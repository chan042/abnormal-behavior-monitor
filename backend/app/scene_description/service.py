from __future__ import annotations

import base64
import json
import queue
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Protocol, Sequence

import httpx

from ..events.schema import EventRecord, EventType, event_record_from_dict
from ..events.storage import read_event_record, update_event_record, utc_now
from ..paths import PROJECT_ROOT

MAX_SCENE_DESCRIPTION_CHARS = 160
SCENE_DESCRIPTION_AGE_GROUPS = (
    "10대",
    "20대",
    "30대",
    "40대",
    "50대",
    "60대",
    "70대",
    "80대 이상",
    "확인 어려움",
)
SCENE_DESCRIPTION_GENDERS = ("남성", "여성", "확인 어려움")
SCENE_DESCRIPTION_REQUIRED_KEYS = (
    "age_group",
    "gender",
    "upper_clothing",
    "lower_clothing",
    "action_posture",
    "location",
    "event_phrase",
)
SCENE_DESCRIPTION_EVENT_PHRASES = {
    EventType.FALL_SUSPECTED: (
        "실신이 의심됩니다",
        "실신 상황으로 추정됩니다",
    ),
    EventType.WANDERING_SUSPECTED: (
        "배회가 의심됩니다",
        "배회 상황으로 추정됩니다",
    ),
}
UPPER_CLOTHING_TOKENS = (
    "상의",
    "셔츠",
    "티셔츠",
    "재킷",
    "자켓",
    "점퍼",
    "후드",
    "니트",
    "블라우스",
    "가디건",
    "코트",
    "패딩",
    "조끼",
    "원피스",
)
LOWER_CLOTHING_TOKENS = (
    "하의",
    "바지",
    "청바지",
    "슬랙스",
    "반바지",
    "치마",
    "스커트",
    "레깅스",
    "트레이닝",
)


class SceneDescriptionProvider(Protocol):
    def generate_description(self, event: EventRecord, snapshot_path: Path) -> str:
        ...

    def close(self) -> None:
        ...


@dataclass(frozen=True)
class SceneDescriptionConfig:
    model: str = "gemma4:e4b"
    host: str = "http://127.0.0.1:11434"
    timeout_seconds: float = 8.0
    keep_alive: str = "5m"
    max_retries: int = 1


@dataclass(frozen=True)
class QueuedSceneDescriptionJob:
    event_id: str
    source_path: Path
    fallback_description: str


@dataclass(frozen=True)
class SceneDescriptionOutcome:
    description: str
    description_status: str
    description_source: str
    description_generated_at: Optional[str]
    description_error: str


@dataclass(frozen=True)
class StructuredSceneDescription:
    age_group: str
    gender: str
    upper_clothing: str
    lower_clothing: str
    action_posture: str
    location: str
    event_phrase: str


class OllamaSceneDescriptionProvider:
    def __init__(
        self,
        config: SceneDescriptionConfig,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self.config = config
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=config.timeout_seconds)

    def generate_description(self, event: EventRecord, snapshot_path: Path) -> str:
        response = self._client.post(
            f"{self.config.host.rstrip('/')}/api/chat",
            json={
                "model": self.config.model,
                "stream": False,
                "format": "json",
                "keep_alive": self.config.keep_alive,
                "messages": [
                    {
                        "role": "system",
                        "content": _build_system_prompt(),
                    },
                    {
                        "role": "user",
                        "content": _build_user_prompt(event),
                        "images": [_encode_image(snapshot_path)],
                    },
                ],
            },
        )
        response.raise_for_status()
        payload = response.json()
        message = payload.get("message")
        if not isinstance(message, dict):
            raise ValueError("Ollama response is missing the assistant message payload")
        content = message.get("content")
        if not isinstance(content, str):
            raise ValueError("Ollama response content is not a string")
        return content

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


