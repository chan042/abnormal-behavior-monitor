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
    r"(?P<event_id>swoon\d+)_"
    r"(?P<location>place\d+)_"
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
class SwoonVideoRecord:
    sample_id: str
    take_id: str
    camera_id: str
    event_id: str
    location: str
    time_of_day: str
    season: str
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

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["actions"] = [action.to_dict() for action in self.actions]
        return payload

    @classmethod
    def from_dict(cls, payload: Dict[str, object]) -> "SwoonVideoRecord":
        return cls(
            sample_id=str(payload["sample_id"]),
            take_id=str(payload["take_id"]),
            camera_id=str(payload["camera_id"]),
            event_id=str(payload["event_id"]),
            location=str(payload["location"]),
            time_of_day=str(payload["time_of_day"]),
            season=str(payload["season"]),
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
        )

    def action_segments(self, action_name: str) -> List[ActionAnnotation]:
        return [action for action in self.actions if action.action_name == action_name]


@dataclass
class EvaluationSegment:
    segment_id: str
    sample_id: str
    take_id: str
    camera_id: str
    season: str
    label: str
    segment_role: str
    video_path: str
    xml_path: str
    start_ms: int
    end_ms: int
    event_start_ms: int
    event_end_ms: int
    falldown_start_ms: int
    falldown_end_ms: int
    falldown_segments_ms: List[List[int]]
    totter_segments_ms: List[List[int]]
    fall_threshold_profile: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, object]) -> "EvaluationSegment":
        return cls(
            segment_id=str(payload["segment_id"]),
            sample_id=str(payload["sample_id"]),
            take_id=str(payload["take_id"]),
            camera_id=str(payload["camera_id"]),
            season=str(payload["season"]),
            label=str(payload["label"]),
            segment_role=str(payload["segment_role"]),
            video_path=str(payload["video_path"]),
            xml_path=str(payload["xml_path"]),
            start_ms=int(payload["start_ms"]),
            end_ms=int(payload["end_ms"]),
            event_start_ms=int(payload["event_start_ms"]),
            event_end_ms=int(payload["event_end_ms"]),
            falldown_start_ms=int(payload["falldown_start_ms"]),
            falldown_end_ms=int(payload["falldown_end_ms"]),
            falldown_segments_ms=[
                [int(segment_start), int(segment_end)]
                for segment_start, segment_end in payload["falldown_segments_ms"]  # type: ignore[misc]
            ],
            totter_segments_ms=[
                [int(segment_start), int(segment_end)]
                for segment_start, segment_end in payload["totter_segments_ms"]  # type: ignore[misc]
            ],
            fall_threshold_profile=(
                str(payload["fall_threshold_profile"])
                if payload.get("fall_threshold_profile") is not None
                else f"{payload['camera_id']}_{payload['season']}"
            ),
        )


def parse_swoon_dataset(
    dataset_root: Path,
    project_root: Optional[Path] = None,
) -> List[SwoonVideoRecord]:
    dataset_root = dataset_root.resolve()
    if project_root is None:
        project_root = dataset_root.parent.resolve()
    else:
        project_root = project_root.resolve()

    records = []
    for xml_path in sorted(dataset_root.rglob("*.xml")):
        records.append(parse_swoon_annotation(xml_path, project_root=project_root))
    return records


