"""Async FFmpeg helpers producing browser- and Premiere-friendly output.

Everything is encoded as H.264 yuv420p with +faststart (moov atom up front so
browsers can start playback while downloading) and even pixel dimensions
(libx264 rejects odd sizes; avatar images can have any dimensions).
"""

import asyncio
import logging
import math
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

_EVEN_DIMS_FILTER = "scale=trunc(iw/2)*2:trunc(ih/2)*2"

# Shared by every segment encode in the full-video assembler: identical codec
# parameters at identical size/fps make the final concat a lossless `-c copy`.
_H264_ARGS = [
    "-c:v", "libx264",
    "-preset", "medium",
    "-crf", "18",
    "-pix_fmt", "yuv420p",
    "-movflags", "+faststart",
]


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


async def _run_ffprobe(*args: str) -> str:
    if shutil.which("ffprobe") is None:
        raise FFmpegError("ffprobe is not installed or not on PATH")
    command = ["ffprobe", "-hide_banner", "-loglevel", "error", *args]
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        tail = stderr.decode(errors="replace").strip()[-2000:]
        raise FFmpegError(f"ffprobe failed (exit {process.returncode}): {tail}")
    return stdout.decode(errors="replace")


async def probe_duration(src: Path) -> float:
    """Container duration in seconds."""
    out = await _run_ffprobe(
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(src),
    )
    try:
        return float(out.strip())
    except ValueError as exc:
        raise FFmpegError(f"could not read duration of {src.name}: {out.strip()!r}") from exc


async def still_to_clip(
    src: Path,
    dst: Path,
    *,
    duration_s: float,
    width: int,
    height: int,
    fps: int = 24,
    zoom: float = 1.12,
) -> Path:
    """Turn a still image into a Ken Burns clip (slow center zoom-in) of
    exactly `duration_s` at the given canvas size. The image is cover-cropped
    to 2x the canvas before zoompan — sub-pixel sampling headroom that avoids
    the filter's notorious stair-step jitter."""
    frames = max(1, round(duration_s * fps))
    filters = (
        f"scale={2 * width}:{2 * height}:force_original_aspect_ratio=increase,"
        f"crop={2 * width}:{2 * height},"
        f"zoompan=z='1+({zoom}-1)*on/{frames}'"
        f":x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2'"
        f":d={frames}:s={width}x{height}:fps={fps},"
        "setsar=1"
    )
    await _run(
        "-i", str(src),
        "-vf", filters,
        "-frames:v", str(frames),
        "-an",
        *_H264_ARGS,
        str(dst),
    )
    return dst


async def pingpong(src: Path, dst: Path) -> Path:
    """Forward+reversed copy of a clip (seamless loop point for AI b-roll).
    `reverse` buffers the whole clip in RAM — only use on short raw clips."""
    await _run(
        "-i", str(src),
        "-filter_complex",
        f"[0:v]{_EVEN_DIMS_FILTER},split[a][b];[b]reverse[r];[a][r]concat=n=2:v=1:a=0[v]",
        "-map", "[v]",
        "-an",
        *_H264_ARGS,
        str(dst),
    )
    return dst


async def loop_to_duration(src: Path, dst: Path, *, duration_s: float) -> Path:
    """Repeat a clip as often as needed, then cut at exactly `duration_s`."""
    src_duration = await probe_duration(src)
    if src_duration <= 0:
        raise FFmpegError(f"{src.name} has no measurable duration")
    loops = max(0, math.ceil(duration_s / src_duration) - 1)
    await _run(
        "-stream_loop", str(loops),
        "-i", str(src),
        "-vf", _EVEN_DIMS_FILTER,
        "-t", f"{duration_s:.6f}",
        "-an",
        *_H264_ARGS,
        str(dst),
    )
    return dst


async def normalize_segment(
    src: Path,
    dst: Path,
    *,
    width: int,
    height: int,
    fps: int,
    duration_s: float,
) -> Path:
    """Conform any video to the assembler canvas: cover-crop to width x height,
    resample to `fps` (the fps *filter* preserves wall-clock duration — input
    `-r` would retime and desync lips), strip audio, and land on exactly
    `duration_s` (tpad clones the last frame if the source runs short)."""
    filters = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        f"fps={fps},"
        "setsar=1,"
        "tpad=stop_mode=clone:stop_duration=2"
    )
    await _run(
        "-i", str(src),
        "-vf", filters,
        "-t", f"{duration_s:.6f}",
        "-an",
        *_H264_ARGS,
        str(dst),
    )
    return dst


async def pad_audio_to_duration(src: Path, dst: Path, *, duration_s: float) -> Path:
    """Silence-pad audio out to exactly `duration_s` (PCM16 44.1 kHz mono WAV)."""
    await _run(
        "-i", str(src),
        "-af", "apad",
        "-t", f"{duration_s:.6f}",
        "-c:a", "pcm_s16le",
        "-ar", "44100",
        "-ac", "1",
        str(dst),
    )
    return dst


def _concat_list_line(path: Path) -> str:
    quoted = path.resolve().as_posix().replace("'", "'\\''")
    return f"file '{quoted}'"


async def _concat_copy(sources: list[Path], dst: Path) -> Path:
    """Concat demuxer with stream copy. All inputs must share identical codec
    parameters — guaranteed for our segments by _H264_ARGS at one size/fps,
    and for audio by S2/apad's fixed PCM16 44.1 kHz mono format."""
    if not sources:
        raise ValueError("nothing to concatenate")
    list_path = dst.with_name(f"{dst.stem}_list.txt")
    list_path.write_text(
        "\n".join(_concat_list_line(p) for p in sources) + "\n", encoding="utf-8"
    )
    try:
        await _run(
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_path),
            "-c", "copy",
            str(dst),
        )
    finally:
        list_path.unlink(missing_ok=True)
    return dst


async def concat_clips(sources: list[Path], dst: Path) -> Path:
    return await _concat_copy(sources, dst)


async def concat_audio(sources: list[Path], dst: Path) -> Path:
    return await _concat_copy(sources, dst)
