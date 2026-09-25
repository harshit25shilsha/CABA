"""Signed, at-least-once verdict delivery to the Java application."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
import orjson

from app.core.config import settings
from app.models.external_validation import ExternalValidationJob


class JavaWebhookConfigurationError(RuntimeError):
    """The service is missing the Java webhook endpoint or signing secret."""


class JavaWebhookDeliveryError(RuntimeError):
    """Java did not acknowledge a verdict callback successfully."""


@dataclass(frozen=True)
class SignedWebhookPayload:
    body: bytes
    signature: str


def build_signed_verdict(job: ExternalValidationJob) -> SignedWebhookPayload:
    """Serialize exactly once, then sign those same bytes for Java to verify."""

    if job.verdict is None:
        raise JavaWebhookDeliveryError("Cannot deliver a job without a terminal verdict")
    if not settings.CABA_WEBHOOK_HMAC_SECRET:
        raise JavaWebhookConfigurationError("CABA_WEBHOOK_HMAC_SECRET is not configured")

    body = orjson.dumps(
        {
            "upload_id": job.upload_id,
            "external_ref": job.external_ref,
            # Java contract freezes verdicts as uppercase enum names even
            # though Python stores their normalized lowercase values.
            "verdict": job.verdict.name,
            "confidence": job.confidence,
            "explanation": job.explanation,
            "checks": job.checks or [],
        }
    )
    signature = hmac.new(
        settings.CABA_WEBHOOK_HMAC_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return SignedWebhookPayload(body=body, signature=signature)


async def post_signed_verdict(job: ExternalValidationJob) -> None:
    """POST a pre-signed body and require a Java 2xx acknowledgement."""

    _validate_webhook_url()
    signed_payload = build_signed_verdict(job)
    timeout = httpx.Timeout(settings.JAVA_WEBHOOK_TIMEOUT_SECONDS)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await client.post(
                settings.CABA_WEBHOOK_URL,
                content=signed_payload.body,
                headers={
                    "Content-Type": "application/json",
                    "X-AI-Brain-Signature": signed_payload.signature,
                },
            )
    except httpx.HTTPError as exc:
        raise JavaWebhookDeliveryError(f"Java webhook request failed: {exc}") from exc

    if not 200 <= response.status_code < 300:
        raise JavaWebhookDeliveryError(
            f"Java webhook returned HTTP {response.status_code}"
        )


def _validate_webhook_url() -> None:
    if not settings.CABA_WEBHOOK_URL:
        raise JavaWebhookConfigurationError("CABA_WEBHOOK_URL is not configured")
    parsed = urlparse(settings.CABA_WEBHOOK_URL)
    if parsed.scheme != "https" or not parsed.netloc:
        raise JavaWebhookConfigurationError("CABA_WEBHOOK_URL must be an absolute HTTPS URL")
