"""Async FFmpeg helpers producing browser- and Premiere-friendly output.

Everything is encoded as H.264 yuv420p with +faststart (moov atom up front so
browsers can start playback while downloading) and even pixel dimensions
(libx264 rejects odd sizes; avatar images can have any dimensions).
"""

import asyncio
import logging
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

_EVEN_DIMS_FILTER = "scale=trunc(iw/2)*2:trunc(ih/2)*2"


class FFmpegError(RuntimeError):
    """FFmpeg missing or exited non-zero; message includes the stderr tail."""


async def _run(*args: str) -> None:
    if shutil.which("ffmpeg") is None:
        raise FFmpegError("ffmpeg is not installed or not on PATH")
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args]
    log.info("running ffmpeg", extra={"command": " ".join(args)})
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        tail = stderr.decode(errors="replace").strip()[-2000:]
        raise FFmpegError(f"ffmpeg failed (exit {process.returncode}): {tail}")


async def encode_h264(src: Path, dst: Path, fps: int | None = None) -> Path:
    """Re-encode any video into H.264/yuv420p/faststart, stripping audio."""
    args = ["-i", str(src)]
    if fps is not None:
        args += ["-r", str(fps)]
    args += [
        "-vf", _EVEN_DIMS_FILTER,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-an",
        str(dst),
    ]
    await _run(*args)
    return dst


async def mux_av(video_src: Path, audio_src: Path, dst: Path) -> Path:
    """Combine a (possibly silent) video and an audio file into the final MP4
    (H.264 + AAC). -shortest guards against sub-frame duration drift between
    the lip-sync video and the speech track."""
    await _run(
        "-i", str(video_src),
        "-i", str(audio_src),
        "-vf", _EVEN_DIMS_FILTER,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        str(dst),
    )
    return dst
