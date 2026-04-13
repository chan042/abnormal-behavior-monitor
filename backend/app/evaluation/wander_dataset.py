from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional


_FILENAME_RE = re.compile(
    r"^(?P<take_id>\d+-\d+)_"
    r"(?P<camera_id>cam\d+)_"
    r"(?P<event_id>wander\d+)_"
    r"(?P<place_id>place\d+)_"
    r"(?P<time_of_day>\w+)_"
    r"(?P<season>\w+)$"
)


def _parse_timecode_to_ms(value: str) -> int:
    hours, minutes, seconds = value.split(":")
    return int(round((int(hours) * 3600 + int(minutes) * 60 + float(seconds)) * 1000))


def _project_relative(path: Path, project_root: Path) -> str:
    try:
        return str(path.relative_to(project_root))
    except ValueError:
        return str(path)


@dataclass
class ActionAnnotation:
    action_name: str
    frame_ranges: List[List[int]]
    start_frame: int
    end_frame: int
    start_ms: int
    end_ms: int

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, object]) -> "ActionAnnotation":
        return cls(
            action_name=str(payload["action_name"]),
            frame_ranges=[
                [int(frame_start), int(frame_end)]
                for frame_start, frame_end in payload["frame_ranges"]  # type: ignore[misc]
            ],
            start_frame=int(payload["start_frame"]),
            end_frame=int(payload["end_frame"]),
            start_ms=int(payload["start_ms"]),
            end_ms=int(payload["end_ms"]),
        )


@dataclass
class WanderVideoRecord:
    sample_id: str
    take_id: str
    camera_id: str
    event_id: str
    place_id: str
    season: str
    time_of_day_filename: str
    time_of_day_xml: str
    weather: str
    inout: str
    population: int
    character: str
    width: int
    height: int
    fps_xml: float
    frame_count_xml: int
    duration_ms_xml: int
    event_name: str
    event_start_ms: int
    event_end_ms: int
    keyframe: Optional[int]
    keypoint_xy: Optional[List[int]]
    video_path: str
    xml_path: str
    actions: List[ActionAnnotation]
    roi_profile_id: str
    wandering_threshold_profile: str
    metadata_warnings: List[str]

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["actions"] = [action.to_dict() for action in self.actions]
        return payload

    @classmethod
    def from_dict(cls, payload: Dict[str, object]) -> "WanderVideoRecord":
        return cls(
            sample_id=str(payload["sample_id"]),
            take_id=str(payload["take_id"]),
            camera_id=str(payload["camera_id"]),
            event_id=str(payload["event_id"]),
            place_id=str(payload["place_id"]),
            season=str(payload["season"]),
            time_of_day_filename=str(payload["time_of_day_filename"]),
            time_of_day_xml=str(payload["time_of_day_xml"]),
            weather=str(payload["weather"]),
            inout=str(payload["inout"]),
            population=int(payload["population"]),
            character=str(payload["character"]),
            width=int(payload["width"]),
            height=int(payload["height"]),
            fps_xml=float(payload["fps_xml"]),
            frame_count_xml=int(payload["frame_count_xml"]),
            duration_ms_xml=int(payload["duration_ms_xml"]),
            event_name=str(payload["event_name"]),
            event_start_ms=int(payload["event_start_ms"]),
            event_end_ms=int(payload["event_end_ms"]),
            keyframe=int(payload["keyframe"]) if payload.get("keyframe") is not None else None,
            keypoint_xy=[int(value) for value in payload["keypoint_xy"]]
            if payload.get("keypoint_xy") is not None
            else None,
            video_path=str(payload["video_path"]),
            xml_path=str(payload["xml_path"]),
            actions=[
                ActionAnnotation.from_dict(action_payload)
                for action_payload in payload["actions"]  # type: ignore[misc]
            ],
            roi_profile_id=str(payload["roi_profile_id"]),
            wandering_threshold_profile=str(payload["wandering_threshold_profile"]),
            metadata_warnings=[str(value) for value in payload.get("metadata_warnings", [])],
        )

    def action_segments(self, action_name: str) -> List[ActionAnnotation]:
        normalized = action_name.lower()
        return [action for action in self.actions if action.action_name == normalized]


