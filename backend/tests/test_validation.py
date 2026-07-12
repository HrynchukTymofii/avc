"""Upload and text validation edge cases."""

import io

import pytest
from PIL import Image

from app.services.validation import (
    InputValidationError,
    read_image_upload,
    read_video_upload,
    validate_text,
)


class FakeUpload:
    def __init__(self, data: bytes) -> None:
        self._buffer = io.BytesIO(data)

    async def read(self, size: int = -1) -> bytes:
        return self._buffer.read(size)


def image_bytes(fmt: str) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buffer, format=fmt)
    return buffer.getvalue()


# ---- validate_text -----------------------------------------------------------


def test_validate_text_strips_whitespace() -> None:
    assert validate_text("  hello  ", field="script", max_chars=100) == "hello"


@pytest.mark.parametrize("value", ["", "   ", "\n\t"])
def test_validate_text_rejects_empty(value: str) -> None:
    with pytest.raises(InputValidationError, match="script must not be empty"):
        validate_text(value, field="script", max_chars=100)


def test_validate_text_rejects_too_long() -> None:
    with pytest.raises(InputValidationError, match="maximum 100"):
        validate_text("x" * 101, field="script", max_chars=100)


def test_validate_text_length_checked_after_strip() -> None:
    padded = " " * 50 + "x" * 100 + " " * 50
    assert validate_text(padded, field="script", max_chars=100) == "x" * 100


# ---- read_image_upload --------------------------------------------------------


async def test_accepts_png() -> None:
    data, ext = await read_image_upload(
        FakeUpload(image_bytes("PNG")), max_bytes=10_000_000, field="avatar"
    )
    assert ext == ".png"
    assert data == image_bytes("PNG")


async def test_accepts_jpeg() -> None:
    _, ext = await read_image_upload(
        FakeUpload(image_bytes("JPEG")), max_bytes=10_000_000, field="avatar"
    )
    assert ext == ".jpg"


async def test_rejects_non_image() -> None:
    with pytest.raises(InputValidationError, match="not a valid image"):
        await read_image_upload(
            FakeUpload(b"definitely not an image"), max_bytes=10_000_000, field="avatar"
        )


async def test_rejects_empty_file() -> None:
    with pytest.raises(InputValidationError, match="file is empty"):
        await read_image_upload(FakeUpload(b""), max_bytes=10_000_000, field="avatar")


async def test_rejects_disallowed_format() -> None:
    with pytest.raises(InputValidationError, match="PNG or JPEG"):
        await read_image_upload(
            FakeUpload(image_bytes("GIF")), max_bytes=10_000_000, field="avatar"
        )


async def test_rejects_oversized_upload() -> None:
    with pytest.raises(InputValidationError, match="size limit"):
        await read_image_upload(
            FakeUpload(image_bytes("PNG")), max_bytes=10, field="avatar"
        )


async def test_renamed_extension_is_caught_by_content_sniffing() -> None:
    """A .png filename with GIF bytes must be rejected — content wins over name."""
    upload = FakeUpload(image_bytes("GIF"))
    upload.filename = "innocent.png"  # type: ignore[attr-defined]
    with pytest.raises(InputValidationError, match="PNG or JPEG"):
        await read_image_upload(upload, max_bytes=10_000_000, field="avatar")


# ---- read_video_upload ----------------------------------------------------------

MP4_HEADER = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32
WEBM_HEADER = b"\x1a\x45\xdf\xa3" + b"\x00" * 32


async def test_accepts_mp4_header() -> None:
    data, ext = await read_video_upload(
        FakeUpload(MP4_HEADER), max_bytes=10_000_000, field="clip"
    )
    assert ext == ".mp4"
    assert data == MP4_HEADER


async def test_mov_brand_is_canonicalized_to_mp4() -> None:
    mov = b"\x00\x00\x00\x14ftypqt  " + b"\x00" * 32
    _, ext = await read_video_upload(FakeUpload(mov), max_bytes=10_000_000, field="clip")
    assert ext == ".mp4"


async def test_accepts_webm_header() -> None:
    _, ext = await read_video_upload(
        FakeUpload(WEBM_HEADER), max_bytes=10_000_000, field="clip"
    )
    assert ext == ".webm"


async def test_video_rejects_non_video_bytes() -> None:
    with pytest.raises(InputValidationError, match="MP4, MOV or WebM"):
        await read_video_upload(
            FakeUpload(b"definitely not a video, but long enough"),
            max_bytes=10_000_000,
            field="clip",
        )


async def test_video_rejects_image_bytes() -> None:
    with pytest.raises(InputValidationError, match="MP4, MOV or WebM"):
        await read_video_upload(
            FakeUpload(image_bytes("PNG")), max_bytes=10_000_000, field="clip"
        )


async def test_video_rejects_empty_file() -> None:
    with pytest.raises(InputValidationError, match="file is empty"):
        await read_video_upload(FakeUpload(b""), max_bytes=10_000_000, field="clip")


async def test_video_rejects_oversized_upload() -> None:
    with pytest.raises(InputValidationError, match="size limit"):
        await read_video_upload(FakeUpload(MP4_HEADER), max_bytes=10, field="clip")