class SceneDescriptionService:
    def __init__(
        self,
        provider: SceneDescriptionProvider,
        max_retries: int = 1,
        worker_name: str = "scene-description-worker",
    ) -> None:
        self.provider = provider
        self.max_retries = max(0, int(max_retries))
        self.worker_name = worker_name
        self._queue: "queue.Queue[Optional[QueuedSceneDescriptionJob]]" = queue.Queue()
        self._queued_event_ids: set[str] = set()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._stop_requested = False

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_requested = False
            thread = threading.Thread(
                target=self._run_worker,
                name=self.worker_name,
                daemon=True,
            )
            thread.start()
            self._thread = thread

    def enqueue_event(self, event: EventRecord, source_path: Path) -> bool:
        with self._lock:
            if self._stop_requested or event.event_id in self._queued_event_ids:
                return False
            self._queued_event_ids.add(event.event_id)

        self._queue.put(
            QueuedSceneDescriptionJob(
                event_id=event.event_id,
                source_path=source_path,
                fallback_description=event.description,
            )
        )
        return True

    def stop(self) -> None:
        with self._lock:
            self._stop_requested = True
        self._queue.put(None)
        if self._thread is not None:
            self._thread.join(timeout=2)
        self.provider.close()

    def drain_and_stop(self) -> None:
        self._queue.join()
        self.stop()

    def _run_worker(self) -> None:
        while True:
            job = self._queue.get()
            try:
                if job is None:
                    return
                self._process_job(job)
            finally:
                if job is not None:
                    with self._lock:
                        self._queued_event_ids.discard(job.event_id)
                self._queue.task_done()

    def _process_job(self, job: QueuedSceneDescriptionJob) -> None:
        record = read_event_record(job.source_path, job.event_id)
        if record is None or record.description_status != "pending":
            return

        outcome = generate_scene_description_outcome(
            record=record,
            provider=self.provider,
            max_retries=self.max_retries,
        )
        update_event_record(
            job.source_path,
            job.event_id,
            lambda payload: _apply_description_update(
                payload=payload,
                description=outcome.description,
                description_status=outcome.description_status,
                description_source=outcome.description_source,
                description_generated_at=outcome.description_generated_at,
                description_error=outcome.description_error,
            ),
        )


def backfill_scene_descriptions(
    source_paths: Sequence[Path],
    provider: SceneDescriptionProvider,
    max_retries: int = 1,
    overwrite_completed: bool = False,
) -> Dict[str, object]:
    summary = {
        "files": 0,
        "events_seen": 0,
        "events_updated": 0,
        "events_skipped": 0,
        "completed": 0,
        "fallback": 0,
        "failed": 0,
    }

    for source_path in source_paths:
        if not source_path.exists():
            continue
        summary["files"] += 1
        for record in _read_event_records(source_path):
            summary["events_seen"] += 1
            if not overwrite_completed and record.description_status == "completed":
                summary["events_skipped"] += 1
                continue
            outcome = generate_scene_description_outcome(
                record=record,
                provider=provider,
                max_retries=max_retries,
            )
            if (
                overwrite_completed
                and record.description_status == "completed"
                and outcome.description_status != "completed"
            ):
                summary["events_skipped"] += 1
                continue
            update_event_record(
                source_path,
                record.event_id,
                lambda payload, outcome=outcome: _apply_description_update(
                    payload=payload,
                    description=outcome.description,
                    description_status=outcome.description_status,
                    description_source=outcome.description_source,
                    description_generated_at=outcome.description_generated_at,
                    description_error=outcome.description_error,
                ),
            )
            summary["events_updated"] += 1
            summary[outcome.description_status] += 1

    return summary


