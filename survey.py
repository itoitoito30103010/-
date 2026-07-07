#!/usr/bin/env python3
"""
survey.py  ―  競合ホテル料金 自動調査ツール（メイン）

使い方:
    python survey.py                 # config.yaml の全日程・全ホテルを調査
    python survey.py --checkin 2026-08-07 --area okinawa/onna
    python survey.py --dry-run       # サンプルデータでロジック確認（API不要）

出力: outputs/competitor_rates_YYYYMMDD_HHMMSS.xlsx / .csv
"""

from __future__ import annotations

import os
import sys
import csv
import json
import logging
import argparse
import datetime as dt
from typing import Any

import yaml

from rakuten_client import RakutenTravelClient
from grade_mapping import PlanRecord, parse_plan_records, classify

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("survey")

HERE = os.path.dirname(os.path.abspath(__file__))

# 最終出力テーブルのヘッダー（調査プロトコルの出力フォーマット準拠）
HEADERS = ["日程区分", "ホテル名", "グレード", "客室タイプ名", "総額料金(2名)", "プラン名", "備考"]


# ----------------------------------------------------------------------
# 設定読み込み
# ----------------------------------------------------------------------
def load_config(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # 環境変数を優先
    cred = cfg.setdefault("credentials", {})
    cred["application_id"] = os.getenv("RAKUTEN_APP_ID") or cred.get("application_id", "")
    cred["access_key"] = os.getenv("RAKUTEN_ACCESS_KEY") or cred.get("access_key", "")
    cred["affiliate_id"] = os.getenv("RAKUTEN_AFFILIATE_ID") or cred.get("affiliate_id", "")
    return cfg


def add_days(date_str: str, days: int) -> str:
    d = dt.date.fromisoformat(date_str)
    return (d + dt.timedelta(days=days)).isoformat()


def name_matches(target: str, hotel_name: str) -> bool:
    """記号・空白を無視したゆるい部分一致."""
    def norm(s: str) -> str:
        return "".join(ch for ch in s if ch.isalnum() or "ぁ" <= ch <= "ヿ" or "一" <= ch <= "鿿")
    a, b = norm(target), norm(hotel_name)
    if not a or not b:
        return False
    # 先頭の数トークンで一致を見る（正式名称のブレ対策）
    head = a[: max(4, len(a) // 2)]
    return head in b or a in b or b in a


# ----------------------------------------------------------------------
# 収集: 1日程分の全対象ホテル×プランを取得
# ----------------------------------------------------------------------
def collect_records_for_date(
    client: RakutenTravelClient,
    cfg: dict[str, Any],
    checkin: str,
    checkout: str,
) -> list[PlanRecord]:
    s = cfg["search"]
    hotels_cfg = cfg["hotels"]
    area = cfg.get("area", {})

    hotel_nos = [h["hotel_no"] for h in hotels_cfg if h.get("hotel_no")]
    raw_hotels: list[dict[str, Any]] = []

    # (A) hotel_no が分かっているものは施設番号で直接取得（最大15件/リクエスト）
    if hotel_nos:
        for i in range(0, len(hotel_nos), 15):
            batch = hotel_nos[i : i + 15]
            log.info("施設番号で取得: %s", batch)
            raw_hotels += client.search_vacant(
                checkin, checkout,
                adult_num=s["adult_num"], room_num=s["room_num"],
                hotel_no=batch, max_pages=s["max_pages_per_hotel"],
            )

    # (B) hotel_no 未設定のホテルがあれば、エリア一括検索して名前フィルタ
    unresolved = [h for h in hotels_cfg if not h.get("hotel_no")]
    if unresolved and area.get("small_class_codes"):
        for small in area["small_class_codes"]:
            log.info("エリア取得: %s/%s/%s", area["large_class_code"], area["middle_class_code"], small)
            raw_hotels += client.search_vacant(
                checkin, checkout,
                adult_num=s["adult_num"], room_num=s["room_num"],
                large_class_code=area["large_class_code"],
                middle_class_code=area["middle_class_code"],
                small_class_code=small,
                max_pages=s["max_pages_per_hotel"],
            )

    # レコード化 → 対象ホテルのみに絞る
    target_names = [h["name"] for h in hotels_cfg]
    records: list[PlanRecord] = []
    seen_hotel_names: set[str] = set()
    for hr in raw_hotels:
        for rec in parse_plan_records(hr):
            keep = bool(hotel_nos) and rec.hotel_no in set(hotel_nos)
            if not keep:
                keep = any(name_matches(t, rec.hotel_name) for t in target_names)
            if keep:
                records.append(rec)
                seen_hotel_names.add(rec.hotel_name)
    log.info("  → %d プラン取得 / 対象施設 %d 件ヒット", len(records), len(seen_hotel_names))
    return records


# ----------------------------------------------------------------------
# 選定: (ホテル×グレード) ごとに代表プランを1つ選ぶ
# ----------------------------------------------------------------------
def pick_representative(
    records: list[PlanRecord],
    cfg: dict[str, Any],
) -> dict[tuple[str, str], PlanRecord]:
    s = cfg["search"]
    grade_rules = cfg["grades"]

    for r in records:
        classify(r, grade_rules)

    # 食事条件・返金条件でフィルタしつつ、(ホテル名, グレード)ごとに最安を選ぶ
    best: dict[tuple[str, str], PlanRecord] = {}
    for r in records:
        if r.total is None:
            continue
        if s["exclude_non_refundable"] and r.non_refundable:
            continue
        # 食事の優先度スコア（素泊まり優先なら 素泊まり=0, 朝食=1, その他=2）
        key = (r.hotel_name, r.grade_code or "T1")
        cur = best.get(key)
        if cur is None or _better(r, cur, s):
            best[key] = r
    return best


def _meal_rank(r: PlanRecord, meal_pref: str) -> int:
    room_only = (not r.with_breakfast) and (not r.with_dinner)
    if meal_pref == "room_only":
        if room_only:
            return 0
        if r.with_breakfast and not r.with_dinner:
            return 1
        return 2
    else:  # breakfast優先
        if r.with_breakfast and not r.with_dinner:
            return 0
        if room_only:
            return 1
        return 2


def _better(a: PlanRecord, b: PlanRecord, s: dict[str, Any]) -> bool:
    """a が b より代表として望ましいか。まず食事条件、次に価格."""
    ra, rb = _meal_rank(a, s["meal_preference"]), _meal_rank(b, s["meal_preference"])
    if ra != rb:
        return ra < rb
    return (a.total or 1e18) < (b.total or 1e18)


# ----------------------------------------------------------------------
# 1日程を処理し、出力行を作る（2泊フォールバック含む）
# ----------------------------------------------------------------------
def build_rows_for_date(
    client: RakutenTravelClient | None,
    cfg: dict[str, Any],
    date_entry: dict[str, Any],
    preloaded: list[PlanRecord] | None = None,
) -> list[list[Any]]:
    label = date_entry["label"]
    checkin = date_entry["checkin"]
    nights = date_entry.get("nights", 1)
    checkout = add_days(checkin, nights)
    s = cfg["search"]

    if preloaded is not None:
        records = preloaded
    else:
        records = collect_records_for_date(client, cfg, checkin, checkout)

    best = pick_representative(records, cfg)

    # 2泊フォールバック: 空だったホテルを2泊で再検索し1泊平均
    if client is not None and s.get("two_night_fallback"):
        found_hotels = {name for (name, _grade) in best}
        missing = [h["name"] for h in cfg["hotels"]
                   if not any(name_matches(h["name"], fh) for fh in found_hotels)]
        if missing:
            co2 = add_days(checkin, max(nights + 1, 2))
            log.info("[%s] 空室ゼロのため2泊縛りで再検索: %s", label, missing)
            recs2 = collect_records_for_date(client, cfg, checkin, co2)
            for r in recs2:
                if r.total is not None:
                    r.total = round(r.total / max(nights + 1, 2))  # 1泊平均
                    r.plan_name = (r.plan_name + " ｜2泊平均").strip()
            best2 = pick_representative(recs2, cfg)
            for k, v in best2.items():
                best.setdefault(k, v)  # 既存(1泊)を優先

    return _assemble_rows(label, cfg, best, twonight_labels=_twonight_set(cfg, best))


def _twonight_set(cfg, best):
    return {k for k, v in best.items() if "2泊平均" in (v.plan_name or "")}


def _assemble_rows(label, cfg, best, twonight_labels):
    grade_order = [g["code"] for g in cfg["grades"]]
    grade_label = {g["code"]: g["label"] for g in cfg["grades"]}
    rows: list[list[Any]] = []
    for hotel in cfg["hotels"]:
        hname = hotel["name"]
        for gcode in grade_order:
            # このホテル名にゆるく一致する best キーを探す
            match = None
            for (bn, bg), rec in best.items():
                if bg == gcode and name_matches(hname, bn):
                    match = rec
                    break
            if match is None:
                rows.append([label, hname, gcode, "", "N/A（満室/該当なし）", "", ""])
                continue
            notes = []
            if match.with_breakfast and not match.with_dinner:
                notes.append("朝食込")
            if match.with_dinner:
                notes.append("夕食付")
            if "2泊平均" in (match.plan_name or ""):
                notes.append("※2泊縛り料金")
            price = f"¥{match.total:,}" if match.total is not None else "N/A"
            rows.append([
                label, hname, gcode, match.room_name, price,
                match.plan_name.replace(" ｜2泊平均", ""), " / ".join(notes),
            ])
    return rows


# ----------------------------------------------------------------------
# 出力（Excel / CSV）
# ----------------------------------------------------------------------
def write_outputs(all_rows: list[list[Any]], cfg: dict[str, Any]) -> list[str]:
    outdir = os.path.join(HERE, cfg["output"].get("dir", "outputs"))
    os.makedirs(outdir, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    paths = []

    if cfg["output"].get("csv", True):
        cpath = os.path.join(outdir, f"competitor_rates_{stamp}.csv")
        with open(cpath, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(HEADERS)
            w.writerows(all_rows)
        paths.append(cpath)

    if cfg["output"].get("excel", True):
        xpath = os.path.join(outdir, f"competitor_rates_{stamp}.xlsx")
        _write_excel(xpath, all_rows)
        paths.append(xpath)

    return paths


def _write_excel(path: str, rows: list[list[Any]]) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    wb = Workbook()
    ws = wb.active
    ws.title = "競合料金調査"

    header_fill = PatternFill("solid", fgColor="1F3864")
    header_font = Font(name="Meiryo", bold=True, color="FFFFFF", size=11)
    body_font = Font(name="Meiryo", size=10)
    na_font = Font(name="Meiryo", size=10, color="B00000")
    thin = Side(style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center")
    left = Alignment(horizontal="left", vertical="center", wrap_text=True)
    right = Alignment(horizontal="right", vertical="center")

    ws.append(HEADERS)
    for c in ws[1]:
        c.fill, c.font, c.alignment, c.border = header_fill, header_font, center, border

    band = PatternFill("solid", fgColor="F2F5FB")
    prev_label = None
    for row in rows:
        ws.append(row)
        r = ws.max_row
        # 日程区分が変わるたびに薄い帯で見やすく
        if row[0] != prev_label:
            prev_label = row[0]
        for idx, c in enumerate(ws[r], start=1):
            c.border = border
            c.font = body_font
            if idx in (1, 3):
                c.alignment = center
            elif idx == 5:
                c.alignment = right
                if isinstance(c.value, str) and c.value.startswith("N/A"):
                    c.font = na_font
            else:
                c.alignment = left
            if (r % 2) == 0:
                c.fill = band

    widths = [10, 26, 8, 30, 16, 34, 16]
    from openpyxl.utils import get_column_letter
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:G{ws.max_row}"
    wb.save(path)


# ----------------------------------------------------------------------
# メイン
# ----------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="競合ホテル料金 自動調査ツール")
    ap.add_argument("--config", default=os.path.join(HERE, "config.yaml"))
    ap.add_argument("--checkin", help="単発調査: チェックイン日 YYYY-MM-DD（config日程を上書き）")
    ap.add_argument("--nights", type=int, default=1)
    ap.add_argument("--label", default="AD-HOC")
    ap.add_argument("--dry-run", action="store_true", help="APIを呼ばずサンプルデータで動作確認")
    args = ap.parse_args()

    cfg = load_config(args.config)

    # ドライラン: サンプルJSONでロジックのみ検証
    if args.dry_run:
        sample_path = os.path.join(HERE, "sample_response.json")
        with open(sample_path, encoding="utf-8") as f:
            sample = json.load(f)
        records: list[PlanRecord] = []
        for hr in sample.get("hotels", []):
            records += parse_plan_records(hr)
        rows = build_rows_for_date(None, cfg, {"label": "DEMO", "checkin": "2026-08-07", "nights": 1},
                                   preloaded=records)
        paths = write_outputs(rows, cfg)
        _print_table(rows)
        print("\n出力ファイル:")
        for p in paths:
            print("  -", p)
        return

    client = RakutenTravelClient(
        application_id=cfg["credentials"]["application_id"],
        access_key=cfg["credentials"]["access_key"],
        affiliate_id=cfg["credentials"]["affiliate_id"],
        interval_sec=cfg["search"]["request_interval_sec"],
    )

    if args.checkin:
        date_entries = [{"label": args.label, "checkin": args.checkin, "nights": args.nights}]
    else:
        date_entries = cfg["dates"]

    all_rows: list[list[Any]] = []
    for de in date_entries:
        log.info("=== %s (%s〜) 調査開始 ===", de["label"], de["checkin"])
        all_rows += build_rows_for_date(client, cfg, de)

    paths = write_outputs(all_rows, cfg)
    _print_table(all_rows)
    print("\n出力ファイル:")
    for p in paths:
        print("  -", p)


def _print_table(rows: list[list[Any]]) -> None:
    print("\n" + " | ".join(HEADERS))
    print("-" * 100)
    for r in rows:
        print(" | ".join(str(x) for x in r))


if __name__ == "__main__":
    main()
