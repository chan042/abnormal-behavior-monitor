from __future__ import annotations

import json
import threading
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterator, Optional, Protocol

from .schema import EventRecord, event_record_from_dict


class SceneDescriptionQueue(Protocol):
    def enqueue_event(self, event: EventRecord, source_path: Path) -> bool:
        ...


EventPayloadMutator = Callable[[Dict[str, object]], Dict[str, object]]

_FILE_LOCK_GUARD = threading.Lock()
_FILE_LOCKS: Dict[str, threading.RLock] = defaultdict(threading.RLock)


def append_event_record(source_path: Path, event: EventRecord) -> EventRecord:
    source_path.parent.mkdir(parents=True, exist_ok=True)
    with locked_event_file(source_path):
        with source_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event.to_dict(), ensure_ascii=True) + "\n")
    return event


def persist_event_record(
    source_path: Path,
    event: EventRecord,
    scene_description_service: Optional[SceneDescriptionQueue] = None,
) -> EventRecord:
    if scene_description_service is not None:
        event.description_status = "pending"
        event.description_source = "rule"
        event.description_generated_at = None
        event.description_error = ""
    if event.updated_at is None:
        event.updated_at = event.started_at
    append_event_record(source_path, event)
    if scene_description_service is not None:
        scene_description_service.enqueue_event(event=event, source_path=source_path)
    return event


def read_event_record(source_path: Path, event_id: str) -> Optional[EventRecord]:
    if not source_path.exists():
        return None

    with locked_event_file(source_path):
        with source_path.open("r", encoding="utf-8") as file:
            for raw_line in file:
                line = raw_line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                if payload.get("event_id") == event_id:
                    return event_record_from_dict(payload)
    return None


def update_event_record(
    source_path: Path,
    event_id: str,
    mutator: EventPayloadMutator,
) -> EventRecord:
    updated_record: Optional[EventRecord] = None
    updated_lines = []

    with locked_event_file(source_path):
        with source_path.open("r", encoding="utf-8") as file:
            for raw_line in file:
                line = raw_line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                if payload.get("event_id") == event_id:
                    payload = mutator(dict(payload))
                    updated_record = event_record_from_dict(payload)
                updated_lines.append(json.dumps(payload, ensure_ascii=True))

        if updated_record is None:
            raise FileNotFoundError(f"Event not found: {event_id}")

        with source_path.open("w", encoding="utf-8") as file:
            for line in updated_lines:
                file.write(line + "\n")

    return updated_record


@contextmanager
def locked_event_file(source_path: Path) -> Iterator[None]:
    lock_key = str(source_path.resolve())
    with _FILE_LOCK_GUARD:
        lock = _FILE_LOCKS[lock_key]
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
