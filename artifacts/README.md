# Artifacts Layout

- `events/`: serialized event records
- `clips/`: saved video clips around detected events, grouped by `camera_id`
- `snapshots/`: representative still frames, grouped by `camera_id`
- `logs/`: runtime logs and diagnostic output
- `overlays/`: rendered review videos with bbox, `track_id`, pose landmarks, and event labels

These files are runtime outputs, not source assets.
