"""Command-line entry point for the Rakuten Travel hotel scraper."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import sys
from pathlib import Path

from .scraper import HotelResult, build_search_url, scrape, scrape_hotel_rates

# 20 hotels from the competitive-rate Excel (sheet 02_競合セット / 03_料金採取テンプレ)
DEFAULT_HOTELS = [
    {"name": "ハレクラニ沖縄",                              "url": "https://travel.rakuten.co.jp/HOTEL/172611/172611.html"},
    {"name": "ハイアットリージェンシー瀬良垣アイランド沖縄",  "url": "https://travel.rakuten.co.jp/HOTEL/166320/166320.html"},
    {"name": "ANAインターコンチネンタル万座ビーチリゾート",    "url": "https://travel.rakuten.co.jp/HOTEL/16123/16123.html"},
    {"name": "シェラトン沖縄サンマリーナリゾート",            "url": "https://travel.rakuten.co.jp/HOTEL/13554/13554.html"},
    {"name": "ルネッサンス リゾート オキナワ",               "url": "https://travel.rakuten.co.jp/HOTEL/54315/54315.html"},
    {"name": "ホテルモントレ沖縄 スパ＆リゾート",            "url": "https://travel.rakuten.co.jp/HOTEL/141596/141596.html"},
    {"name": "沖縄かりゆしビーチリゾート・オーシャンスパ",    "url": "https://travel.rakuten.co.jp/HOTEL/14275/14275.html"},
    {"name": "リザンシーパークホテル谷茶ベイ",               "url": "https://travel.rakuten.co.jp/HOTEL/52229/52229.html"},
    {"name": "ザ・ムーンビーチ ミュージアムリゾート",          "url": "https://travel.rakuten.co.jp/HOTEL/15483/15483.html"},
    {"name": "カフーリゾートフチャクコンド・ホテル",          "url": "https://travel.rakuten.co.jp/HOTEL/78239/78239.html"},
    {"name": "OKINAWA KARIYUSHI RESORT EXES ONNA",          "url": "https://travel.rakuten.co.jp/HOTEL/70318/70318.html"},
    {"name": "HIYORIオーシャンリゾート沖縄",                 "url": "https://travel.rakuten.co.jp/HOTEL/180687/180687.html"},
    {"name": "アクアセンス ホテル & リゾート",               "url": "https://travel.rakuten.co.jp/HOTEL/183576/183576.html"},
    {"name": "UMITO PLAGE The Atta Okinawa",                "url": "https://travel.rakuten.co.jp/HOTEL/179815/179815.html"},
    {"name": "ジ・アッタテラス クラブタワーズ",               "url": "https://travel.rakuten.co.jp/HOTEL/104679/104679.html"},
    {"name": "星野リゾート BEB5 沖縄瀬良垣",                 "url": "https://travel.rakuten.co.jp/HOTEL/184015/184015.html"},
    {"name": "ザ・ペリドット スマートホテル タンチャワード",   "url": "https://travel.rakuten.co.jp/HOTEL/158440/158440.html"},
    {"name": "ザ・プールリゾート沖縄",                        "url": "https://travel.rakuten.co.jp/HOTEL/164539/164539.html"},
    {"name": "ベストウェスタン沖縄恩納ビーチ",                "url": "https://travel.rakuten.co.jp/HOTEL/107650/107650.html"},
    {"name": "オリエンタルヒルズ沖縄",                        "url": "https://travel.rakuten.co.jp/HOTEL/76791/76791.html"},
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape hotel rates from Rakuten Travel for competitive analysis.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Hotel-detail mode (default): scrape the 20 Onnason competitor hotels
  python -m scraper --w1-checkin 2026-08-12 --w1-checkout 2026-08-13 \\
                    --w2-checkin 2026-10-07 --w2-checkout 2026-10-08 \\
                    --w3-checkin 2026-12-08 --w3-checkout 2026-12-09 \\
                    --excel-output rates_filled.xlsx

  # Area-search mode (legacy)
  python -m scraper --area-search --pref okinawa --area onnason --output hotels.csv
        """,
    )

    mode = parser.add_argument_group("Mode")
    mode.add_argument(
        "--area-search",
        action="store_true",
        help="Run area-search (legacy) mode instead of hotel-detail rate collection.",
    )

    detail = parser.add_argument_group("Hotel-detail rate collection (default mode)")
    detail.add_argument("--w1-checkin",  help="W1 (peak) check-in date YYYY-MM-DD")
    detail.add_argument("--w1-checkout", help="W1 (peak) check-out date YYYY-MM-DD")
    detail.add_argument("--w2-checkin",  help="W2 (shoulder) check-in date YYYY-MM-DD")
    detail.add_argument("--w2-checkout", help="W2 (shoulder) check-out date YYYY-MM-DD")
    detail.add_argument("--w3-checkin",  help="W3 (off) check-in date YYYY-MM-DD")
    detail.add_argument("--w3-checkout", help="W3 (off) check-out date YYYY-MM-DD")
    detail.add_argument("--adults", type=int, default=2, help="Adults per room (default: 2)")
    detail.add_argument(
        "--excel-template",
        default="沖縄県恩納村エリア_競合料金調査_再構築フレームワーク.xlsx",
        help="Path to the Excel template to fill (default: 沖縄県恩納村エリア_競合料金調査_再構築フレームワーク.xlsx)",
    )
    detail.add_argument(
        "--excel-output",
        help="Path to write the filled Excel workbook (defaults to overwriting the template).",
    )

    search = parser.add_argument_group("Area-search options (--area-search mode)")
    search.add_argument("--url", action="append", dest="urls", help="Full search URL (repeatable).")
    search.add_argument("--pref", default="okinawa")
    search.add_argument("--area", default="onnason")
    search.add_argument("--rooms", type=int, default=1)
    search.add_argument("--checkin")
    search.add_argument("--checkout")
    search.add_argument("--pages", type=int, default=1)

    common = parser.add_argument_group("Common options")
    common.add_argument("--headless", action="store_true", default=True)
    common.add_argument("--no-headless", dest="headless", action="store_false")
    common.add_argument("--min-delay", type=float, default=3.0)
    common.add_argument("--max-delay", type=float, default=7.0)
    common.add_argument("--output", help="CSV/JSON output path (area-search mode or JSON dump of detail results).")
    common.add_argument("-v", "--verbose", action="store_true")

    return parser.parse_args(argv)


