from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def transcode_mp4_for_web(path: Path) -> bool:
    if not path.exists():
        return False

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return False

    temp_path = path.with_name(f"{path.stem}.webtmp{path.suffix}")
    encoders = ("libx264", "h264_videotoolbox")

    for encoder in encoders:
        if _run_ffmpeg(ffmpeg, encoder, path, temp_path):
            temp_path.replace(path)
            return True
        if temp_path.exists():
            temp_path.unlink()

    return False


def _run_ffmpeg(
    ffmpeg: str,
    encoder: str,
    source_path: Path,
    output_path: Path,
) -> bool:
    command = [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(source_path),
        "-an",
        "-c:v",
        encoder,
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and output_path.exists()
