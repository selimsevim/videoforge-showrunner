from __future__ import annotations


RETRYABLE_CODES = {"429", "500", "502", "503", "504", "TIMEOUT", "CONNECTION"}
NON_RETRYABLE_CODES = {
    "401",
    "403",
    "INVALID_API_KEY",
    "INVALID_PARAMETER",
    "DATA_INSPECTION_FAILED",
    "MODEL_NOT_FOUND",
}


def is_retryable_error(code: str | int | None, message: str = "") -> bool:
    normalized = str(code or "").upper().replace(" ", "_")
    if normalized in NON_RETRYABLE_CODES:
        return False
    if normalized in RETRYABLE_CODES:
        return True
    lower = message.lower()
    if any(token in lower for token in ("authentication", "moderation", "invalid model")):
        return False
    return any(token in lower for token in ("timeout", "connection", "temporarily", "rate limit"))

