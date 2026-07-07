"""CLI for the official Rakuten Travel API (see scraper/rakuten_api.py).

Requires the RAKUTEN_APPLICATION_ID and RAKUTEN_ACCESS_KEY environment
variables to be set - see that module's docstring.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from .rakuten_api import RakutenAPIError, extract_hotel_plans, find_area_codes, vacant_hotel_search


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Query the official Rakuten Travel API.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    area = sub.add_parser("area-codes", help="Look up area codes by name via GetAreaClass (one call, walked locally).")
    area.add_argument("--large", required=True, help="Large-class display name, e.g. '日本'")
    area.add_argument("--middle", help="Middle-class display name, e.g. '沖縄'")
    area.add_argument("--small", help="Small-class display name, e.g. '恩納村' (requires --middle)")
    area.add_argument("--detail", help="Detail-class display name (requires --small)")

    search = sub.add_parser(
        "search",
        help="Search vacant hotels/plans via VacantHotelSearch and emit fill_template-ready JSON.",
    )
    search.add_argument("--middle-class-code", required=True)
    search.add_argument("--small-class-code")
    search.add_argument("--checkin", required=True, help="YYYY-MM-DD")
    search.add_argument("--checkout", required=True, help="YYYY-MM-DD")
    search.add_argument("--adults", type=int, default=2)
    search.add_argument("--rooms", type=int, default=1)
    search.add_argument("--week", required=True, choices=["W1", "W2", "W3"], help="Target week label for the scraped records")
    search.add_argument("--output", help="Write JSON records here (scraper.fill_template input); defaults to stdout")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        if args.command == "area-codes":
            result = find_area_codes(args.large, args.middle, args.small, args.detail)
            if not result:
                print("No match found.", file=sys.stderr)
                return 1
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        raw = vacant_hotel_search(
            middle_class_code=args.middle_class_code,
            small_class_code=args.small_class_code,
            checkin=args.checkin,
            checkout=args.checkout,
            adults=args.adults,
            rooms=args.rooms,
        )
        records = extract_hotel_plans(raw, args.week)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
            print(f"Wrote {len(records)} record(s) to {args.output}")
        else:
            print(json.dumps(records, ensure_ascii=False, indent=2))
        return 0
    except RakutenAPIError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