@dataclass
class WanderingEvaluationSegment:
    segment_id: str
    sample_id: str
    take_id: str
    camera_id: str
    place_id: str
    season: str
    label: str
    segment_role: str
    video_path: str
    xml_path: str
    start_ms: int
    end_ms: int
    event_start_ms: int
    event_end_ms: int
    action_segments_ms: List[List[int]]
    roi_profile_id: str
    wandering_threshold_profile: str
    metadata_warnings: List[str]

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, object]) -> "WanderingEvaluationSegment":
        return cls(
            segment_id=str(payload["segment_id"]),
            sample_id=str(payload["sample_id"]),
            take_id=str(payload["take_id"]),
            camera_id=str(payload["camera_id"]),
            place_id=str(payload["place_id"]),
            season=str(payload["season"]),
            label=str(payload["label"]),
            segment_role=str(payload["segment_role"]),
            video_path=str(payload["video_path"]),
            xml_path=str(payload["xml_path"]),
            start_ms=int(payload["start_ms"]),
            end_ms=int(payload["end_ms"]),
            event_start_ms=int(payload["event_start_ms"]),
            event_end_ms=int(payload["event_end_ms"]),
            action_segments_ms=[
                [int(segment_start), int(segment_end)]
                for segment_start, segment_end in payload["action_segments_ms"]  # type: ignore[misc]
            ],
            roi_profile_id=str(payload["roi_profile_id"]),
            wandering_threshold_profile=str(payload["wandering_threshold_profile"]),
            metadata_warnings=[str(value) for value in payload.get("metadata_warnings", [])],
        )


def parse_wander_dataset(
    dataset_root: Path,
    project_root: Optional[Path] = None,
) -> List[WanderVideoRecord]:
    dataset_root = dataset_root.resolve()
    if project_root is None:
        project_root = dataset_root.parent.resolve()
    else:
        project_root = project_root.resolve()

    records: List[WanderVideoRecord] = []
    for xml_path in sorted(dataset_root.rglob("*.xml")):
        records.append(parse_wander_annotation(xml_path, project_root=project_root))
    return records