def generate_scene_description_outcome(
    record: EventRecord,
    provider: SceneDescriptionProvider,
    max_retries: int = 1,
) -> SceneDescriptionOutcome:
    snapshot_path = _resolve_scene_description_image(record)
    fallback_description = record.description
    if snapshot_path is None or not snapshot_path.exists():
        return SceneDescriptionOutcome(
            description=fallback_description,
            description_status="fallback",
            description_source="rule",
            description_generated_at=None,
            description_error="snapshot_missing",
        )

    last_error = ""
    saw_validation_failure = False
    attempts = max(0, int(max_retries)) + 1
    for _ in range(attempts):
        try:
            raw_description = provider.generate_description(record, snapshot_path)
            description = sanitize_scene_description(raw_description, record.event_type)
            if description is None:
                saw_validation_failure = True
                last_error = "response_validation_failed"
                continue
            return SceneDescriptionOutcome(
                description=description,
                description_status="completed",
                description_source="llm",
                description_generated_at=utc_now().isoformat(),
                description_error="",
            )
        except Exception as exc:
            last_error = str(exc)

    if saw_validation_failure:
        return SceneDescriptionOutcome(
            description=fallback_description,
            description_status="fallback",
            description_source="fallback",
            description_generated_at=None,
            description_error="response_validation_failed",
        )

    return SceneDescriptionOutcome(
        description=fallback_description,
        description_status="failed",
        description_source=record.description_source or "rule",
        description_generated_at=None,
        description_error=last_error or "description_generation_failed",
    )


def sanitize_scene_description(
    value: str,
    event_type: EventType,
) -> Optional[str]:
    structured = _parse_structured_scene_description(value, event_type)
    if structured is None:
        return None
    return _compose_scene_description(structured)


def _build_system_prompt() -> str:
    return (
        "당신은 CCTV 이상행동 관제용 상황 설명 보조 모델이다. "
        "사진과 메타데이터를 바탕으로 AI EVENT 배지와 강조 박스가 붙은 사람 한 명만 설명한다. "
        "보이는 사실만 사용하고 과도한 추정, 신원 특정, 질병 단정, 감정 과장은 금지한다. "
        "출력은 설명문이 아니라 JSON 객체 하나만 반환하고, 마크다운, 코드블록, 부가 문장은 금지한다. "
        "키는 age_group, gender, upper_clothing, lower_clothing, action_posture, location, event_phrase만 사용하고 모두 반드시 채운다. "
        "age_group은 10대, 20대, 30대, 40대, 50대, 60대, 70대, 80대 이상, 확인 어려움 중 하나만 사용한다. "
        "gender는 남성, 여성, 확인 어려움 중 하나만 사용한다. "
        "upper_clothing과 lower_clothing은 색상과 종류를 함께 적고, 불명확하면 각각 식별 어려운 상의, 식별 어려운 하의로 적는다. "
        "action_posture는 대상의 자세나 움직임을 짧은 명사구로 적고, location은 장소만 짧게 적거나 확인 어려움으로 적는다. "
        "event_phrase는 이벤트 유형에 맞는 의심 또는 추정 문구만 사용한다. "
        "배지가 없는 다른 인물의 수, 행동, 위치는 사건 이해에 꼭 필요한 경우가 아니면 문장에 넣지 않는다. "
        "배지, 박스, 오버레이, AI EVENT 같은 UI 표현 자체는 어떤 필드에도 넣지 않는다."
    )


