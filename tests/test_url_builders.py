import unittest
from urllib.parse import parse_qs, urlparse

from scraper.scraper import (
    HOTEL_NO_RE,
    build_hotel_vacancy_url,
    build_keyword_search_url,
    build_search_url,
)


class BuildSearchUrlTest(unittest.TestCase):
    def test_basic_params(self):
        url = build_search_url("okinawa", "onnason", 2, 1)
        parsed = urlparse(url)
        self.assertEqual(parsed.path, "/search/mih/okinawa/onnason/list.html")
        qs = parse_qs(parsed.query)
        self.assertEqual(qs["f_stay_adult_n"], ["2"])
        self.assertEqual(qs["f_room_num"], ["1"])
        self.assertNotIn("f_page", qs)

    def test_page_param_only_added_when_over_1(self):
        url = build_search_url("okinawa", "onnason", 2, 1, page=3)
        self.assertIn("f_page=3", url)


class BuildKeywordSearchUrlTest(unittest.TestCase):
    def test_keyword_only(self):
        url = build_keyword_search_url("ハレクラニ沖縄")
        parsed = urlparse(url)
        self.assertEqual(parsed.path, "/dsearch/")
        qs = parse_qs(parsed.query)
        self.assertEqual(qs["f_keyword"], ["ハレクラニ沖縄"])
        self.assertNotIn("f_dai", qs)

    def test_with_pref_and_area(self):
        url = build_keyword_search_url("ハレクラニ沖縄", pref="okinawa", area="onnason")
        qs = parse_qs(urlparse(url).query)
        self.assertEqual(qs["f_dai"], ["okinawa"])
        self.assertEqual(qs["f_sho"], ["onnason"])


class BuildHotelVacancyUrlTest(unittest.TestCase):
    def test_basic(self):
        url = build_hotel_vacancy_url("12345", 2, 1, checkin="2026-08-11", checkout="2026-08-12")
        self.assertTrue(url.startswith("https://travel.rakuten.co.jp/HOTEL/12345/yoyaku.html?"))
        qs = parse_qs(urlparse(url).query)
        self.assertEqual(qs["f_check_in"], ["2026-08-11"])
        self.assertEqual(qs["f_check_out"], ["2026-08-12"])

    def test_hotel_no_roundtrips_through_regex(self):
        url = build_hotel_vacancy_url("98765", 2, 1)
        match = HOTEL_NO_RE.search(url)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "98765")


if __name__ == "__main__":
    unittest.main()
