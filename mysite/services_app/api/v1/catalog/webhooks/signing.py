"""HMAC-SHA256 signing for outbound catalog webhooks.

The consumer (ai-bot-platform) reads ``X-Signature`` from the request
header and recomputes HMAC over the raw body. If the two hexdigests
do not match (constant-time), the consumer drops the message — this
is what protects the catalog cache from a forged delta-push.
"""
from __future__ import annotations

import hashlib
import hmac

_HEADER_PREFIX = "sha256="


def sign_body(body: bytes, secret: str) -> str:
    """Return the value to put in ``X-Signature`` for ``body``.

    Format: ``sha256=<hex>``. The ``sha256=`` prefix is part of the
    contract so the receiver can pick an algorithm without parsing the
    digest length (matches the convention GitHub / Stripe / Shopify
    webhooks use — easy to recognise, easy to evolve later).
    """
    if not isinstance(body, (bytes, bytearray)):
        raise TypeError("body must be bytes (the exact bytes sent over the wire)")
    if not secret:
        raise ValueError("HMAC secret must be a non-empty string")
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"{_HEADER_PREFIX}{digest}"


def verify_signature(body: bytes, secret: str, signature_header: str) -> bool:
    """Constant-time verification of an incoming ``X-Signature`` header.

    Not used by the producer (mysite) itself — kept here so the M3 unit
    tests can exercise the symmetric verify-path and so the consumer
    side has a single canonical implementation to copy-paste from the
    library. ``hmac.compare_digest`` makes timing attacks impossible.
    """
    if not signature_header or not signature_header.startswith(_HEADER_PREFIX):
        return False
    expected = sign_body(body, secret)
    return hmac.compare_digest(expected, signature_header)
