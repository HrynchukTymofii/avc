"""FFmpeg helpers, exercised with synthetic lavfi inputs. Skipped when ffmpeg
is not installed locally; always runs in the Docker image."""

import asyncio
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

from app.services.ffmpeg import (
    FFmpegError,
    concat_audio,
    concat_clips,
    encode_h264,
    loop_to_duration,
    mux_av,
    normalize_segment,
    pad_audio_to_duration,
    pingpong,
    probe_duration,
    still_to_clip,
)

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg not installed"
)


def make_test_video(path: Path, seconds: float = 1.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size=322x241:rate=25",
            "-c:v", "mpeg4", str(path),
        ],
        check=True,
    )


def make_test_wav(path: Path, seconds: float = 1.0, rate: int = 44100) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\x01\x00" * int(seconds * rate))


def probe_streams(path: Path) -> str:
    return subprocess.run(
        ["ffprobe", "-hide_banner", "-loglevel", "error", "-show_streams", str(path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_encode_h264_produces_yuv420p_even_dims(tmp_path: Path) -> None:
    src, dst = tmp_path / "src.mp4", tmp_path / "out.mp4"
    make_test_video(src)  # deliberately odd 322x241 input
    asyncio.run(encode_h264(src, dst))

    info = probe_streams(dst)
    assert "codec_name=h264" in info
    assert "pix_fmt=yuv420p" in info
    assert "width=322" in info and "height=240" in info  # odd dim rounded to even


def test_mux_av_combines_video_and_audio(tmp_path: Path) -> None:
    video, audio, dst = tmp_path / "v.mp4", tmp_path / "a.wav", tmp_path / "out.mp4"
    make_test_video(video)
    make_test_wav(audio)
    asyncio.run(mux_av(video, audio, dst))

    info = probe_streams(dst)
    assert "codec_name=h264" in info
    assert "codec_name=aac" in info


def test_invalid_input_raises_ffmpeg_error(tmp_path: Path) -> None:
    src = tmp_path / "not_video.mp4"
    src.write_bytes(b"garbage")
    with pytest.raises(FFmpegError, match="ffmpeg failed"):
        asyncio.run(encode_h264(src, tmp_path / "out.mp4"))


# ---- full-video assembly helpers ------------------------------------------------


def make_test_png(path: Path, size: str = "640x480") -> None:
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc=duration=0.04:size={size}:rate=25",
            "-frames:v", "1", str(path),
        ],
        check=True,
    )


def probe_value(path: Path, key: str) -> str:
    for line in probe_streams(path).splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    raise AssertionError(f"{key} not found in ffprobe output for {path}")


def test_probe_duration(tmp_path: Path) -> None:
    src = tmp_path / "src.mp4"
    make_test_video(src, seconds=2.0)
    assert asyncio.run(probe_duration(src)) == pytest.approx(2.0, abs=0.1)


def test_probe_duration_rejects_garbage(tmp_path: Path) -> None:
    src = tmp_path / "bad.mp4"
    src.write_bytes(b"garbage")
    with pytest.raises(FFmpegError):
        asyncio.run(probe_duration(src))


def test_still_to_clip_duration_size_and_fps(tmp_path: Path) -> None:
    still, dst = tmp_path / "still.png", tmp_path / "kb.mp4"
    make_test_png(still)
    asyncio.run(still_to_clip(still, dst, duration_s=1.5, width=320, height=176))

    assert probe_value(dst, "width") == "320"
    assert probe_value(dst, "height") == "176"
    assert probe_value(dst, "r_frame_rate") == "24/1"
    assert asyncio.run(probe_duration(dst)) == pytest.approx(1.5, abs=0.1)


def test_pingpong_doubles_duration(tmp_path: Path) -> None:
    src, dst = tmp_path / "src.mp4", tmp_path / "pp.mp4"
    make_test_video(src, seconds=1.0)
    asyncio.run(pingpong(src, dst))
    assert asyncio.run(probe_duration(dst)) == pytest.approx(2.0, abs=0.2)


def test_loop_to_duration_extends_short_clip(tmp_path: Path) -> None:
    src, dst = tmp_path / "src.mp4", tmp_path / "looped.mp4"
    make_test_video(src, seconds=1.0)
    asyncio.run(loop_to_duration(src, dst, duration_s=3.25))
    assert asyncio.run(probe_duration(dst)) == pytest.approx(3.25, abs=0.1)


def test_loop_to_duration_trims_long_clip(tmp_path: Path) -> None:
    src, dst = tmp_path / "src.mp4", tmp_path / "trimmed.mp4"
    make_test_video(src, seconds=2.0)
    asyncio.run(loop_to_duration(src, dst, duration_s=1.0))
    assert asyncio.run(probe_duration(dst)) == pytest.approx(1.0, abs=0.1)


def test_normalize_segment_conforms_odd_25fps_input(tmp_path: Path) -> None:
    """The MuseTalk case: odd-sized 25 fps input → canvas size, 24 fps, exact
    duration (tpad extends the slightly-short source)."""
    src, dst = tmp_path / "src.mp4", tmp_path / "seg.mp4"
    make_test_video(src, seconds=1.0)  # 322x241 @ 25fps
    asyncio.run(normalize_segment(src, dst, width=320, height=176, fps=24, duration_s=1.5))

    assert probe_value(dst, "width") == "320"
    assert probe_value(dst, "height") == "176"
    assert probe_value(dst, "r_frame_rate") == "24/1"
    assert asyncio.run(probe_duration(dst)) == pytest.approx(1.5, abs=0.1)


def test_pad_audio_to_duration(tmp_path: Path) -> None:
    src, dst = tmp_path / "a.wav", tmp_path / "padded.wav"
    make_test_wav(src, seconds=1.0)
    asyncio.run(pad_audio_to_duration(src, dst, duration_s=2.5))
    assert asyncio.run(probe_duration(dst)) == pytest.approx(2.5, abs=0.05)


def test_concat_clips_stream_copy_of_normalized_segments(tmp_path: Path) -> None:
    """Locks the shared-args invariant: two independently produced segments
    (normalize_segment + still_to_clip) concat losslessly with -c copy."""
    video, still = tmp_path / "v.mp4", tmp_path / "s.png"
    make_test_video(video, seconds=1.0)
    make_test_png(still)
    seg1, seg2, out = tmp_path / "seg1.mp4", tmp_path / "seg2.mp4", tmp_path / "cat.mp4"
    asyncio.run(normalize_segment(video, seg1, width=320, height=176, fps=24, duration_s=1.0))
    asyncio.run(still_to_clip(still, seg2, duration_s=1.5, width=320, height=176))

    asyncio.run(concat_clips([seg1, seg2], out))
    assert asyncio.run(probe_duration(out)) == pytest.approx(2.5, abs=0.1)
    assert probe_value(out, "codec_name") == "h264"
    assert not (tmp_path / "cat_list.txt").exists()  # list file cleaned up


def test_concat_audio(tmp_path: Path) -> None:
    a, b, out = tmp_path / "a.wav", tmp_path / "b.wav", tmp_path / "cat.wav"
    make_test_wav(a, seconds=1.0)
    make_test_wav(b, seconds=0.5)
    asyncio.run(concat_audio([a, b], out))
    assert asyncio.run(probe_duration(out)) == pytest.approx(1.5, abs=0.05)


def test_concat_rejects_empty_list(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="nothing to concatenate"):
        asyncio.run(concat_clips([], tmp_path / "out.mp4"))