def _build_user_prompt(event: EventRecord) -> str:
    event_label = {
        EventType.FALL_SUSPECTED: "실신 의심",
        EventType.WANDERING_SUSPECTED: "배회 의심",
    }[event.event_type]
    allowed_event_phrases = " | ".join(SCENE_DESCRIPTION_EVENT_PHRASES[event.event_type])
    details = (
        json.dumps(event.details, ensure_ascii=False, sort_keys=True)
        if event.details is not None
        else "{}"
    )
    example_payload = {
        "age_group": "50대",
        "gender": "남성",
        "upper_clothing": "파란 체크 셔츠",
        "lower_clothing": "검은 바지",
        "action_posture": (
            "바닥에 쓰러져 움직임이 거의 없는 상태"
            if event.event_type == EventType.FALL_SUSPECTED
            else "서성이며 반복 이동하는 모습"
        ),
        "location": "복도",
        "event_phrase": SCENE_DESCRIPTION_EVENT_PHRASES[event.event_type][0],
    }
    return "\n".join(
        [
            "다음 이벤트를 JSON 객체 하나로만 작성하세요.",
            f"- 이벤트 유형: {event_label}",
            f"- 카메라 ID: {event.camera_id}",
            f"- ROI: {event.roi_id or 'GLOBAL'}",
            f"- 규칙 엔진 메타데이터: {details}",
            f"- 기본 설명: {event.description}",
            "- 이미지에서 'AI EVENT' 배지와 강조 박스가 붙은 대상이 설명의 주인공입니다.",
            "- 다른 사람이 함께 보여도 배지가 없는 인물은 설명에서 제외하고, 사건 주체로 단정하지 마세요.",
            "- 배지나 박스가 보이더라도 그 UI 요소를 어떤 필드에도 직접 적지 마세요.",
            f"- 필수 키: {', '.join(SCENE_DESCRIPTION_REQUIRED_KEYS)}",
            f"- age_group 허용값: {' | '.join(SCENE_DESCRIPTION_AGE_GROUPS)}",
            f"- gender 허용값: {' | '.join(SCENE_DESCRIPTION_GENDERS)}",
            "- upper_clothing/lower_clothing은 복장 색상과 종류를 포함하고, 불명확하면 식별 어려운 상의 / 식별 어려운 하의로 작성하세요.",
            "- action_posture는 위치를 제외한 자세나 움직임만 적고, 명사구 형태로 작성하세요.",
            "- location은 장소만 짧게 적고 불명확하면 확인 어려움으로 작성하세요.",
            f"- event_phrase 허용값: {allowed_event_phrases}",
            f"- 예시 JSON: {json.dumps(example_payload, ensure_ascii=False)}",
            "- JSON 외 다른 텍스트, 설명, 코드블록 금지",
        ]
    )


def _encode_image(path: Path) -> str:
    try:
        import cv2  # type: ignore
    except ModuleNotFoundError:
        return base64.b64encode(path.read_bytes()).decode("ascii")

    image = cv2.imread(str(path))
    if image is None:
        return base64.b64encode(path.read_bytes()).decode("ascii")

    height, width = image.shape[:2]
    max_dimension = 960
    longest_edge = max(height, width)
    if longest_edge > max_dimension:
        scale = max_dimension / float(longest_edge)
        resized_width = max(1, int(round(width * scale)))
        resized_height = max(1, int(round(height * scale)))
        image = cv2.resize(
            image,
            (resized_width, resized_height),
            interpolation=cv2.INTER_AREA,
        )

    encoded_ok, encoded = cv2.imencode(
        ".jpg",
        image,
        [int(cv2.IMWRITE_JPEG_QUALITY), 82],
    )
    if not encoded_ok:
        return base64.b64encode(path.read_bytes()).decode("ascii")
    return base64.b64encode(encoded.tobytes()).decode("ascii")


def _resolve_snapshot_path(raw_path: Optional[str]) -> Optional[Path]:
    if not raw_path:
        return None
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _resolve_scene_description_image(record: EventRecord) -> Optional[Path]:
    overlay_clip_path = _resolve_snapshot_path(record.overlay_clip_path)
    if overlay_clip_path is not None and overlay_clip_path.exists():
        extracted_path = _extract_overlay_frame_for_llm(record, overlay_clip_path)
        if extracted_path is not None and extracted_path.exists():
            focused_path = _write_focus_image(record, extracted_path)
            if focused_path is not None and focused_path.exists():
                return focused_path
            return extracted_path

    snapshot_path = _resolve_snapshot_path(record.snapshot_path)
    if snapshot_path is None or not snapshot_path.exists():
        return snapshot_path

    focused_path = _write_focus_image(record, snapshot_path)
    if focused_path is not None and focused_path.exists():
        return focused_path
    return snapshot_path


