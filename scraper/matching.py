"""Shared hotel-name normalization/matching used when looking a hotel up by
name - both against the survey workbook's rows and against Rakuten Travel
keyword-search results.
"""

from __future__ import annotations

import re


def normalize_name(name: str | None) -> str:
    return re.sub(r"\s+", "", name or "").lower()


def names_match(a: str | None, b: str | None) -> bool:
    """Exact match after normalization, or a substring match either way."""
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na
