"""Keyword-based room-type classification for the T1-T4 template categories.

Definitions come from the "05_採取手順・定義" sheet of the survey workbook:
  T1 スタンダード        - standard, no view guarantee, up to ~35 sqm
  T2 デラックス/OV        - deluxe / superior / ocean view, ~35-55 sqm
  T3 スイート/プレミアム   - suite / premium / club floor, 55 sqm+
  T4 ヴィラ/コンド        - villa / condominium / pool-attached / kitchenette

Classification is a best-effort suggestion only: the workbook explicitly asks
operators to hand-check "判断に迷う部屋" (ambiguous rooms), so callers should
treat an unclassified result as "needs a human to decide", not as missing data.
"""

from __future__ import annotations

T1, T2, T3, T4 = "T1", "T2", "T3", "T4"

# Ordered most-specific-first: a name can match multiple keyword sets (e.g.
# "デラックススイート"), and the higher tier should win.
_KEYWORDS: list[tuple[str, list[str]]] = [
    (T4, ["ヴィラ", "villa", "コンド", "condo", "キッチン付", "プール付", "プールヴィラ"]),
    (T3, ["スイート", "suite", "プレミアム", "premium", "クラブフロア", "club floor", "クラブ"]),
    (T2, ["デラックス", "deluxe", "スーペリア", "superior", "オーシャンビュー", "ocean view", "海側", "オーシャンフロント"]),
    (T1, ["スタンダード", "standard", "シングル", "ツイン", "ダブル"]),
]


def classify_room_type(plan_or_room_name: str) -> str | None:
    """Suggest a T1-T4 bucket for a raw plan/room name, or None if unsure."""
    if not plan_or_room_name:
        return None
    name = plan_or_room_name.strip().lower()
    for tier, keywords in _KEYWORDS:
        if any(kw.lower() in name for kw in keywords):
            return tier
    return None
