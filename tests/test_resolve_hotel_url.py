import asyncio
import unittest

from scraper.scraper import HOTEL_CARD_SELECTORS, HOTEL_LINK_SELECTORS, resolve_hotel_url


class FakeLink:
    def __init__(self, href, text):
        self._href = href
        self._text = text

    async def get_attribute(self, name):
        return self._href if name == "href" else None

    async def inner_text(self):
        return self._text


class FakeCard:
    def __init__(self, link_selector, href, text):
        self._link_selector = link_selector
        self._link = FakeLink(href, text)

    async def query_selector(self, selector):
        if selector == self._link_selector:
            return self._link
        return None


class FakePage:
    def __init__(self, cards, card_selector=HOTEL_CARD_SELECTORS[0]):
        self._cards = cards
        self._card_selector = card_selector
        self.goto_calls = []

    async def goto(self, url, wait_until=None):
        self.goto_calls.append(url)

    async def query_selector_all(self, selector):
        return self._cards if selector == self._card_selector else []


LINK_SELECTOR = HOTEL_LINK_SELECTORS[0]  # ".hotelNameArea a"


def run(coro):
    return asyncio.run(coro)


class ResolveHotelUrlTest(unittest.TestCase):
    def test_exact_match_returns_absolute_url(self):
        cards = [FakeCard(LINK_SELECTOR, "/HOTEL/74902/index.html", "ハレクラニ沖縄")]
        page = FakePage(cards)
        result = run(resolve_hotel_url(page, "ハレクラニ沖縄", min_delay=0, max_delay=0))
        self.assertEqual(result, "https://travel.rakuten.co.jp/HOTEL/74902/index.html")

    def test_fuzzy_fallback_when_no_exact_match(self):
        cards = [FakeCard(LINK_SELECTOR, "/HOTEL/11111/index.html", "ハレクラニ沖縄（別館）")]
        page = FakePage(cards)
        result = run(resolve_hotel_url(page, "ハレクラニ沖縄", min_delay=0, max_delay=0))
        self.assertEqual(result, "https://travel.rakuten.co.jp/HOTEL/11111/index.html")

    def test_prefers_exact_match_over_earlier_fuzzy_candidate(self):
        cards = [
            FakeCard(LINK_SELECTOR, "/HOTEL/11111/index.html", "ハレクラニ沖縄（別館）"),
            FakeCard(LINK_SELECTOR, "/HOTEL/74902/index.html", "ハレクラニ沖縄"),
        ]
        page = FakePage(cards)
        result = run(resolve_hotel_url(page, "ハレクラニ沖縄", min_delay=0, max_delay=0))
        self.assertEqual(result, "https://travel.rakuten.co.jp/HOTEL/74902/index.html")

    def test_no_matching_card_returns_none(self):
        cards = [FakeCard(LINK_SELECTOR, "/HOTEL/99999/index.html", "全く関係ないホテル")]
        page = FakePage(cards)
        result = run(resolve_hotel_url(page, "ハレクラニ沖縄", min_delay=0, max_delay=0))
        self.assertIsNone(result)

    def test_no_cards_at_all_returns_none(self):
        page = FakePage([])
        result = run(resolve_hotel_url(page, "ハレクラニ沖縄", min_delay=0, max_delay=0))
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
