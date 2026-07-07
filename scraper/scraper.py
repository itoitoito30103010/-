"""Rakuten Travel hotel list scraper.

Fetches a Rakuten Travel search-results page (vacancy search) with Playwright,
using playwright-stealth to reduce the chance of being served a bot-check
page, and extracts hotel name / price pairs from the result list.

Rakuten renders this page client-side and periodically changes its CSS class
names, so the selectors below are best-effort defaults. If a scrape returns
zero hotels, open the target URL in a real browser, inspect the result-card
markup, and update HOTEL_CARD_SELECTORS / NAME_SELECTORS / PRICE_SELECTORS.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import urlencode, urljoin

from playwright.async_api import Page, async_playwright
from playwright_stealth import Stealth

from .matching import names_match, normalize_name
from .roomtype import classify_room_type

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Candidate selectors, tried in order, since Rakuten's markup shifts over time.
HOTEL_CARD_SELECTORS = [".hotelCard", ".hotelListEachTable", "[id^='hinfo']"]
NAME_SELECTORS = [".hotelName", ".hotelListName", ".hotelNameArea a"]
PRICE_SELECTORS = [".price", ".rateHyoujiBox", ".rate-box .price"]

# Candidate selectors for a single hotel's vacancy/rate-calendar page (the
# "施設ページ空室・料金カレンダー" the survey's 05 sheet asks operators to use).
# Unverified against a live page (this repo's sandbox can't reach
# travel.rakuten.co.jp) - same best-effort-list convention as the selectors
# above; update from a real page's markup if a scrape returns zero plans.
PLAN_CARD_SELECTORS = [".raq-room-plan", ".plan-list-item", "[id^='plan']", ".searchResultItem"]
PLAN_NAME_SELECTORS = [".plan-name", ".htlPlanName", ".roomTypeName", "h3", "h4"]
PLAN_PRICE_SELECTORS = [".price", ".plan-price", ".total-price", ".rateHyoujiBox"]

# Candidate selectors for the hotel-name *link* on an area/keyword-search
# result card, used to resolve a hotel's own page from its name. Falls back
# to any anchor pointing at a hotel page if the more specific classes miss.
# Same unverified-best-effort caveat as the selector lists above.
HOTEL_LINK_SELECTORS = [".hotelNameArea a", ".hotelName a", ".hotelListName a", "a[href*='/HOTEL/']"]

# Rakuten Travel hotel page URLs are conventionally
# "https://travel.rakuten.co.jp/HOTEL/<hotel_no>/...".
HOTEL_NO_RE = re.compile(r"/HOTEL/(\d+)/")


@dataclass
class HotelResult:
    name: str
    price: str


@dataclass
class PlanResult:
    hotel_name: str
    week: str
    plan_name: str
    price: str
    room_type: str | None = None


def build_search_url(
    pref: str,
    area: str,
    adults: int,
    rooms: int,
    checkin: str | None = None,
    checkout: str | None = None,
    page: int = 1,
) -> str:
    """Build a Rakuten Travel vacancy-search URL for a prefecture/area pair.

    `pref`/`area` are the path segments Rakuten uses internally (e.g.
    "okinawa"/"onnason"), copied from a real search-results URL.
    """
    params = {"f_stay_adult_n": adults, "f_room_num": rooms}
    if checkin:
        params["f_check_in"] = checkin
    if checkout:
        params["f_check_out"] = checkout
    if page > 1:
        params["f_page"] = page
    return f"https://travel.rakuten.co.jp/search/mih/{pref}/{area}/list.html?{urlencode(params)}"


def build_keyword_search_url(keyword: str, pref: str | None = None, area: str | None = None, page: int = 1) -> str:
    """Build a Rakuten Travel free-word search URL to look a hotel up by name.

    Used to resolve a hotel's own page URL when the operator only has the
    hotel's name (e.g. from the survey workbook), not its Rakuten hotel
    number. `pref`/`area` narrow the search when given, matching the same
    path segments as `build_search_url`. Unverified against a live page (see
    module docstring) - if this returns no cards, inspect a real keyword
    search results page and adjust.
    """
    params = {"f_keyword": keyword}
    if pref:
        params["f_dai"] = pref
    if area:
        params["f_sho"] = area
    if page > 1:
        params["f_page"] = page
    return f"https://travel.rakuten.co.jp/dsearch/?{urlencode(params)}"


def build_hotel_vacancy_url(
    hotel_no: str,
    adults: int,
    rooms: int,
    checkin: str | None = None,
    checkout: str | None = None,
) -> str:
    """Build a single hotel's vacancy/rate-calendar page URL from its Rakuten
    hotel number (extracted from its own page's URL via `HOTEL_NO_RE`).
    """
    params = {"f_stay_adult_n": adults, "f_room_num": rooms}
    if checkin:
        params["f_check_in"] = checkin
    if checkout:
        params["f_check_out"] = checkout
    return f"https://travel.rakuten.co.jp/HOTEL/{hotel_no}/yoyaku.html?{urlencode(params)}"


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
        for name_selector in NAME_SELECTORS:
            name_el = await card.query_selector(name_selector)
            if name_el:
                break
        price_el = None
        for price_selector in PRICE_SELECTORS:
            price_el = await card.query_selector(price_selector)
            if price_el:
                break

        name_text = (await name_el.inner_text()).strip() if name_el else "No Name"
        price_text = (await price_el.inner_text()).strip() if price_el else "0"
        results.append(HotelResult(name=name_text, price=price_text))

    return results


async def scrape_hotel_plans(
    page: Page, url: str, hotel_name: str, week: str, min_delay: float, max_delay: float
) -> list[PlanResult]:
    """Scrape one hotel's vacancy/rate-calendar page for its listed room plans.

    Unlike `scrape_page` (one row per hotel on an area listing), a single
    hotel's page lists one row per room plan/type, so callers scrape it once
    per target week (W1/W2/W3) and pass that label through for downstream
    template filling.
    """
    logger.info("Fetching %s", url)
    await page.goto(url, wait_until="networkidle")
    await asyncio.sleep(random.uniform(min_delay, max_delay))

    selector, cards = await _query_first(page, PLAN_CARD_SELECTORS)
    if not cards:
        logger.warning("No plan cards matched any known selector on %s", url)
        return []
    logger.info("Matched %d plan card(s) with selector %r", len(cards), selector)

    results: list[PlanResult] = []
    for card in cards:
        name_el = None
        for name_selector in PLAN_NAME_SELECTORS:
            name_el = await card.query_selector(name_selector)
            if name_el:
                break
        price_el = None
        for price_selector in PLAN_PRICE_SELECTORS:
            price_el = await card.query_selector(price_selector)
            if price_el:
                break

        plan_name = (await name_el.inner_text()).strip() if name_el else "No Name"
        price_text = (await price_el.inner_text()).strip() if price_el else "0"
        results.append(
            PlanResult(
                hotel_name=hotel_name,
                week=week,
                plan_name=plan_name,
                price=price_text,
                room_type=classify_room_type(plan_name),
            )
        )

    return results


async def resolve_hotel_url(
    page: Page,
    hotel_name: str,
    pref: str | None = None,
    area: str | None = None,
    min_delay: float = 3.0,
    max_delay: float = 6.0,
) -> str | None:
    """Look `hotel_name` up on Rakuten's keyword search and return its own
    hotel page URL, or None if no result card's name matches.

    An exact (whitespace/case-insensitive) name match is preferred; if none
    is found, falls back to the first substring match either way.
    """
    url = build_keyword_search_url(hotel_name, pref, area)
    logger.info("Resolving hotel URL for %r via %s", hotel_name, url)
    await page.goto(url, wait_until="networkidle")
    await asyncio.sleep(random.uniform(min_delay, max_delay))

    _, cards = await _query_first(page, HOTEL_CARD_SELECTORS)
    if not cards:
        logger.warning("No hotel cards matched any known selector on %s", url)
        return None

    candidates: list[tuple[str, str]] = []  # (card_name, href)
    for card in cards:
        link_el = None
        for link_selector in HOTEL_LINK_SELECTORS:
            link_el = await card.query_selector(link_selector)
            if link_el:
                break
        if not link_el:
            continue
        href = await link_el.get_attribute("href")
        if not href:
            continue
        card_name = (await link_el.inner_text()).strip()
        if not card_name:
            name_el = None
            for name_selector in NAME_SELECTORS:
                name_el = await card.query_selector(name_selector)
                if name_el:
                    break
            card_name = (await name_el.inner_text()).strip() if name_el else ""
        candidates.append((card_name, href))

    target = normalize_name(hotel_name)
    for card_name, href in candidates:
        if normalize_name(card_name) == target:
            return urljoin(url, href)
    for card_name, href in candidates:
        if names_match(card_name, hotel_name):
            return urljoin(url, href)

    logger.warning("No hotel card name matched %r among %d candidate(s)", hotel_name, len(candidates))
    return None


async def resolve_and_build_hotel_urls(
    hotel_name: str,
    stay_dates: list[str],
    adults: int,
    rooms: int,
    pref: str | None = None,
    area: str | None = None,
    headless: bool = True,
    min_delay: float = 3.0,
    max_delay: float = 6.0,
    user_agent: str = DEFAULT_USER_AGENT,
) -> list[str]:
    """Resolve `hotel_name` to its Rakuten hotel page once, then build one
    vacancy-page URL per date in `stay_dates` (each a 1-night stay).

    Raises ValueError if the hotel can't be resolved, or its hotel number
    can't be extracted from the resolved URL.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(user_agent=user_agent)
        page = await context.new_page()
        await Stealth().apply_stealth_async(page)

        try:
            hotel_url = await resolve_hotel_url(page, hotel_name, pref, area, min_delay, max_delay)
        finally:
            await browser.close()

    if not hotel_url:
        raise ValueError(f"Could not resolve a Rakuten hotel page for {hotel_name!r}")

    match = HOTEL_NO_RE.search(hotel_url)
    if not match:
        raise ValueError(f"Could not extract a hotel number from resolved URL {hotel_url!r}")
    hotel_no = match.group(1)

    urls = []
    for checkin in stay_dates:
        checkout_date = date.fromisoformat(checkin) + timedelta(days=1)
        urls.append(build_hotel_vacancy_url(hotel_no, adults, rooms, checkin, checkout_date.isoformat()))
    return urls


async def scrape(
    urls: list[str],
    headless: bool = True,
    min_delay: float = 3.0,
    max_delay: float = 6.0,
    user_agent: str = DEFAULT_USER_AGENT,
) -> list[HotelResult]:
    all_results: list[HotelResult] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
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


async def scrape_hotels(
    urls: list[str],
    hotel_name: str,
    week: str,
    headless: bool = True,
    min_delay: float = 3.0,
    max_delay: float = 6.0,
    user_agent: str = DEFAULT_USER_AGENT,
) -> list[PlanResult]:
    """Scrape one or more URLs for the same hotel/week (e.g. a weekday and a
    weekend date for the same target week, per the 05 sheet's sampling rule).
    """
    all_results: list[PlanResult] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(user_agent=user_agent)
        page = await context.new_page()
        await Stealth().apply_stealth_async(page)

        try:
            for url in urls:
                try:
                    all_results.extend(
                        await scrape_hotel_plans(page, url, hotel_name, week, min_delay, max_delay)
                    )
                except Exception:
                    logger.exception("Failed to scrape %s", url)
        finally:
            await browser.close()

    return all_results