def parse_swoon_annotation(xml_path: Path, project_root: Optional[Path] = None) -> SwoonVideoRecord:
    xml_path = xml_path.resolve()
    if project_root is None:
        project_root = xml_path.parents[2]
    else:
        project_root = project_root.resolve()

    tree = ET.parse(xml_path)
    annotation = tree.getroot()
    stem = xml_path.stem
    match = _FILENAME_RE.match(stem)
    if match is None:
        raise ValueError(f"Unexpected swoon filename format: {xml_path.name}")

    header = annotation.find("header")
    event = annotation.find("event")
    obj = annotation.find("object")
    position = obj.find("position") if obj is not None else None
    if header is None or event is None or obj is None:
        raise ValueError(f"Missing required annotation blocks in {xml_path}")

    fps_xml = float(header.findtext("fps", "0") or 0.0)
    actions = _parse_actions(obj, fps_xml)
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

    event_start_ms = _parse_timecode_to_ms(event.findtext("starttime", "00:00:00.0"))
    event_duration_ms = _parse_timecode_to_ms(event.findtext("duration", "00:00:00.0"))

    return SwoonVideoRecord(
        sample_id=stem,
        take_id=match.group("take_id"),
        camera_id=match.group("camera_id"),
        event_id=match.group("event_id"),
        location=str(header.findtext("location", match.group("location"))).lower(),
        time_of_day=str(header.findtext("time", match.group("time_of_day"))).lower(),
        season=str(header.findtext("season", match.group("season"))).lower(),
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
        event_end_ms=event_start_ms + event_duration_ms,
        keyframe=(
            int(position.findtext("keyframe"))
            if position is not None and position.findtext("keyframe")
            else None
        ),
        keypoint_xy=keypoint,
        video_path=_project_relative(video_path, project_root),
        xml_path=_project_relative(xml_path, project_root),
        actions=actions,
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


def build_fall_evaluation_segments(
    records: Iterable[SwoonVideoRecord],
    *,
    positive_pre_ms: int = 5000,
    positive_post_ms: int = 8000,
    normal_duration_ms: int = 20000,
    normal_guard_ms: int = 10000,
    min_normal_duration_ms: int = 5000,
) -> List[EvaluationSegment]:
    segments: List[EvaluationSegment] = []
    for record in records:
        falldown_actions = record.action_segments("falldown")
        if not falldown_actions:
            continue

        falldown_start_ms = min(action.start_ms for action in falldown_actions)
        falldown_end_ms = max(action.end_ms for action in falldown_actions)
        falldown_segments_ms = [
            [action.start_ms, action.end_ms] for action in falldown_actions
        ]
        totter_segments_ms = [
            [action.start_ms, action.end_ms]
            for action in record.action_segments("totter")
        ]

        positive_start_ms = max(0, falldown_start_ms - positive_pre_ms)
        positive_end_ms = min(record.duration_ms_xml, falldown_end_ms + positive_post_ms)
        segments.append(
            EvaluationSegment(
                segment_id=f"{record.sample_id}_fall_positive",
                sample_id=record.sample_id,
                take_id=record.take_id,
                camera_id=record.camera_id,
                season=record.season,
                label="fall",
                segment_role="fall_positive",
                video_path=record.video_path,
                xml_path=record.xml_path,
                start_ms=positive_start_ms,
                end_ms=positive_end_ms,
                event_start_ms=record.event_start_ms,
                event_end_ms=record.event_end_ms,
                falldown_start_ms=falldown_start_ms,
                falldown_end_ms=falldown_end_ms,
                falldown_segments_ms=falldown_segments_ms,
                totter_segments_ms=totter_segments_ms,
                fall_threshold_profile=f"{record.camera_id}_{record.season}",
            )
        )

        normal_end_ms = max(0, record.event_start_ms - normal_guard_ms)
        normal_start_ms = max(0, normal_end_ms - normal_duration_ms)
        if (normal_end_ms - normal_start_ms) >= min_normal_duration_ms:
            segments.append(
                EvaluationSegment(
                    segment_id=f"{record.sample_id}_normal_pre_event",
                    sample_id=record.sample_id,
                    take_id=record.take_id,
                    camera_id=record.camera_id,
                    season=record.season,
                    label="normal",
                    segment_role="normal_pre_event",
                    video_path=record.video_path,
                    xml_path=record.xml_path,
                    start_ms=normal_start_ms,
                    end_ms=normal_end_ms,
                    event_start_ms=record.event_start_ms,
                    event_end_ms=record.event_end_ms,
                    falldown_start_ms=falldown_start_ms,
                    falldown_end_ms=falldown_end_ms,
                    falldown_segments_ms=falldown_segments_ms,
                    totter_segments_ms=totter_segments_ms,
                    fall_threshold_profile=f"{record.camera_id}_{record.season}",
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


def load_video_manifest(path: Path) -> List[SwoonVideoRecord]:
    records: List[SwoonVideoRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(SwoonVideoRecord.from_dict(json.loads(line)))
    return records


def load_segment_manifest(path: Path) -> List[EvaluationSegment]:
    records: List[EvaluationSegment] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(EvaluationSegment.from_dict(json.loads(line)))
    return records
