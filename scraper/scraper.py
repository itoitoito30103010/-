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
from dataclasses import dataclass
from urllib.parse import urlencode

from playwright.async_api import Page, async_playwright
from playwright_stealth import Stealth

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Candidate selectors, tried in order, since Rakuten's markup shifts over time.
HOTEL_CARD_SELECTORS = [".hotelCard", ".hotelListEachTable", "[id^='hinfo']"]
NAME_SELECTORS = [".hotelName", ".hotelListName", ".hotelNameArea a"]
PRICE_SELECTORS = [".price", ".rateHyoujiBox", ".rate-box .price"]


@dataclass
class HotelResult:
    name: str
    price: str


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
