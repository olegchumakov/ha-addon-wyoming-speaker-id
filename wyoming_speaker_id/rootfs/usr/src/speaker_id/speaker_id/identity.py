"""Signed speaker mark on a transcript, and the check for the people-list password.

The shared password is the HMAC key and the people-list password. Never log it.
The wire format is SPEC.md.
"""
from __future__ import annotations

import hashlib
import hmac
import math
import secrets
import time
from urllib.parse import quote

_LEFT = "\u27e6"
_RIGHT = "\u27e7"


def encode_name(name: str | None) -> str:
    """Percent-encode a person name: UTF-8, uppercase hex, RFC 3986 unreserved kept."""
    return quote(name or "", safe="")


def format_confidence(score: float | None) -> str:
    """Confidence in ``0.00``..``1.00``. Missing or non-finite scores become ``0.00``."""
    value = 0.0
    if score is not None:
        try:
            value = float(score)
        except (TypeError, ValueError):
            value = 0.0
        else:
            if not math.isfinite(value):
                value = 0.0
    if value < 0.0:
        value = 0.0
    elif value > 1.0:
        value = 1.0
    return f"{value:.2f}"


def identity_name(label: str, name: str | None) -> str:
    """Person name for the mark. Anything below the recognition threshold is empty."""
    if label == "speaker" and name:
        return name
    return ""


def signed_transcript(
    secret: str,
    name: str,
    score: float | None,
    text: str,
    *,
    now: int | None = None,
    nonce: str | None = None,
) -> str:
    """Prepend ``⟦spk1;...⟧`` to ``text``. ``now`` and ``nonce`` are for tests."""
    n = encode_name(name)
    c = format_confidence(score)
    t = str(int(time.time() if now is None else now))
    r = secrets.token_hex(8) if nonce is None else nonce
    message = f"spk1|{n}|{c}|{t}|{r}|{text}"
    sig = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{_LEFT}spk1;n={n};c={c};t={t};r={r};s={sig}{_RIGHT} {text}"


def apply_tag(
    text: str,
    *,
    secret: str,
    label: str,
    name: str | None,
    score: float | None,
    tag_unknown: bool,
    tag_template: str,
    guest_label: str,
    unknown_label: str,
    now: int | None = None,
    nonce: str | None = None,
) -> str:
    """Rewrite a transcript. A non-empty password replaces the name label with a signed mark."""
    if not isinstance(secret, str):
        secret = ""
    if not text.strip():
        return text
    if secret:
        return signed_transcript(
            secret, identity_name(label, name), score, text, now=now, nonce=nonce
        )
    if label in ("short", "uncertain") and not tag_unknown:
        return text
    if label == "speaker":
        who = name or ""
    elif label == "guest":
        who = guest_label
    else:
        who = unknown_label
    if not who:
        return text
    try:
        return tag_template.format(name=who, text=text)
    except (KeyError, IndexError, ValueError):
        return f"[{who}] {text}"


def keys_match(presented: object, secret: object) -> bool:
    """Constant-time password check. An empty password never matches."""
    left = presented if isinstance(presented, str) else ""
    right = secret if isinstance(secret, str) else ""
    same = hmac.compare_digest(
        hashlib.sha256(left.encode("utf-8")).digest(),
        hashlib.sha256(right.encode("utf-8")).digest(),
    )
    return right != "" and same


def people_payload(names) -> dict:
    """Body of ``GET /api/people``: enrolled names only, in a stable order."""
    return {"people": [{"name": n} for n in sorted(names)]}
