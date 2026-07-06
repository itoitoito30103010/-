"""Rakuten Travel hotel rate scraper.

Two modes:
  1. Area search (legacy): scrapes a hotel-list page and returns name/price pairs.
  2. Hotel detail (new):   scrapes individual hotel pages for specific checkin dates
     and classifies room plans into T1-T4 types for competitive rate analysis.

Rakuten renders pages client-side and periodically changes CSS class names.
If selectors return nothing, open the page in a browser, inspect the markup,
and update the selector lists below.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
from dataclasses import dataclass, field
from urllib.parse import urlencode

from playwright.async_api import Page, async_playwright
from playwright_stealth import Stealth

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# ── Area-search selectors (legacy mode) ──────────────────────────────────────
HOTEL_CARD_SELECTORS = [".hotelCard", ".hotelListEachTable", "[id^='hinfo']"]
NAME_SELECTORS = [".hotelName", ".hotelListName", ".hotelNameArea a"]
PRICE_SELECTORS = [".price", ".rateHyoujiBox", ".rate-box .price"]

# ── Hotel-detail selectors ────────────────────────────────────────────────────
PLAN_CARD_SELECTORS = [
    ".planListBox",
    ".plan-item",
    ".planItem",
    "[class*='planList'] li",
    ".roomPlan",
    ".planBox",
]
PLAN_NAME_SELECTORS = [
    ".planName",
    ".plan-name",
    ".planTitle",
    "[class*='planName']",
    "h3",
    "h4",
]
PLAN_PRICE_SELECTORS = [
    ".planPrice .price",
    ".priceArea .price",
    ".price",
    "[class*='price']",
    ".ratePrice",
    ".totalPrice",
]

# ── Room-type classification keywords ────────────────────────────────────────
# Maps T1-T4 to lists of Japanese/English keywords found in plan/room names.
# Evaluated in order T4→T3→T2→T1 so the most-specific wins.
ROOM_TYPE_KEYWORDS: dict[str, list[str]] = {
    "T4": ["ヴィラ", "villa", "コンド", "condo", "プール付", "プール棟", "キッチン付", "コテージ", "cottage"],
    "T3": ["スイート", "suite", "プレミアム", "premium", "クラブ", "club", "エグゼクティブ", "executive", "ペントハウス"],
    "T2": ["オーシャンビュー", "ocean view", "シービュー", "sea view", "デラックス", "deluxe", "スーペリア", "superior", "ビュー", "view"],
    "T1": [],  # fallback
}


@dataclass
class HotelResult:
    """Single name/price pair from an area-search listing (legacy)."""
    name: str
    price: str


@dataclass
class PlanRate:
    """One scraped room plan."""
    plan_name: str
    price_yen: int | None
    room_type: str  # T1-T4


@dataclass
class HotelWeekRates:
    """Rates for one hotel across one check-in week."""
    hotel_name: str
    hotel_url: str
    checkin: str
    checkout: str
    plans: list[PlanRate] = field(default_factory=list)

    def min_price_by_type(self) -> dict[str, int | None]:
        """Return the lowest price per room type (T1-T4), None if unavailable."""
        result: dict[str, int | None] = {"T1": None, "T2": None, "T3": None, "T4": None}
        for plan in self.plans:
            cur = result.get(plan.room_type)
            if plan.price_yen is not None:
                if cur is None or plan.price_yen < cur:
                    result[plan.room_type] = plan.price_yen
        return result


def classify_room_type(name: str) -> str:
    """Return T1-T4 based on keywords in the plan/room name."""
    lower = name.lower()
    for room_type in ("T4", "T3", "T2"):
        for kw in ROOM_TYPE_KEYWORDS[room_type]:
            if kw.lower() in lower:
                return room_type
    return "T1"


def extract_price(text: str) -> int | None:
    """Parse the first number ≥ 1000 from a price string (strip ¥/円/,)."""
    digits = re.findall(r"[\d,]+", text.replace("￥", "").replace("¥", ""))
    for d in digits:
        val = int(d.replace(",", ""))
        if val >= 1000:
            return val
    return None


def build_search_url(
    pref: str,
    area: str,
    adults: int,
    rooms: int,
    checkin: str | None = None,
    checkout: str | None = None,
    page: int = 1,
) -> str:
    params: dict = {"f_stay_adult_n": adults, "f_room_num": rooms}
    if checkin:
        params["f_check_in"] = checkin
    if checkout:
        params["f_check_out"] = checkout
    if page > 1:
        params["f_page"] = page
    return f"https://travel.rakuten.co.jp/search/mih/{pref}/{area}/list.html?{urlencode(params)}"


def build_hotel_url(hotel_id: str, checkin: str, checkout: str, adults: int = 2, rooms: int = 1) -> str:
    params = {
        "f_check_in": checkin,
        "f_check_out": checkout,
        "f_stay_adult_n": adults,
        "f_room_num": rooms,
        "f_meal_cond": "0",  # prefer room-only; fall back to any plan
    }
    return f"https://travel.rakuten.co.jp/HOTEL/{hotel_id}/{hotel_id}.html?{urlencode(params)}"


# ── Area-search (legacy) ──────────────────────────────────────────────────────

async def _query_first(page: Page, selectors: list[str]):
    for selector in selectors:
        elements = await page.query_selector_all(selector)
        if elements:
            return selector, elements
    return None, []


async def scrape_page(page: Page, url: str, min_delay: float, max_delay: float) -> list[HotelResult]:
    logger.info("Fetching %s", url)
    await page.goto(url, wait_until="networkidle")
    await asyncio.sleep(random.uniform(min_delay, max_delay))

    selector, cards = await _query_first(page, HOTEL_CARD_SELECTORS)
    if not cards:
        logger.warning("No hotel cards matched any known selector on %s", url)
        return []
    logger.info("Matched %d card(s) with selector %r", len(cards), selector)

    results: list[HotelResult] = []
    for card in cards:
        name_el = None
        for ns in NAME_SELECTORS:
            name_el = await card.query_selector(ns)
            if name_el:
                break
        price_el = None
        for ps in PRICE_SELECTORS:
            price_el = await card.query_selector(ps)
            if price_el:
                break

        name_text = (await name_el.inner_text()).strip() if name_el else "No Name"
        price_text = (await price_el.inner_text()).strip() if price_el else "0"
        results.append(HotelResult(name=name_text, price=price_text))

    return results


async def scrape(
    urls: list[str],
    headless: bool = True,
    min_delay: float = 3.0,
    max_delay: float = 6.0,
    user_agent: str = DEFAULT_USER_AGENT,
) -> list[HotelResult]:
    all_results: list[HotelResult] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless, executable_path="/opt/pw-browsers/chromium")
        context = await browser.new_context(user_agent=user_agent)
        page = await context.new_page()
        await Stealth().apply_stealth_async(page)

        try:
            for url in urls:
                try:
                    all_results.extend(await scrape_page(page, url, min_delay, max_delay))
                except Exception:
                    logger.exception("Failed to scrape %s", url)
        finally:
            await browser.close()

    return all_results


# ── Hotel-detail rate scraping ────────────────────────────────────────────────

async def _scrape_hotel_week(
    page: Page,
    hotel_name: str,
    hotel_url_base: str,
    checkin: str,
    checkout: str,
    adults: int,
    min_delay: float,
    max_delay: float,
) -> HotelWeekRates:
    """Fetch one hotel page for a specific checkin/checkout and extract plans."""
    hotel_id = re.search(r"/HOTEL/(\d+)/", hotel_url_base)
    if hotel_id:
        url = build_hotel_url(hotel_id.group(1), checkin, checkout, adults)
    else:
        # Fallback: append params to the base URL directly
        sep = "&" if "?" in hotel_url_base else "?"
        url = (
            f"{hotel_url_base}{sep}f_check_in={checkin}&f_check_out={checkout}"
            f"&f_stay_adult_n={adults}&f_room_num=1&f_meal_cond=0"
        )

    result = HotelWeekRates(hotel_name=hotel_name, hotel_url=url, checkin=checkin, checkout=checkout)
    logger.info("Fetching %s (%s→%s)", hotel_name, checkin, checkout)

    try:
        await page.goto(url, wait_until="networkidle", timeout=60_000)
        await asyncio.sleep(random.uniform(min_delay, max_delay))
    except Exception:
        logger.exception("Navigation failed for %s", url)
        return result

    # Try each plan-card selector
    plan_cards = []
    matched_selector = None
    for selector in PLAN_CARD_SELECTORS:
        try:
            plan_cards = await page.query_selector_all(selector)
            if plan_cards:
                matched_selector = selector
                break
        except Exception:
            continue

    if not plan_cards:
        logger.warning("No plan cards found for %s at %s", hotel_name, url)
        # Last-ditch: look for any visible price element on the page
        try:
            price_texts = await page.eval_on_selector_all(
                "[class*='price'],[class*='Price'],[class*='rate'],[class*='Rate']",
                "els => els.map(e => e.innerText).filter(t => /[¥￥\\d,]+/.test(t))",
            )
            for pt in price_texts[:5]:
                price = extract_price(pt)
                if price:
                    result.plans.append(PlanRate(plan_name="(不明)", price_yen=price, room_type="T1"))
        except Exception:
            pass
        return result

    logger.info("Matched %d plan(s) with selector %r for %s", len(plan_cards), matched_selector, hotel_name)

    for card in plan_cards:
        plan_name = ""
        for ns in PLAN_NAME_SELECTORS:
            try:
                el = await card.query_selector(ns)
                if el:
                    plan_name = (await el.inner_text()).strip()
                    if plan_name:
                        break
            except Exception:
                continue

        price_yen: int | None = None
        for ps in PLAN_PRICE_SELECTORS:
            try:
                el = await card.query_selector(ps)
                if el:
                    price_yen = extract_price(await el.inner_text())
                    if price_yen:
                        break
            except Exception:
                continue

        if not plan_name and price_yen is None:
            continue

        room_type = classify_room_type(plan_name)
        result.plans.append(PlanRate(plan_name=plan_name, price_yen=price_yen, room_type=room_type))

    return result


async def scrape_hotel_rates(
    hotels: list[dict],  # [{"name": str, "url": str}, ...]
    weeks: dict[str, tuple[str, str]],  # {"W1": ("2026-08-12", "2026-08-13"), ...}
    adults: int = 2,
    headless: bool = True,
    min_delay: float = 3.0,
    max_delay: float = 7.0,
    user_agent: str = DEFAULT_USER_AGENT,
) -> list[dict]:
    """
    Scrape all hotels × all weeks.

    Returns a list of dicts ready for the Excel template:
        {"name": str, "url": str, "W1": {"T1": int|None, ...}, "W2": ..., "W3": ...}
    """
    results: list[dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless, executable_path="/opt/pw-browsers/chromium")
        context = await browser.new_context(user_agent=user_agent)
        page = await context.new_page()
        await Stealth().apply_stealth_async(page)

        try:
            for hotel in hotels:
                row: dict = {"name": hotel["name"], "url": hotel["url"]}
                for week_label, (checkin, checkout) in weeks.items():
                    week_data = await _scrape_hotel_week(
                        page, hotel["name"], hotel["url"],
                        checkin, checkout, adults, min_delay, max_delay,
                    )
                    row[week_label] = week_data.min_price_by_type()
                    logger.info(
                        "%s %s: %s",
                        hotel["name"], week_label,
                        {k: v for k, v in row[week_label].items() if v},
                    )
                results.append(row)
        finally:
            await browser.close()

    return results
