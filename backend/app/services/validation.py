"""Input validation for uploads and text fields.

Raises InputValidationError with user-presentable messages; the app-level exception
handler in main.py converts these into HTTP 422 responses.
"""

import io

from fastapi import UploadFile
from PIL import Image

# Canonical extension per accepted image format, keyed by Pillow's format name.
ALLOWED_IMAGE_FORMATS = {"PNG": ".png", "JPEG": ".jpg"}

_READ_CHUNK_BYTES = 1024 * 1024


class InputValidationError(ValueError):
    """Invalid user input; the message is safe to show to the end user."""


def _size_limit_label(max_bytes: int) -> str:
    if max_bytes >= 1024 * 1024:
        return f"{max_bytes / (1024 * 1024):g} MB"
    return f"{max_bytes} bytes"


async def _read_capped(file: UploadFile, *, max_bytes: int, field: str) -> bytes:
    """Stream an upload into memory, rejecting it as soon as it exceeds the cap."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(_READ_CHUNK_BYTES):
        total += len(chunk)
        if total > max_bytes:
            raise InputValidationError(
                f"{field} exceeds the {_size_limit_label(max_bytes)} size limit"
            )
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise InputValidationError(f"{field} file is empty")
    return data


def validate_text(value: str, *, field: str, max_chars: int) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise InputValidationError(f"{field} must not be empty")
    if len(cleaned) > max_chars:
        raise InputValidationError(
            f"{field} is too long ({len(cleaned)} characters, maximum {max_chars})"
        )
    return cleaned


async def read_image_upload(
    file: UploadFile, *, max_bytes: int, field: str
) -> tuple[bytes, str]:
    """Read an uploaded image, enforcing the size limit while streaming (so an
    oversized upload is rejected before it is fully buffered) and verifying by
    content — not filename — that it is a PNG or JPEG.

    Returns the raw bytes and the canonical file extension (".png" / ".jpg").
    """
    data = await _read_capped(file, max_bytes=max_bytes, field=field)

    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
            image_format = image.format
    except InputValidationError:
        raise
    except Exception as exc:
        raise InputValidationError(f"{field} is not a valid image file") from exc

    if image_format not in ALLOWED_IMAGE_FORMATS:
        raise InputValidationError(
            f"{field} must be a PNG or JPEG image (got {image_format})"
        )
    return data, ALLOWED_IMAGE_FORMATS[image_format]


async def read_video_upload(
    file: UploadFile, *, max_bytes: int, field: str
) -> tuple[bytes, str]:
    """Read an uploaded video clip, enforcing the size limit while streaming and
    sniffing the container by content — not filename. MP4/MOV (ISO BMFF, both
    canonicalized to ".mp4") and WebM/Matroska (EBML) are accepted; whether the
    file actually decodes is the caller's job (ffprobe it after saving).

    Returns the raw bytes and the canonical file extension (".mp4" / ".webm").
    """
    data = await _read_capped(file, max_bytes=max_bytes, field=field)

    # ISO BMFF (MP4/MOV): a leading box whose type at bytes 4-8 is "ftyp".
    if len(data) > 12 and data[4:8] == b"ftyp":
        return data, ".mp4"
    # Matroska/WebM: EBML magic.
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return data, ".webm"
    raise InputValidationError(f"{field} must be an MP4, MOV or WebM video file")
