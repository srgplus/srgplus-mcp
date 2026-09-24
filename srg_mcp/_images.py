"""Cover-image helpers: load bytes, detect type + size, PUT to a signed URL.

The type is read from the file's magic bytes first, so a cover URL does not
need an extension (signed Drive asset URLs have none). The dimensions are the
real ones, not placeholders. The hosted server never reads local paths.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

from srg_mcp._client import _current_key_var

# Backend limit for a content cover (UpdateContentValidator.ValidateImage).
MAX_COVER_BYTES = 25 * 1024 * 1024

# Extensions the backend accepts for a content cover (RegexPatterns.ImageExtension).
COVER_EXTENSIONS = {"webp", "png", "jpg", "jpeg", "heic", "heif", "ico"}

# Must match the backend's FileHelper.GetContentType: the signed cover PUT is
# bound to this Content-Type, so any other value fails the signature check.
_EXT_TO_MIME = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
    "heic": "image/heic",
    "heif": "image/heif",
    "ico": "image/x-icon",
    "bmp": "image/bmp",
}

_MIME_TO_EXT = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/pjpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/heic": "heic",
    "image/heif": "heif",
    "image/x-icon": "ico",
    "image/vnd.microsoft.icon": "ico",
    "image/bmp": "bmp",
}


@dataclass(frozen=True)
class CoverImage:
    data: bytes
    extension: str
    width: int
    height: int

    @property
    def mime(self) -> str:
        return _EXT_TO_MIME.get(self.extension, "application/octet-stream")

    def upsert(self) -> dict:
        """The ``cover`` object for a create/PATCH body (new image + signed URL)."""
        return {
            "image": {
                "width": self.width,
                "height": self.height,
                "size": len(self.data),
                "extension": self.extension,
            },
            "generateSignedUrl": True,
        }


def is_hosted() -> bool:
    """True inside the hosted multi-tenant server (a request-bound key is set)."""
    return _current_key_var.get() is not None


def sniff_extension(data: bytes) -> str | None:
    """Image format from magic bytes, or ``None`` when not a known image."""
    head = data[:32]
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis"):
            return "heic"
        if brand in (b"mif1", b"msf1"):
            return "heif"
    if head[:2] == b"BM":
        return "bmp"
    if head[:4] == b"\x00\x00\x01\x00":
        return "ico"
    return None


def _suffix(source: str) -> str:
    path = urlparse(source).path if "://" in source else source
    return Path(path).suffix.lstrip(".").lower()


def _dimensions(data: bytes, extension: str) -> tuple[int, int] | None:
    try:
        from srg._upload_multipart import get_image_dimensions
    except ImportError:  # pragma: no cover - very old SDK
        return None
    fd, tmp_path = tempfile.mkstemp(suffix=f".{extension}")
    try:
        with os.fdopen(fd, "wb") as tmp:
            tmp.write(data)
        dims = get_image_dimensions(tmp_path)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
    if dims is None:
        return None
    return int(dims[0]), int(dims[1])


def describe(data: bytes, source: str, content_type: str | None = None) -> CoverImage:
    """Validate an image for use as a content cover and measure it."""
    if not data:
        raise ValueError(f"The image at {_redact(source)} is empty.")
    if len(data) > MAX_COVER_BYTES:
        raise ValueError(
            f"The image at {_redact(source)} is {len(data)} bytes; a cover can be "
            f"at most {MAX_COVER_BYTES} bytes (25 MB)."
        )
    mime = (content_type or "").split(";")[0].strip().lower()
    extension = sniff_extension(data) or _suffix(source) or _MIME_TO_EXT.get(mime, "")
    if extension not in COVER_EXTENSIONS:
        raise ValueError(
            f"The file at {_redact(source)} is not a supported cover image "
            f"(detected type: {extension or 'unknown'}). Use JPEG, PNG, WEBP or HEIC."
        )
    width, height = _dimensions(data, extension) or (1, 1)
    return CoverImage(data=data, extension=extension, width=width, height=height)


def load(source: str) -> CoverImage:
    """Fetch an image from an http(s) URL (or, locally only, a file path)."""
    if source.startswith(("http://", "https://")):
        data, content_type = _download(source)
        return describe(data, source, content_type)
    if is_hosted():
        raise ValueError(
            "cover_image must be an http(s) URL: the hosted SRG+ server cannot "
            "read files on your computer. To use a local file, upload it with "
            "create_upload → run the script → complete_upload, then call "
            "set_cover(content_id, asset_id) (or update_content(cover_asset_id=...))."
        )
    path = Path(source).expanduser()
    if not path.is_file():
        raise ValueError(f"No such image file: {path}")
    return describe(path.read_bytes(), str(path))


def _download(url: str) -> tuple[bytes, str | None]:
    chunks: list[bytes] = []
    total = 0
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            for chunk in resp.iter_bytes():
                total += len(chunk)
                if total > MAX_COVER_BYTES:
                    raise ValueError(
                        f"The image at {_redact(url)} is larger than 25 MB, the "
                        "cover limit."
                    )
                chunks.append(chunk)
            return b"".join(chunks), resp.headers.get("content-type")


def put_signed(url: str, image: CoverImage, headers: dict[str, str] | None) -> None:
    """PUT the image bytes to a presigned URL returned by SRG+."""
    with httpx.Client(timeout=120.0) as client:
        resp = client.put(
            url,
            content=image.data,
            headers={
                "Content-Type": image.mime,
                "Content-Length": str(len(image.data)),
                **(headers or {}),
            },
        )
        resp.raise_for_status()


def _redact(source: str) -> str:
    """Drop the query string (signatures) before echoing a URL in an error."""
    return source.split("?", 1)[0]
