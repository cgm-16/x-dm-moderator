from pathlib import Path
import json
import os

import pytest


def write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def install_fake_ffmpeg_tools(bin_dir: Path) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)

    ffprobe_path = bin_dir / "ffprobe"
    ffmpeg_path = bin_dir / "ffmpeg"

    write_executable(
        ffprobe_path,
        """#!/usr/bin/env python3
import os
import sys

if os.environ.get("FAKE_FFPROBE_FAIL") == "1":
    sys.stderr.write("ffprobe failed\\n")
    raise SystemExit(1)

sys.stdout.write(os.environ.get("FAKE_FFPROBE_DURATION", "0"))
""",
    )

    write_executable(
        ffmpeg_path,
        """#!/usr/bin/env python3
from pathlib import Path
import json
import os
import sys

log_path = os.environ.get("FAKE_FFMPEG_LOG")
if log_path:
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(sys.argv[1:]) + "\\n")

if os.environ.get("FAKE_FFMPEG_FAIL") == "1":
    sys.stderr.write("ffmpeg failed\\n")
    raise SystemExit(1)

output_path = Path(sys.argv[-1])
output_path.parent.mkdir(parents=True, exist_ok=True)
output_path.write_bytes(b"jpeg-bytes")
""",
    )

    return bin_dir


def read_ffmpeg_log(log_path: Path) -> list[list[str]]:
    return [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def test_extract_frames_returns_one_frame_per_second_for_ten_second_video(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from dmguard import frame_extractor

    bin_dir = install_fake_ffmpeg_tools(tmp_path / "bin")
    log_path = tmp_path / "ffmpeg-log.jsonl"
    output_dir = tmp_path / "frames"
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"video")

    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_FFPROBE_DURATION", "10.0")
    monkeypatch.setenv("FAKE_FFMPEG_LOG", str(log_path))
    monkeypatch.setattr(frame_extractor, "TMP_DIR", output_dir)

    frames = frame_extractor.extract_frames(video_path, "event-1")

    assert [frame.index for frame in frames] == list(range(10))
    assert [frame.time_sec for frame in frames] == [
        1.0,
        2.0,
        3.0,
        4.0,
        5.0,
        6.0,
        7.0,
        8.0,
        9.0,
        10.0,
    ]
    assert [frame.path for frame in frames] == [
        output_dir / "event-1_frame_0.jpg",
        output_dir / "event-1_frame_1.jpg",
        output_dir / "event-1_frame_2.jpg",
        output_dir / "event-1_frame_3.jpg",
        output_dir / "event-1_frame_4.jpg",
        output_dir / "event-1_frame_5.jpg",
        output_dir / "event-1_frame_6.jpg",
        output_dir / "event-1_frame_7.jpg",
        output_dir / "event-1_frame_8.jpg",
        output_dir / "event-1_frame_9.jpg",
    ]
    assert all(frame.path.read_bytes() == b"jpeg-bytes" for frame in frames)

    ffmpeg_calls = read_ffmpeg_log(log_path)
    assert [call[call.index("-ss") + 1] for call in ffmpeg_calls] == [
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
        "10",
    ]


def test_extract_frames_clamps_to_video_duration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from dmguard import frame_extractor

    bin_dir = install_fake_ffmpeg_tools(tmp_path / "bin")
    output_dir = tmp_path / "frames"
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"video")

    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_FFPROBE_DURATION", "5.0")
    monkeypatch.setattr(frame_extractor, "TMP_DIR", output_dir)

    frames = frame_extractor.extract_frames(video_path, "event-2")

    assert [frame.index for frame in frames] == [0, 1, 2, 3, 4]
    assert [frame.time_sec for frame in frames] == [1.0, 2.0, 3.0, 4.0, 5.0]


def test_extract_frames_clamps_to_twelve_seconds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from dmguard import frame_extractor

    bin_dir = install_fake_ffmpeg_tools(tmp_path / "bin")
    output_dir = tmp_path / "frames"
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"video")

    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_FFPROBE_DURATION", "30.0")
    monkeypatch.setattr(frame_extractor, "TMP_DIR", output_dir)

    frames = frame_extractor.extract_frames(video_path, "event-3")

    assert len(frames) == 12
    assert frames[0].time_sec == 1.0
    assert frames[-1].time_sec == 12.0


def test_extract_frames_returns_empty_list_for_subsecond_video(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from dmguard import frame_extractor

    bin_dir = install_fake_ffmpeg_tools(tmp_path / "bin")
    output_dir = tmp_path / "frames"
    log_path = tmp_path / "ffmpeg-log.jsonl"
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"video")

    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_FFPROBE_DURATION", "0.9")
    monkeypatch.setenv("FAKE_FFMPEG_LOG", str(log_path))
    monkeypatch.setattr(frame_extractor, "TMP_DIR", output_dir)

    frames = frame_extractor.extract_frames(video_path, "event-4")

    assert frames == []
    assert not log_path.exists()


def test_extract_frames_outputs_can_be_removed_with_cleanup_media(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from dmguard import frame_extractor
    from dmguard.media_download import cleanup_media

    bin_dir = install_fake_ffmpeg_tools(tmp_path / "bin")
    output_dir = tmp_path / "frames"
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"video")

    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_FFPROBE_DURATION", "2.0")
    monkeypatch.setattr(frame_extractor, "TMP_DIR", output_dir)

    frames = frame_extractor.extract_frames(video_path, "event-5")

    cleanup_media([frame.path for frame in frames])

    assert all(not frame.path.exists() for frame in frames)


def test_extract_frames_raises_when_ffprobe_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from dmguard import frame_extractor

    bin_dir = install_fake_ffmpeg_tools(tmp_path / "bin")
    output_dir = tmp_path / "frames"
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"video")

    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_FFPROBE_FAIL", "1")
    monkeypatch.setattr(frame_extractor, "TMP_DIR", output_dir)

    with pytest.raises(frame_extractor.FrameExtractionError, match="ffprobe failed"):
        frame_extractor.extract_frames(video_path, "event-6")


def test_extract_frames_raises_when_ffmpeg_fails_and_cleans_partial_frames(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from dmguard import frame_extractor

    bin_dir = install_fake_ffmpeg_tools(tmp_path / "bin")
    output_dir = tmp_path / "frames"
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"video")

    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_FFPROBE_DURATION", "2.0")
    monkeypatch.setenv("FAKE_FFMPEG_FAIL", "1")
    monkeypatch.setattr(frame_extractor, "TMP_DIR", output_dir)

    with pytest.raises(frame_extractor.FrameExtractionError, match="ffmpeg failed"):
        frame_extractor.extract_frames(video_path, "event-7")

    assert list(output_dir.glob("*.jpg")) == []