def parse_wander_annotation(
    xml_path: Path,
    project_root: Optional[Path] = None,
) -> WanderVideoRecord:
    xml_path = xml_path.resolve()
    if project_root is None:
        project_root = xml_path.parents[2]
    else:
        project_root = project_root.resolve()

    match = _FILENAME_RE.match(xml_path.stem)
    if match is None:
        raise ValueError(f"Unexpected wander filename format: {xml_path.name}")

    tree = ET.parse(xml_path)
    annotation = tree.getroot()
    header = annotation.find("header")
    event = annotation.find("event")
    obj = annotation.find("object")
    position = obj.find("position") if obj is not None else None
    if header is None or event is None or obj is None:
        raise ValueError(f"Missing required annotation blocks in {xml_path}")

    fps_xml = float(header.findtext("fps", "0") or 0.0)
    actions = _parse_actions(obj, fps_xml)
    event_start_ms = _parse_timecode_to_ms(event.findtext("starttime", "00:00:00.0"))
    event_duration_ms = _parse_timecode_to_ms(event.findtext("duration", "00:00:00.0"))
    event_end_ms = min(
        _parse_timecode_to_ms(header.findtext("duration", "00:00:00.0")),
        event_start_ms + event_duration_ms,
    )

    video_path = xml_path.with_suffix(".mp4")
    if not video_path.exists():
        raise FileNotFoundError(f"Matching video file not found for {xml_path}")

    keypoint = None
    if position is not None:
        keypoint_element = position.find("keypoint")
        if keypoint_element is not None:
            x_value = keypoint_element.findtext("x")
            y_value = keypoint_element.findtext("y")
            if x_value is not None and y_value is not None:
                keypoint = [int(float(x_value)), int(float(y_value))]

    metadata_warnings: List[str] = []
    folder_take_id = xml_path.parent.name
    if folder_take_id != match.group("take_id"):
        metadata_warnings.append(
            f"folder_take_mismatch:{folder_take_id}!={match.group('take_id')}"
        )

    time_of_day_filename = match.group("time_of_day").lower()
    time_of_day_xml = str(header.findtext("time", time_of_day_filename)).lower()
    if time_of_day_xml != time_of_day_filename:
        metadata_warnings.append(
            f"time_of_day_mismatch:{time_of_day_filename}!={time_of_day_xml}"
        )

    place_id = match.group("place_id").lower()
    place_xml = str(header.findtext("location", place_id)).lower()
    if place_xml != place_id:
        metadata_warnings.append(f"place_mismatch:{place_id}!={place_xml}")

    roi_profile_id = f"{place_id}_{match.group('camera_id').lower()}"

    return WanderVideoRecord(
        sample_id=xml_path.stem,
        take_id=match.group("take_id"),
        camera_id=match.group("camera_id"),
        event_id=match.group("event_id"),
        place_id=place_id,
        season=match.group("season").lower(),
        time_of_day_filename=time_of_day_filename,
        time_of_day_xml=time_of_day_xml,
        weather=str(header.findtext("weather", "")).lower(),
        inout=str(header.findtext("inout", "")).lower(),
        population=int(header.findtext("population", "1") or 1),
        character=str(header.findtext("character", "")),
        width=int(annotation.findtext("size/width", "0") or 0),
        height=int(annotation.findtext("size/height", "0") or 0),
        fps_xml=fps_xml,
        frame_count_xml=int(header.findtext("frames", "0") or 0),
        duration_ms_xml=_parse_timecode_to_ms(header.findtext("duration", "00:00:00.0")),
        event_name=str(event.findtext("eventname", "")).lower(),
        event_start_ms=event_start_ms,
        event_end_ms=event_end_ms,
        keyframe=(
            int(position.findtext("keyframe"))
            if position is not None and position.findtext("keyframe")
            else None
        ),
        keypoint_xy=keypoint,
        video_path=_project_relative(video_path, project_root),
        xml_path=_project_relative(xml_path, project_root),
        actions=actions,
        roi_profile_id=roi_profile_id,
        wandering_threshold_profile=roi_profile_id,
        metadata_warnings=metadata_warnings,
    )


def _parse_actions(object_element: ET.Element, fps_xml: float) -> List[ActionAnnotation]:
    actions: List[ActionAnnotation] = []
    for action_element in object_element.findall("action"):
        frame_ranges: List[List[int]] = []
        for frame_element in action_element.findall("frame"):
            start_frame = int(frame_element.findtext("start", "0") or 0)
            end_frame = int(frame_element.findtext("end", "0") or 0)
            frame_ranges.append([start_frame, end_frame])

        if not frame_ranges:
            continue

        start_frame = frame_ranges[0][0]
        end_frame = frame_ranges[-1][1]
        actions.append(
            ActionAnnotation(
                action_name=str(action_element.findtext("actionname", "")).lower(),
                frame_ranges=frame_ranges,
                start_frame=start_frame,
                end_frame=end_frame,
                start_ms=int(round((start_frame / max(fps_xml, 1.0)) * 1000.0)),
                end_ms=int(round((end_frame / max(fps_xml, 1.0)) * 1000.0)),
            )
        )
    return actions


