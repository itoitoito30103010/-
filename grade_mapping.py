"""
grade_mapping.py
楽天APIは客室タイプ指定ができないため、部屋名称＋プラン名の文字列から
T1〜T4 のグレードを判定する。プラン単位のレコードを正規化して扱う。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rakuten_client import _iter_hotel_blocks, _extract_basic

NON_REFUNDABLE_MARKERS = ["返金不可", "返金不可能", "ノンリファンダブル", "non-refundable", "nonrefundable", "非返金"]


@dataclass
class PlanRecord:
    hotel_no: int | None
    hotel_name: str
    room_name: str
    plan_name: str
    total: int | None          # その1泊の税サ込み合計料金（円）
    charge_flag: int | None    # 0=1人あたり / 1=1室あたり
    with_breakfast: bool
    with_dinner: bool
    non_refundable: bool
    reserve_url: str
    grade_code: str | None = None
    grade_label: str | None = None


def _to_int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def parse_plan_records(hotel_record: dict[str, Any]) -> list[PlanRecord]:
    """1つの hotel レコードから、部屋×プラン単位の PlanRecord 群を作る."""
    basic = _extract_basic(hotel_record)
    hotel_name = basic.get("hotelName", "")
    hotel_no = _to_int(basic.get("hotelNo"))

    records: list[PlanRecord] = []
    for block in _iter_hotel_blocks(hotel_record):
        room_infos = block.get("roomInfo")
        if not room_infos:
            continue
        # roomInfo は [ {roomBasicInfo:{...}}, {dailyCharge:{...}} ] のリスト
        room_basic: dict[str, Any] = {}
        daily: dict[str, Any] = {}
        for item in room_infos:
            if "roomBasicInfo" in item:
                room_basic = item["roomBasicInfo"]
            if "dailyCharge" in item:
                daily = item["dailyCharge"]

        room_name = room_basic.get("roomName", "") or ""
        plan_name = room_basic.get("planName", "") or ""
        text = f"{room_name} {plan_name}"

        records.append(
            PlanRecord(
                hotel_no=hotel_no,
                hotel_name=hotel_name,
                room_name=room_name,
                plan_name=plan_name,
                total=_to_int(daily.get("total")),
                charge_flag=_to_int(daily.get("chargeFlag")),
                with_breakfast=str(room_basic.get("withBreakfastFlag", "0")) == "1",
                with_dinner=str(room_basic.get("withDinnerFlag", "0")) == "1",
                non_refundable=any(m.lower() in text.lower() for m in NON_REFUNDABLE_MARKERS),
                reserve_url=room_basic.get("reserveUrl", "") or "",
            )
        )
    return records


def classify(record: PlanRecord, grade_rules: list[dict[str, Any]]) -> None:
    """PlanRecord に grade_code / grade_label を書き込む."""
    text = f"{record.room_name} {record.plan_name}".lower()
    default_rule = None
    for rule in grade_rules:
        if rule.get("is_default"):
            default_rule = rule
            continue
        keywords = rule.get("any_keywords", []) or []
        if any(kw.lower() in text for kw in keywords):
            record.grade_code = rule["code"]
            record.grade_label = rule["label"]
            return
    if default_rule:
        record.grade_code = default_rule["code"]
        record.grade_label = default_rule["label"]
