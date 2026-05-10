"""Stripe webhook signature verification."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any


class WebhookSignatureError(ValueError):
    """Raised when a Stripe webhook signature cannot be trusted."""


def verify_stripe_signature(
    payload: bytes,
    signature_header: str,
    webhook_secret: str,
    *,
    tolerance_seconds: int = 300,
    now: int | None = None,
) -> dict[str, Any]:
    """Verify Stripe's signed payload and return the decoded event."""
    if not webhook_secret:
        raise WebhookSignatureError("Webhook secret is not configured.")
    if not signature_header:
        raise WebhookSignatureError("Missing Stripe-Signature header.")

    timestamp, signatures = _parse_signature_header(signature_header)
    current = int(time.time()) if now is None else now
    if abs(current - timestamp) > tolerance_seconds:
        raise WebhookSignatureError("Webhook signature timestamp is outside tolerance.")

    signed_payload = f"{timestamp}.{payload.decode('utf-8')}".encode("utf-8")
    expected = hmac.new(
        webhook_secret.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()

    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise WebhookSignatureError("Webhook signature verification failed.")

    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise WebhookSignatureError("Webhook payload is not valid JSON.") from exc
    if not isinstance(decoded, dict):
        raise WebhookSignatureError("Webhook payload must decode to an event object.")
    return decoded


def _parse_signature_header(header: str) -> tuple[int, list[str]]:
    timestamp: int | None = None
    signatures: list[str] = []
    for part in header.split(","):
        key, sep, value = part.strip().partition("=")
        if not sep:
            continue
        if key == "t":
            try:
                timestamp = int(value)
            except ValueError as exc:
                raise WebhookSignatureError("Invalid webhook timestamp.") from exc
        elif key == "v1":
            signatures.append(value)

    if timestamp is None or not signatures:
        raise WebhookSignatureError("Malformed Stripe-Signature header.")
    return timestamp, signatures