def build_wandering_evaluation_segments(
    records: Iterable[WanderVideoRecord],
    *,
    positive_pre_ms: int = 15000,
    positive_post_ms: int = 10000,
    normal_duration_ms: int = 45000,
    normal_guard_ms: int = 5000,
    min_normal_duration_ms: int = 15000,
) -> List[WanderingEvaluationSegment]:
    segments: List[WanderingEvaluationSegment] = []
    for record in records:
        action_segments_ms = [
            [action.start_ms, action.end_ms]
            for action in record.action_segments("stop and go")
        ]
        positive_start_ms = max(0, record.event_start_ms - positive_pre_ms)
        positive_end_ms = min(record.duration_ms_xml, record.event_end_ms + positive_post_ms)
        segments.append(
            WanderingEvaluationSegment(
                segment_id=f"{record.sample_id}_wandering_event_full",
                sample_id=record.sample_id,
                take_id=record.take_id,
                camera_id=record.camera_id,
                place_id=record.place_id,
                season=record.season,
                label="wandering",
                segment_role="wandering_event_full",
                video_path=record.video_path,
                xml_path=record.xml_path,
                start_ms=positive_start_ms,
                end_ms=positive_end_ms,
                event_start_ms=record.event_start_ms,
                event_end_ms=record.event_end_ms,
                action_segments_ms=action_segments_ms,
                roi_profile_id=record.roi_profile_id,
                wandering_threshold_profile=record.wandering_threshold_profile,
                metadata_warnings=list(record.metadata_warnings),
            )
        )

        normal_pre_end_ms = max(0, record.event_start_ms - normal_guard_ms)
        normal_pre_start_ms = max(0, normal_pre_end_ms - normal_duration_ms)
        if (normal_pre_end_ms - normal_pre_start_ms) >= min_normal_duration_ms:
            segments.append(
                WanderingEvaluationSegment(
                    segment_id=f"{record.sample_id}_normal_pre_event",
                    sample_id=record.sample_id,
                    take_id=record.take_id,
                    camera_id=record.camera_id,
                    place_id=record.place_id,
                    season=record.season,
                    label="normal",
                    segment_role="normal_pre_event",
                    video_path=record.video_path,
                    xml_path=record.xml_path,
                    start_ms=normal_pre_start_ms,
                    end_ms=normal_pre_end_ms,
                    event_start_ms=record.event_start_ms,
                    event_end_ms=record.event_end_ms,
                    action_segments_ms=action_segments_ms,
                    roi_profile_id=record.roi_profile_id,
                    wandering_threshold_profile=record.wandering_threshold_profile,
                    metadata_warnings=list(record.metadata_warnings),
                )
            )

        normal_post_start_ms = min(record.duration_ms_xml, record.event_end_ms + normal_guard_ms)
        normal_post_end_ms = min(record.duration_ms_xml, normal_post_start_ms + normal_duration_ms)
        if (normal_post_end_ms - normal_post_start_ms) >= min_normal_duration_ms:
            segments.append(
                WanderingEvaluationSegment(
                    segment_id=f"{record.sample_id}_normal_post_event",
                    sample_id=record.sample_id,
                    take_id=record.take_id,
                    camera_id=record.camera_id,
                    place_id=record.place_id,
                    season=record.season,
                    label="normal",
                    segment_role="normal_post_event",
                    video_path=record.video_path,
                    xml_path=record.xml_path,
                    start_ms=normal_post_start_ms,
                    end_ms=normal_post_end_ms,
                    event_start_ms=record.event_start_ms,
                    event_end_ms=record.event_end_ms,
                    action_segments_ms=action_segments_ms,
                    roi_profile_id=record.roi_profile_id,
                    wandering_threshold_profile=record.wandering_threshold_profile,
                    metadata_warnings=list(record.metadata_warnings),
                )
            )
    return segments


def write_jsonl(items: Iterable[Dict[str, object]], output_path: Path) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output_path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=True) + "\n")
            count += 1
    return count


def load_video_manifest(path: Path) -> List[WanderVideoRecord]:
    records: List[WanderVideoRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(WanderVideoRecord.from_dict(json.loads(line)))
    return records


def load_segment_manifest(path: Path) -> List[WanderingEvaluationSegment]:
    records: List[WanderingEvaluationSegment] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(WanderingEvaluationSegment.from_dict(json.loads(line)))
    return records