def write_search_results(results: list[HotelResult], output: str | None) -> None:
    if not output:
        for r in results:
            print(f"施設名: {r.name} | 価格: {r.price}")
        return
    if output.endswith(".json"):
        import json
        with open(output, "w", encoding="utf-8") as f:
            json.dump([r.__dict__ for r in results], f, ensure_ascii=False, indent=2)
    else:
        with open(output, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["name", "price"])
            writer.writeheader()
            for r in results:
                writer.writerow(r.__dict__)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger(__name__)

    # ── Area-search (legacy) mode ─────────────────────────────────────────────
    if args.area_search:
        if args.urls:
            urls = args.urls
        else:
            urls = [
                build_search_url(args.pref, args.area, args.adults, args.rooms,
                                 args.checkin, args.checkout, page)
                for page in range(1, args.pages + 1)
            ]
        results = asyncio.run(
            scrape(urls, headless=args.headless, min_delay=args.min_delay, max_delay=args.max_delay)
        )
        write_search_results(results, args.output)
        log.info("Scraped %d hotel(s)", len(results))
        return 0

    # ── Hotel-detail rate-collection mode ─────────────────────────────────────
    weeks: dict[str, tuple[str, str]] = {}
    if args.w1_checkin and args.w1_checkout:
        weeks["W1"] = (args.w1_checkin, args.w1_checkout)
    if args.w2_checkin and args.w2_checkout:
        weeks["W2"] = (args.w2_checkin, args.w2_checkout)
    if args.w3_checkin and args.w3_checkout:
        weeks["W3"] = (args.w3_checkin, args.w3_checkout)

    if not weeks:
        print(
            "ERROR: Specify at least one week (e.g. --w1-checkin 2026-08-12 --w1-checkout 2026-08-13).\n"
            "Use --help for usage.",
            file=sys.stderr,
        )
        return 1

    results = asyncio.run(
        scrape_hotel_rates(
            hotels=DEFAULT_HOTELS,
            weeks=weeks,
            adults=args.adults,
            headless=args.headless,
            min_delay=args.min_delay,
            max_delay=args.max_delay,
        )
    )

    # JSON dump (optional)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        log.info("Raw results written to %s", args.output)

    # Excel output
    template = Path(args.excel_template)
    output_path = Path(args.excel_output) if args.excel_output else template

    if template.exists():
        from .excel_writer import fill_template
        fill_template(template, output_path, results, weeks)
        print(f"Excel filled and saved: {output_path}")
    else:
        log.warning("Excel template not found at %s — skipping Excel output.", template)
        if not args.output:
            # Print to stdout as a fallback
            for row in results:
                print(row["name"])
                for week_label in ("W1", "W2", "W3"):
                    if week_label in row:
                        print(f"  {week_label}: {row[week_label]}")

    log.info("Done. Scraped %d hotel(s) × %d week(s).", len(results), len(weeks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
