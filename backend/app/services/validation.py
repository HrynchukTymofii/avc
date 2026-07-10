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
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(_READ_CHUNK_BYTES):
        total += len(chunk)
        if total > max_bytes:
            if max_bytes >= 1024 * 1024:
                limit = f"{max_bytes / (1024 * 1024):g} MB"
            else:
                limit = f"{max_bytes} bytes"
            raise InputValidationError(f"{field} exceeds the {limit} size limit")
        chunks.append(chunk)
    data = b"".join(chunks)

    if not data:
        raise InputValidationError(f"{field} file is empty")

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