def _extract_overlay_frame_for_llm(
    record: EventRecord,
    overlay_clip_path: Path,
) -> Optional[Path]:
    try:
        import cv2  # type: ignore
    except ModuleNotFoundError:
        return None

    capture = cv2.VideoCapture(str(overlay_clip_path))
    if not capture.isOpened():
        return None
    try:
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        target_frame_index = max(0, frame_count // 2)
        capture.set(cv2.CAP_PROP_POS_FRAMES, target_frame_index)
        ok, frame = capture.read()
        if not ok or frame is None:
            return None

        base_snapshot_path = _resolve_snapshot_path(record.snapshot_path)
        if base_snapshot_path is not None:
            output_path = base_snapshot_path.with_name(base_snapshot_path.stem + "_llm.jpg")
        else:
            output_path = overlay_clip_path.with_name(overlay_clip_path.stem + "_llm.jpg")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(output_path), frame):
            return None
        return output_path
    finally:
        capture.release()


def _write_focus_image(
    record: EventRecord,
    source_image_path: Path,
) -> Optional[Path]:
    bbox = _extract_target_bbox(record)
    if bbox is None:
        return None

    try:
        import cv2  # type: ignore
    except ModuleNotFoundError:
        return None

    image = cv2.imread(str(source_image_path))
    if image is None:
        return None

    crop = _crop_focus_region(image, bbox)
    if crop is None:
        return None

    output_path = source_image_path.with_name(source_image_path.stem + "_focus.jpg")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), crop):
        return None
    return output_path


def _extract_target_bbox(
    record: EventRecord,
) -> Optional[tuple[float, float, float, float]]:
    details = record.details
    if not isinstance(details, dict):
        return None

    raw_bbox = details.get("target_bbox") or details.get("bbox")
    if not isinstance(raw_bbox, (list, tuple)) or len(raw_bbox) != 4:
        return None

    try:
        x1, y1, x2, y2 = (float(value) for value in raw_bbox)
    except (TypeError, ValueError):
        return None

    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


def _crop_focus_region(
    image: object,
    bbox: tuple[float, float, float, float],
) -> Optional[object]:
    height, width = image.shape[:2]
    x1, y1, x2, y2 = bbox
    box_width = max(1.0, x2 - x1)
    box_height = max(1.0, y2 - y1)

    pad_x = box_width * 0.55
    pad_top = box_height * 0.9
    pad_bottom = box_height * 0.35

    crop_x1 = max(0, int(round(x1 - pad_x)))
    crop_y1 = max(0, int(round(y1 - pad_top)))
    crop_x2 = min(width, int(round(x2 + pad_x)))
    crop_y2 = min(height, int(round(y2 + pad_bottom)))

    if crop_x2 <= crop_x1 or crop_y2 <= crop_y1:
        return None

    crop = image[crop_y1:crop_y2, crop_x1:crop_x2]
    if crop.size == 0:
        return None
    return crop


def _parse_structured_scene_description(
    value: str,
    event_type: EventType,
) -> Optional[StructuredSceneDescription]:
    payload = _extract_scene_description_payload(value)
    if payload is None:
        return None

    age_group = _normalize_age_group(payload.get("age_group"))
    gender = _normalize_gender(payload.get("gender"))
    upper_clothing = _normalize_upper_clothing(payload.get("upper_clothing"))
    lower_clothing = _normalize_lower_clothing(payload.get("lower_clothing"))
    action_posture = _normalize_action_posture(payload.get("action_posture"))
    location = _normalize_location(payload.get("location"))
    event_phrase = _normalize_event_phrase(payload.get("event_phrase"), event_type)
    if (
        age_group is None
        or gender is None
        or upper_clothing is None
        or lower_clothing is None
        or action_posture is None
        or location is None
        or event_phrase is None
    ):
        return None

    return StructuredSceneDescription(
        age_group=age_group,
        gender=gender,
        upper_clothing=upper_clothing,
        lower_clothing=lower_clothing,
        action_posture=action_posture,
        location=location,
        event_phrase=event_phrase,
    )


