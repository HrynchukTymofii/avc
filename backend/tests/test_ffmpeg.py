"""FFmpeg helpers, exercised with synthetic lavfi inputs. Skipped when ffmpeg
is not installed locally; always runs in the Docker image."""

import asyncio
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

from app.services.ffmpeg import FFmpegError, encode_h264, mux_av

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
