from dataclasses import dataclass
from math import floor
from pathlib import Path
import subprocess

from dmguard.media_download import cleanup_media
from dmguard.paths import TMP_DIR


@dataclass(frozen=True)
class FrameInfo:
    path: Path
    time_sec: float
    index: int


class FrameExtractionError(RuntimeError):
    pass


def extract_frames(video_path: Path, event_id: str) -> list[FrameInfo]:
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    duration_sec = _probe_duration(video_path)
    max_time_sec = min(12, floor(duration_sec))

    if max_time_sec < 1:
        return []

    frames: list[FrameInfo] = []

    try:
        for index, time_sec in enumerate(range(1, max_time_sec + 1)):
            frame_path = TMP_DIR / f"{event_id}_frame_{index}.jpg"
            _extract_frame(video_path, frame_path, time_sec)
            frames.append(
                FrameInfo(
                    path=frame_path,
                    time_sec=float(time_sec),
                    index=index,
                )
            )
    except Exception:
        cleanup_media([frame.path for frame in frames])
        raise

    return frames


def _probe_duration(video_path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise FrameExtractionError(result.stderr.strip() or "ffprobe failed")

    try:
        return float(result.stdout.strip())
    except ValueError as error:
        raise FrameExtractionError("ffprobe returned invalid duration") from error


def _extract_frame(video_path: Path, frame_path: Path, time_sec: int) -> None:
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            str(time_sec),
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            str(frame_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise FrameExtractionError(result.stderr.strip() or "ffmpeg failed")


__all__ = ["FrameExtractionError", "FrameInfo", "extract_frames"]