def _extract_scene_description_payload(value: str) -> Optional[Dict[str, object]]:
    raw_payload = _load_json_object(value)
    if raw_payload is None:
        return None
    if _has_scene_description_keys(raw_payload):
        return raw_payload
    for key in ("result", "scene_description", "data", "payload"):
        nested = raw_payload.get(key)
        if isinstance(nested, dict) and _has_scene_description_keys(nested):
            return nested
    return None


def _load_json_object(value: str) -> Optional[Dict[str, object]]:
    stripped = value.strip()
    if not stripped:
        return None
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    if not (stripped.startswith("{") and stripped.endswith("}")):
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        stripped = stripped[start : end + 1]
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, str):
        try:
            nested = json.loads(payload)
        except json.JSONDecodeError:
            return None
        payload = nested
    if not isinstance(payload, dict):
        return None
    return payload


def _has_scene_description_keys(payload: Dict[str, object]) -> bool:
    return all(key in payload for key in SCENE_DESCRIPTION_REQUIRED_KEYS)


def _clean_scene_field_value(value: object) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = value.replace("\r", " ").replace("\n", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip("\"'` ")
    cleaned = re.sub(r"AI\s*EVENT[가-힣]*", "", cleaned, flags=re.IGNORECASE)
    for token in (
        "AI 이벤트 배지",
        "강조 박스",
        "강조된 영역",
        "강조된 대상",
        "강조된",
        "표시된",
        "배지",
        "오버레이",
        "박스",
    ):
        cleaned = cleaned.replace(token, "")
    return re.sub(r"\s+", " ", cleaned).strip(" ,;:.")


def _normalize_age_group(value: object) -> Optional[str]:
    cleaned = _clean_scene_field_value(value)
    if not cleaned:
        return None
    if cleaned in SCENE_DESCRIPTION_AGE_GROUPS:
        return cleaned
    if cleaned in ("연령대 식별이 어려움", "연령 식별이 어려움", "연령 추정이 어려움", "불명", "알 수 없음"):
        return "확인 어려움"
    match = re.search(r"(10|20|30|40|50|60|70|80)대", cleaned)
    if not match:
        return None
    age_group = f"{match.group(1)}대"
    if age_group == "80대" or "이상" in cleaned:
        return "80대 이상" if match.group(1) == "80" else age_group
    return age_group


def _normalize_gender(value: object) -> Optional[str]:
    cleaned = _clean_scene_field_value(value)
    if not cleaned:
        return None
    if any(token in cleaned for token in ("남성", "남자")):
        return "남성"
    if any(token in cleaned for token in ("여성", "여자")):
        return "여성"
    if cleaned in ("확인 어려움", "성별 추정이 어려움", "성별 확인이 어려움", "불명", "알 수 없음"):
        return "확인 어려움"
    return None


def _normalize_upper_clothing(value: object) -> Optional[str]:
    return _normalize_clothing_value(
        value=value,
        required_tokens=UPPER_CLOTHING_TOKENS,
        fallback_aliases=("식별 어려운 상의", "상의 식별이 어려움", "상의 색상 식별이 어려움", "확인 어려움"),
        fallback_value="식별 어려운 상의",
        forbidden_tokens=LOWER_CLOTHING_TOKENS,
    )


def _normalize_lower_clothing(value: object) -> Optional[str]:
    return _normalize_clothing_value(
        value=value,
        required_tokens=LOWER_CLOTHING_TOKENS,
        fallback_aliases=("식별 어려운 하의", "하의 식별이 어려움", "확인 어려움"),
        fallback_value="식별 어려운 하의",
        forbidden_tokens=UPPER_CLOTHING_TOKENS,
    )


def _normalize_clothing_value(
    value: object,
    required_tokens: tuple[str, ...],
    fallback_aliases: tuple[str, ...],
    fallback_value: str,
    forbidden_tokens: tuple[str, ...],
) -> Optional[str]:
    cleaned = _clean_scene_field_value(value)
    if not cleaned:
        return None
    if cleaned in fallback_aliases:
        return fallback_value
    if "복장" in cleaned and not any(token in cleaned for token in required_tokens):
        return None
    if any(token in cleaned for token in required_tokens):
        return cleaned
    if any(token in cleaned for token in forbidden_tokens):
        return None
    return None


def _normalize_action_posture(value: object) -> Optional[str]:
    cleaned = _clean_scene_field_value(value)
    if not cleaned:
        return None
    cleaned = re.sub(r"^(행동/자세|행동|자세)는?\s*", "", cleaned)
    if cleaned in ("확인 어려움", "알 수 없음", "불명", "판단 어려움"):
        return None
    if len(cleaned) < 4 or len(cleaned) > 48:
        return None
    return cleaned


def _normalize_location(value: object) -> Optional[str]:
    cleaned = _clean_scene_field_value(value)
    if not cleaned:
        return "확인 어려움"
    cleaned = re.sub(r"^(위치)는?\s*", "", cleaned)
    if cleaned in ("확인 어려움", "위치 식별이 어려움", "알 수 없음", "불명"):
        return "확인 어려움"
    for suffix in ("에서", "부근", "근처", "주변"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)].strip()
            break
    if not cleaned:
        return "확인 어려움"
    if len(cleaned) > 24:
        return None
    return cleaned


