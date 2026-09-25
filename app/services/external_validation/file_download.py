"""Securely fetch a Java-issued, short-lived document URL in a worker."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from app.core.config import settings


class ExternalDocumentDownloadError(RuntimeError):
    """The Java-supplied URL could not safely provide a valid document."""


@dataclass(frozen=True)
class DownloadedDocument:
    content: bytes
    size_bytes: int


_MIME_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "application/pdf": (b"%PDF-",),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (b"PK\x03\x04",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
}


async def download_external_document(file_url: str, mime_type: str) -> DownloadedDocument:
    """Download and verify the file before it is handed to AI processors.

    The endpoint accepts an URL, never raw bytes. Redirects are refused so a
    signed URL cannot turn the worker into a general-purpose network proxy.
    """

    _validate_url(file_url)
    if mime_type not in settings.ALLOWED_MIME_TYPES:
        raise ExternalDocumentDownloadError(f"Unsupported MIME type: {mime_type}")
    if mime_type not in _MIME_SIGNATURES:
        raise ExternalDocumentDownloadError(f"No signature rule exists for MIME type: {mime_type}")

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    timeout = httpx.Timeout(settings.EXTERNAL_FILE_DOWNLOAD_TIMEOUT_SECONDS)
    chunks: list[bytes] = []
    size_bytes = 0

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            async with client.stream("GET", file_url) as response:
                if response.is_redirect:
                    raise ExternalDocumentDownloadError("Signed document URL must not redirect")
                response.raise_for_status()

                response_mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if response_mime and response_mime != mime_type:
                    raise ExternalDocumentDownloadError(
                        f"Downloaded Content-Type {response_mime!r} does not match {mime_type!r}"
                    )

                async for chunk in response.aiter_bytes():
                    size_bytes += len(chunk)
                    if size_bytes > max_bytes:
                        raise ExternalDocumentDownloadError(
                            f"Downloaded file exceeds {settings.MAX_UPLOAD_SIZE_MB}MB"
                        )
                    chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise ExternalDocumentDownloadError(f"Unable to download signed document URL: {exc}") from exc

    content = b"".join(chunks)
    if not content:
        raise ExternalDocumentDownloadError("Downloaded document is empty")
    if not any(content.startswith(signature) for signature in _MIME_SIGNATURES[mime_type]):
        raise ExternalDocumentDownloadError("Downloaded bytes do not match the declared MIME type")

    return DownloadedDocument(content=content, size_bytes=size_bytes)


def _validate_url(file_url: str) -> None:
    parsed = urlparse(file_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ExternalDocumentDownloadError("Document URL must be an absolute HTTPS URL")
    if parsed.username or parsed.password:
        raise ExternalDocumentDownloadError("Document URL must not include user credentials")
