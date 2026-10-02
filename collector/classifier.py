from __future__ import annotations

import re
from dataclasses import dataclass


ENTRY_HASHTAG_RE = re.compile(r"#RAPSTAR2026\b", re.IGNORECASE)


@dataclass(frozen=True)
class Classification:
    status: str  # 'entry' | 'unclassified'
    rapper_name: str | None


def classify_caption(caption: str | None) -> Classification:
    """Return classification and best-effort rapper name for a media caption.

    Rule (as of 2026-09-20 sample):
      - '#RAPSTAR2026' hashtag present → 'entry'
      - otherwise → 'unclassified' (never auto-mark 'excluded')

    Rapper name heuristic: first line, split on '/', take first slash-separated
    token trimmed. Returns None if caption is empty or heuristic yields empty.
    """
    if not caption:
        return Classification(status="unclassified", rapper_name=None)

    status = "entry" if ENTRY_HASHTAG_RE.search(caption) else "unclassified"
    rapper_name = _extract_rapper_name(caption)
    return Classification(status=status, rapper_name=rapper_name)


def _extract_rapper_name(caption: str) -> str | None:
    first_line = caption.strip().splitlines()[0] if caption.strip() else ""
    if not first_line:
        return None
    head = first_line.split("/")[0].strip()
    return head or None