def _normalize_event_phrase(
    value: object,
    event_type: EventType,
) -> Optional[str]:
    cleaned = _clean_scene_field_value(value)
    if not cleaned:
        return None
    if cleaned in SCENE_DESCRIPTION_EVENT_PHRASES[event_type]:
        return cleaned
    if event_type == EventType.FALL_SUSPECTED and "실신" in cleaned:
        return (
            "실신 상황으로 추정됩니다"
            if "추정" in cleaned
            else "실신이 의심됩니다"
        )
    if event_type == EventType.WANDERING_SUSPECTED and "배회" in cleaned:
        return (
            "배회 상황으로 추정됩니다"
            if "추정" in cleaned
            else "배회가 의심됩니다"
        )
    return None


def _compose_scene_description(
    description: StructuredSceneDescription,
) -> Optional[str]:
    segments = [
        f"연령대 {description.age_group}",
        f"성별 {description.gender}",
        f"상의 {description.upper_clothing}",
        f"하의 {description.lower_clothing}",
    ]
    if description.location != "확인 어려움":
        segments.append(f"위치 {description.location}")
    segments.append(f"행동/자세 {description.action_posture}")
    body = ", ".join(segments)
    event_phrase = description.event_phrase.rstrip(". ")
    rendered = f"{body}, {event_phrase}"
    if len(rendered) >= MAX_SCENE_DESCRIPTION_CHARS and description.location != "확인 어려움":
        compact_segments = [segment for segment in segments if not segment.startswith("위치 ")]
        rendered = f"{', '.join(compact_segments)}, {event_phrase}"
    if len(rendered) >= MAX_SCENE_DESCRIPTION_CHARS:
        return None
    return rendered + "."


def _read_event_records(source_path: Path) -> list[EventRecord]:
    records: list[EventRecord] = []
    with source_path.open("r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line:
                continue
            records.append(event_record_from_dict(json.loads(line)))
    return records


def _apply_description_update(
    payload: Dict[str, object],
    description: str,
    description_status: str,
    description_source: str,
    description_generated_at: Optional[str],
    description_error: str,
) -> Dict[str, object]:
    payload["description"] = description
    payload["description_status"] = description_status
    payload["description_source"] = description_source
    payload["description_generated_at"] = description_generated_at
    payload["description_error"] = description_error
    payload["updated_at"] = utc_now().isoformat()
    return payload
