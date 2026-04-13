from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import cv2
import httpx
import numpy as np

from backend.app.events.schema import EventRecord, EventType
from backend.app.events.storage import read_event_record
from backend.app.scene_description.service import (
    MAX_SCENE_DESCRIPTION_CHARS,
    OllamaSceneDescriptionProvider,
    SceneDescriptionConfig,
    SceneDescriptionService,
    backfill_scene_descriptions,
    generate_scene_description_outcome,
    sanitize_scene_description,
)


class SceneDescriptionServiceTest(unittest.TestCase):
    def test_service_updates_pending_event_with_llm_description(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            event_path = temp_path / "events.jsonl"
            snapshot_path = temp_path / "evt_success.jpg"
            snapshot_path.write_bytes(b"fake-image")

            event = EventRecord(
                event_id="evt_success",
                camera_id="cam_01",
                track_id=7,
                event_type=EventType.FALL_SUSPECTED,
                started_at=datetime.fromtimestamp(100, tz=timezone.utc),
                snapshot_path=str(snapshot_path),
                description="실신 의심: 급격한 자세 붕괴 후 움직임이 거의 없음",
                description_status="pending",
            )
            event_path.write_text(
                json.dumps(event.to_dict(), ensure_ascii=True) + "\n",
                encoding="utf-8",
            )

            request_payload: dict[str, object] = {}
            client = httpx.Client(
                transport=httpx.MockTransport(
                    lambda request: _json_response(
                        request=request,
                        captured_payload=request_payload,
                        response_payload={
                            "message": {
                                "content": _structured_response(
                                    age_group="60대",
                                    gender="남성",
                                    upper_clothing="파란 체크 셔츠",
                                    lower_clothing="검은 바지",
                                    action_posture="복도 바닥에 쓰러져 움직임이 거의 없는 상태",
                                    location="복도",
                                    event_phrase="실신이 의심됩니다",
                                )
                            }
                        },
                    )
                )
            )
            service = SceneDescriptionService(
                provider=OllamaSceneDescriptionProvider(
                    config=SceneDescriptionConfig(
                        host="http://ollama.local",
                        model="gemma4:e4b",
                        timeout_seconds=2.0,
                        keep_alive="5m",
                    ),
                    client=client,
                ),
                max_retries=0,
            )
            service.start()
            self.assertTrue(service.enqueue_event(event, event_path))
            service.drain_and_stop()

            updated = read_event_record(event_path, "evt_success")
            self.assertIsNotNone(updated)
            assert updated is not None
            self.assertEqual(updated.description_status, "completed")
            self.assertEqual(updated.description_source, "llm")
            self.assertEqual(
                updated.description,
                "연령대 60대, 성별 남성, 상의 파란 체크 셔츠, 하의 검은 바지, 위치 복도, 행동/자세 복도 바닥에 쓰러져 움직임이 거의 없는 상태, 실신이 의심됩니다.",
            )
            self.assertIsNotNone(updated.description_generated_at)
            self.assertEqual(updated.description_error, "")
            self.assertEqual(request_payload["model"], "gemma4:e4b")
            self.assertEqual(request_payload["keep_alive"], "5m")
            self.assertFalse(request_payload["stream"])
            self.assertEqual(request_payload["format"], "json")
            self.assertIn("messages", request_payload)
            messages = request_payload["messages"]
            self.assertIsInstance(messages, list)
            assert isinstance(messages, list)
            self.assertEqual(len(messages), 2)
            system_message = messages[0]
            user_message = messages[1]
            self.assertIsInstance(system_message, dict)
            self.assertIsInstance(user_message, dict)
            assert isinstance(system_message, dict)
            assert isinstance(user_message, dict)
            system_prompt = system_message["content"]
            user_prompt = user_message["content"]
            self.assertIsInstance(system_prompt, str)
            self.assertIsInstance(user_prompt, str)
            assert isinstance(system_prompt, str)
            assert isinstance(user_prompt, str)
            self.assertIn("JSON 객체 하나만 반환", system_prompt)
            self.assertIn("age_group, gender, upper_clothing, lower_clothing, action_posture, location, event_phrase", system_prompt)
            self.assertIn("10대, 20대, 30대, 40대, 50대, 60대, 70대, 80대 이상, 확인 어려움", system_prompt)
            self.assertIn("남성, 여성, 확인 어려움", system_prompt)
            self.assertIn("필수 키: age_group, gender, upper_clothing, lower_clothing, action_posture, location, event_phrase", user_prompt)
            self.assertIn("event_phrase 허용값: 실신이 의심됩니다 | 실신 상황으로 추정됩니다", user_prompt)
            self.assertIn("\"age_group\": \"50대\"", user_prompt)

    def test_service_keeps_rule_description_when_response_validation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            event_path = temp_path / "events.jsonl"
            snapshot_path = temp_path / "evt_fallback.jpg"
            snapshot_path.write_bytes(b"fake-image")

            event = EventRecord(
                event_id="evt_fallback",
                camera_id="cam_01",
                track_id=11,
                event_type=EventType.WANDERING_SUSPECTED,
                started_at=datetime.fromtimestamp(200, tz=timezone.utc),
                snapshot_path=str(snapshot_path),
                description="배회 의심: 동일 구역 내 반복 이동이 지속됨",
                description_status="pending",
            )
            event_path.write_text(
                json.dumps(event.to_dict(), ensure_ascii=True) + "\n",
                encoding="utf-8",
            )

            client = httpx.Client(
                transport=httpx.MockTransport(
                    lambda request: _json_response(
                        request=request,
                        captured_payload={},
                        response_payload={
                            "message": {
                                "content": _structured_response(
                                    age_group="중년",
                                    gender="남성",
                                    upper_clothing="검은 셔츠",
                                    lower_clothing="검은 바지",
                                    action_posture="복도를 반복 이동하는 모습",
                                    location="복도",
                                    event_phrase="배회가 의심됩니다",
                                )
                            }
                        },
                    )
                )
            )
            service = SceneDescriptionService(
                provider=OllamaSceneDescriptionProvider(
                    config=SceneDescriptionConfig(
                        host="http://ollama.local",
                        timeout_seconds=2.0,
                    ),
                    client=client,
                ),
                max_retries=0,
            )
            service.start()
            self.assertTrue(service.enqueue_event(event, event_path))
            service.drain_and_stop()

            updated = read_event_record(event_path, "evt_fallback")
            self.assertIsNotNone(updated)
            assert updated is not None
            self.assertEqual(updated.description_status, "fallback")
            self.assertEqual(updated.description, event.description)
            self.assertEqual(updated.description_error, "response_validation_failed")

    def test_service_marks_failed_when_provider_is_unreachable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            event_path = temp_path / "events.jsonl"
            snapshot_path = temp_path / "evt_failed.jpg"
            snapshot_path.write_bytes(b"fake-image")

            event = EventRecord(
                event_id="evt_failed",
                camera_id="cam_01",
                track_id=5,
                event_type=EventType.FALL_SUSPECTED,
                started_at=datetime.fromtimestamp(300, tz=timezone.utc),
                snapshot_path=str(snapshot_path),
                description="실신 의심: 급격한 자세 붕괴 후 움직임이 거의 없음",
                description_status="pending",
            )
            event_path.write_text(
                json.dumps(event.to_dict(), ensure_ascii=True) + "\n",
                encoding="utf-8",
            )

            service = SceneDescriptionService(
                provider=OllamaSceneDescriptionProvider(
                    config=SceneDescriptionConfig(
                        host="http://ollama.local",
                        timeout_seconds=0.2,
                    ),
                    client=httpx.Client(
                        transport=httpx.MockTransport(
                            lambda request: (_ for _ in ()).throw(
                                httpx.ConnectError("connection refused", request=request)
                            )
                        )
                    ),
                ),
                max_retries=0,
            )
            service.start()
            self.assertTrue(service.enqueue_event(event, event_path))
            service.drain_and_stop()

            updated = read_event_record(event_path, "evt_failed")
            self.assertIsNotNone(updated)
            assert updated is not None
            self.assertEqual(updated.description_status, "failed")
            self.assertEqual(updated.description, event.description)
            self.assertTrue(updated.description_error)

    def test_backfill_scene_descriptions_updates_existing_event_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            event_path = temp_path / "demo_events.jsonl"
            snapshot_a = temp_path / "demo_a.jpg"
            snapshot_b = temp_path / "demo_b.jpg"
            snapshot_a.write_bytes(b"fake-a")
            snapshot_b.write_bytes(b"fake-b")

            first = EventRecord(
                event_id="evt_backfill_a",
                camera_id="cam_a",
                track_id=1,
                event_type=EventType.FALL_SUSPECTED,
                started_at=datetime.fromtimestamp(1, tz=timezone.utc),
                snapshot_path=str(snapshot_a),
                description="실신 샘플: demo_a",
            )
            second = EventRecord(
                event_id="evt_backfill_b",
                camera_id="cam_b",
                track_id=2,
                event_type=EventType.WANDERING_SUSPECTED,
                started_at=datetime.fromtimestamp(2, tz=timezone.utc),
                snapshot_path=str(snapshot_b),
                description="배회 샘플: demo_b",
            )
            event_path.write_text(
                "\n".join(
                    [
                        json.dumps(first.to_dict(), ensure_ascii=True),
                        json.dumps(second.to_dict(), ensure_ascii=True),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            responses = iter(
                [
                    {
                        "message": {
                            "content": _structured_response(
                                age_group="70대",
                                gender="남성",
                                upper_clothing="베이지색 셔츠",
                                lower_clothing="어두운 바지",
                                action_posture="바닥에 쓰러져 움직임이 거의 없는 상태",
                                location="복도",
                                event_phrase="실신 상황으로 추정됩니다",
                            )
                        }
                    },
                    {
                        "message": {
                            "content": _structured_response(
                                age_group="50대",
                                gender="확인 어려움",
                                upper_clothing="밝은색 긴팔 상의",
                                lower_clothing="어두운 바지",
                                action_posture="서성이며 반복 이동하는 모습",
                                location="복도",
                                event_phrase="배회 상황으로 추정됩니다",
                            )
                        }
                    },
                ]
            )
            client = httpx.Client(
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, json=next(responses))
                )
            )
            provider = OllamaSceneDescriptionProvider(
                config=SceneDescriptionConfig(host="http://ollama.local", timeout_seconds=2.0),
                client=client,
            )
            try:
                summary = backfill_scene_descriptions(
                    source_paths=[event_path],
                    provider=provider,
                    max_retries=0,
                )
            finally:
                provider.close()

            self.assertEqual(summary["files"], 1)
            self.assertEqual(summary["events_seen"], 2)
            self.assertEqual(summary["events_updated"], 2)
            self.assertEqual(summary["completed"], 2)

            updated_first = read_event_record(event_path, "evt_backfill_a")
            updated_second = read_event_record(event_path, "evt_backfill_b")
            self.assertIsNotNone(updated_first)
            self.assertIsNotNone(updated_second)
            assert updated_first is not None
            assert updated_second is not None
            self.assertEqual(updated_first.description_status, "completed")
            self.assertEqual(updated_second.description_status, "completed")
            self.assertEqual(updated_first.description_source, "llm")
            self.assertEqual(updated_second.description_source, "llm")

    def test_backfill_preserves_completed_description_when_regeneration_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            event_path = temp_path / "demo_events.jsonl"
            snapshot_path = temp_path / "demo.jpg"
            snapshot_path.write_bytes(b"fake-image")

            event = EventRecord(
                event_id="evt_keep_completed",
                camera_id="cam_keep",
                track_id=4,
                event_type=EventType.FALL_SUSPECTED,
                started_at=datetime.fromtimestamp(10, tz=timezone.utc),
                snapshot_path=str(snapshot_path),
                description="복도 바닥에 쓰러진 사람이 보여 실신이 의심됩니다.",
                description_status="completed",
                description_source="llm",
                description_generated_at=datetime.fromtimestamp(11, tz=timezone.utc),
            )
            event_path.write_text(
                json.dumps(event.to_dict(), ensure_ascii=True) + "\n",
                encoding="utf-8",
            )

            provider = _TimeoutProvider()
            summary = backfill_scene_descriptions(
                source_paths=[event_path],
                provider=provider,
                max_retries=0,
                overwrite_completed=True,
            )

            updated = read_event_record(event_path, "evt_keep_completed")
            self.assertIsNotNone(updated)
            assert updated is not None
            self.assertEqual(summary["events_seen"], 1)
            self.assertEqual(summary["events_updated"], 0)
            self.assertEqual(summary["events_skipped"], 1)
            self.assertEqual(updated.description_status, "completed")
            self.assertEqual(updated.description_source, "llm")
            self.assertIsNotNone(updated.description_generated_at)
            self.assertEqual(updated.description, event.description)

    def test_scene_description_prefers_overlay_frame_when_overlay_clip_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            snapshot_path = temp_path / "evt_overlay.jpg"
            overlay_clip_path = temp_path / "evt_overlay.mp4"

            cv2.imwrite(str(snapshot_path), np.zeros((40, 40, 3), dtype=np.uint8))

            writer = cv2.VideoWriter(
                str(overlay_clip_path),
                cv2.VideoWriter_fourcc(*"mp4v"),
                4.0,
                (40, 40),
            )
            try:
                for value in (10, 40, 220, 240):
                    frame = np.full((40, 40, 3), value, dtype=np.uint8)
                    writer.write(frame)
            finally:
                writer.release()

            event = EventRecord(
                event_id="evt_overlay_preferred",
                camera_id="cam_overlay",
                track_id=3,
                event_type=EventType.WANDERING_SUSPECTED,
                started_at=datetime.fromtimestamp(10, tz=timezone.utc),
                snapshot_path=str(snapshot_path),
                overlay_clip_path=str(overlay_clip_path),
                description="배회 의심: 동일 구역 내 반복 이동이 지속됨",
                description_status="pending",
            )

            provider = _RecordingProvider()
            outcome = generate_scene_description_outcome(
                record=event,
                provider=provider,
                max_retries=0,
            )

            self.assertEqual(outcome.description_status, "completed")
            self.assertIsNotNone(provider.snapshot_path)
            assert provider.snapshot_path is not None
            self.assertTrue(provider.snapshot_path.name.endswith("_llm.jpg"))
            self.assertGreater(provider.mean_pixel_value, 100.0)

    def test_scene_description_focuses_on_target_bbox_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            overlay_clip_path = temp_path / "evt_focus.mp4"
            snapshot_path = temp_path / "evt_focus.jpg"
            cv2.imwrite(str(snapshot_path), np.zeros((80, 120, 3), dtype=np.uint8))

            writer = cv2.VideoWriter(
                str(overlay_clip_path),
                cv2.VideoWriter_fourcc(*"mp4v"),
                4.0,
                (120, 80),
            )
            try:
                for _ in range(4):
                    frame = np.full((80, 120, 3), 25, dtype=np.uint8)
                    frame[18:62, 42:78] = 235
                    writer.write(frame)
            finally:
                writer.release()

            event = EventRecord(
                event_id="evt_focus_target",
                camera_id="cam_focus",
                track_id=9,
                event_type=EventType.WANDERING_SUSPECTED,
                started_at=datetime.fromtimestamp(20, tz=timezone.utc),
                snapshot_path=str(snapshot_path),
                overlay_clip_path=str(overlay_clip_path),
                description="배회 의심: 동일 구역 내 반복 이동이 지속됨",
                description_status="pending",
                details={"target_bbox": [42, 18, 78, 62]},
            )

            provider = _RecordingProvider()
            outcome = generate_scene_description_outcome(
                record=event,
                provider=provider,
                max_retries=0,
            )

            self.assertEqual(outcome.description_status, "completed")
            self.assertIsNotNone(provider.snapshot_path)
            assert provider.snapshot_path is not None
            self.assertTrue(provider.snapshot_path.name.endswith("_focus.jpg"))
            self.assertIsNotNone(provider.image_shape)
            assert provider.image_shape is not None
            self.assertLess(provider.image_shape[1], 120)
            self.assertGreater(provider.mean_pixel_value, 50.0)

    def test_sanitize_scene_description_removes_overlay_ui_phrases(self) -> None:
        cleaned = sanitize_scene_description(
            _structured_response(
                age_group="60대",
                gender="남성",
                upper_clothing="강조된 파란 체크 셔츠",
                lower_clothing="검은 바지",
                action_posture="강조된 복도 바닥에 쓰러져 움직임이 거의 없는 상태",
                location="복도",
                event_phrase="실신 상황으로 추정됩니다",
            ),
            EventType.FALL_SUSPECTED,
        )

        self.assertEqual(
            cleaned,
            "연령대 60대, 성별 남성, 상의 파란 체크 셔츠, 하의 검은 바지, 위치 복도, 행동/자세 복도 바닥에 쓰러져 움직임이 거의 없는 상태, 실신 상황으로 추정됩니다.",
        )

    def test_sanitize_scene_description_rejects_unstructured_or_invalid_slots(self) -> None:
        self.assertIsNone(
            sanitize_scene_description(
                "체크 셔츠를 입은 남성이 복도에서 쓰러져 있어 실신이 의심됩니다.",
                EventType.FALL_SUSPECTED,
            )
        )
        self.assertIsNone(
            sanitize_scene_description(
                _structured_response(
                    age_group="성인",
                    gender="남성",
                    upper_clothing="검은 셔츠",
                    lower_clothing="검은 바지",
                    action_posture="복도를 반복 이동하는 모습",
                    location="복도",
                    event_phrase="배회가 의심됩니다",
                ),
                EventType.WANDERING_SUSPECTED,
            )
        )

    def test_sanitize_scene_description_limits_output_length_with_period(self) -> None:
        cleaned = sanitize_scene_description(
            _structured_response(
                age_group="60대",
                gender="남성",
                upper_clothing="아주 긴 설명의 진한 남색 체크 패턴 셔츠",
                lower_clothing="아주 긴 설명의 어두운색 작업용 바지",
                action_posture="복도 바닥에 쓰러져 움직임이 거의 없는 상태",
                location="매우 긴 설명의 복도 끝 벽면 인접 구역",
                event_phrase="실신이 의심됩니다",
            ),
            EventType.FALL_SUSPECTED,
        )

        self.assertIsNotNone(cleaned)
        assert cleaned is not None
        self.assertLessEqual(len(cleaned), MAX_SCENE_DESCRIPTION_CHARS)
        self.assertTrue(cleaned.endswith("."))

def _json_response(
    request: httpx.Request,
    captured_payload: dict[str, object],
    response_payload: dict[str, object],
) -> httpx.Response:
    captured_payload.update(json.loads(request.content.decode("utf-8")))
    return httpx.Response(200, json=response_payload)


class _RecordingProvider:
    def __init__(self) -> None:
        self.snapshot_path: Path | None = None
        self.mean_pixel_value: float = 0.0
        self.image_shape: tuple[int, int, int] | None = None

    def generate_description(self, event: EventRecord, snapshot_path: Path) -> str:
        self.snapshot_path = snapshot_path
        image = cv2.imread(str(snapshot_path))
        assert image is not None
        self.mean_pixel_value = float(image.mean())
        self.image_shape = tuple(int(value) for value in image.shape)
        return _structured_response(
            age_group="50대",
            gender="남성",
            upper_clothing="밝은색 줄무늬 셔츠",
            lower_clothing="어두운 바지",
            action_posture="같은 구역을 반복 이동하는 모습",
            location="복도",
            event_phrase="배회 상황으로 추정됩니다",
        )

    def close(self) -> None:
        return None


class _TimeoutProvider:
    def generate_description(self, event: EventRecord, snapshot_path: Path) -> str:
        raise TimeoutError("timed out")

    def close(self) -> None:
        return None


def _structured_response(
    *,
    age_group: str,
    gender: str,
    upper_clothing: str,
    lower_clothing: str,
    action_posture: str,
    location: str,
    event_phrase: str,
) -> str:
    return json.dumps(
        {
            "age_group": age_group,
            "gender": gender,
            "upper_clothing": upper_clothing,
            "lower_clothing": lower_clothing,
            "action_posture": action_posture,
            "location": location,
            "event_phrase": event_phrase,
        },
        ensure_ascii=False,
    )


if __name__ == "__main__":
    unittest.main()
