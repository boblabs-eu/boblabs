"""Shared sanitizer for repository-bound text and JSONB (D05).

PostgreSQL / asyncpg reject NULL bytes (``\\x00``) and lone UTF-16
surrogates inside ``text`` and ``jsonb`` payloads. Both
``LabMessageRepository`` and ``LabMemoryRepository`` (and any future
repo) need to strip these before flush. Previously the helpers lived
inside ``lab_repo.py`` and the divergence — message repo sanitised
both ``content`` and JSONB fields; memory repo sanitised only
``content`` — was an audit finding (D05).
"""

from __future__ import annotations

import re
from typing import Any

# NULL bytes + the unpaired UTF-16 surrogate range.
_BAD_CHARS = re.compile(r"[\x00\ud800-\udfff]")


def sanitize_text(text: str | None) -> str | None:
    """Strip characters that PostgreSQL / asyncpg cannot store."""
    if text is None:
        return None
    return _BAD_CHARS.sub("�", text)


def sanitize_json(obj: Any) -> Any:
    """Recursively sanitise every string inside a JSON-serialisable obj."""
    if isinstance(obj, str):
        return _BAD_CHARS.sub("�", obj)
    if isinstance(obj, dict):
        return {k: sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_json(v) for v in obj]
    return obj
