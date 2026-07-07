"""Command-line entry point for the Rakuten Travel hotel scraper."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import sys

from .scraper import HotelResult, PlanResult, build_search_url, scrape, scrape_hotels


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape hotel name/price listings from Rakuten Travel.")
    parser.add_argument(
        "--mode",
        choices=["area", "hotel"],
        default="area",
        help=(
            "'area' scrapes a multi-hotel search-results listing (default). "
            "'hotel' scrapes a single hotel's vacancy/rate-calendar page for its room plans "
            "(one CLI run per hotel per target week, per the 03/05 survey sheets)."
        ),
    )
    parser.add_argument("--url", action="append", dest="urls", help="Full page URL to scrape (repeatable). In area mode, overrides --pref/--area. In hotel mode, this is the hotel's own vacancy page (pass twice for a weekday+weekend sample of the same week).")
    parser.add_argument("--pref", default="okinawa", help="Rakuten prefecture path segment (default: okinawa)")
    parser.add_argument("--area", default="onnason", help="Rakuten area path segment (default: onnason)")
    parser.add_argument("--adults", type=int, default=2, help="Number of adults per room (default: 2)")
    parser.add_argument("--rooms", type=int, default=1, help="Number of rooms (default: 1)")
    parser.add_argument("--checkin", help="Check-in date, YYYY-MM-DD")
    parser.add_argument("--checkout", help="Check-out date, YYYY-MM-DD")
    parser.add_argument("--pages", type=int, default=1, help="Number of result pages to fetch (default: 1, area mode only)")
    parser.add_argument("--hotel-name", help="Hotel name as it appears in the survey workbook (required in hotel mode; used to match the correct row when filling the template).")
    parser.add_argument("--week", choices=["W1", "W2", "W3"], help="Target week label for this scrape (required in hotel mode): W1=peak, W2=shoulder, W3=off.")
    parser.add_argument("--headless", action="store_true", default=True, help="Run the browser headless (default)")
    parser.add_argument("--no-headless", dest="headless", action="store_false", help="Show the browser window for debugging")
    parser.add_argument("--min-delay", type=float, default=3.0, help="Minimum seconds to wait after each page load")
    parser.add_argument("--max-delay", type=float, default=6.0, help="Maximum seconds to wait after each page load")
    parser.add_argument("--output", help="Write results to this path (.csv or .json); defaults to stdout")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args(argv)

    if args.mode == "hotel":
        if not args.urls:
            parser.error("--mode hotel requires at least one --url (the hotel's own vacancy page)")
        if not args.hotel_name:
            parser.error("--mode hotel requires --hotel-name")
        if not args.week:
            parser.error("--mode hotel requires --week")

    return args


def write_results(results: list[HotelResult], output: str | None) -> None:
    if not output:
        for r in results:
            print(f"施設名: {r.name} | 価格: {r.price}")
        return

    if output.endswith(".json"):
        with open(output, "w", encoding="utf-8") as f:
            json.dump([r.__dict__ for r in results], f, ensure_ascii=False, indent=2)
    else:
        with open(output, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["name", "price"])
            writer.writeheader()
            for r in results:
                writer.writerow(r.__dict__)


def write_plan_results(results: list[PlanResult], output: str | None) -> None:
    if not output:
        for r in results:
            print(f"ホテル: {r.hotel_name} | 週: {r.week} | プラン: {r.plan_name} | 価格: {r.price} | 室タイプ(推定): {r.room_type or '要確認'}")
        return

    if output.endswith(".json"):
        with open(output, "w", encoding="utf-8") as f:
            json.dump([r.__dict__ for r in results], f, ensure_ascii=False, indent=2)
    else:
        with open(output, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["hotel_name", "week", "plan_name", "price", "room_type"])
            writer.writeheader()
            for r in results:
                writer.writerow(r.__dict__)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.mode == "hotel":
        plan_results = asyncio.run(
            scrape_hotels(
                args.urls,
                hotel_name=args.hotel_name,
                week=args.week,
                headless=args.headless,
                min_delay=args.min_delay,
                max_delay=args.max_delay,
            )
        )
        write_plan_results(plan_results, args.output)
        logging.getLogger(__name__).info("Scraped %d plan(s) for %s (%s)", len(plan_results), args.hotel_name, args.week)
        return 0

    if args.urls:
        urls = args.urls
    else:
        urls = [
            build_search_url(
                args.pref,
                args.area,
                args.adults,
                args.rooms,
                args.checkin,
                args.checkout,
                page,
            )
            for page in range(1, args.pages + 1)
        ]

    results = asyncio.run(
        scrape(urls, headless=args.headless, min_delay=args.min_delay, max_delay=args.max_delay)
    )
    write_results(results, args.output)
    logging.getLogger(__name__).info("Scraped %d hotel(s)", len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
