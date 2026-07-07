import json
import os
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse

from scraper import rakuten_api
from scraper.rakuten_api import (
    RakutenCredentialsError,
    extract_hotel_plans,
    find_area_codes,
    get_area_class,
    vacant_hotel_search,
)


class CredentialsTest(unittest.TestCase):
    def test_missing_credentials_raise(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RakutenCredentialsError):
                rakuten_api._credentials()

    def test_present_credentials_returned(self):
        env = {"RAKUTEN_APPLICATION_ID": "app-1", "RAKUTEN_ACCESS_KEY": "key-1"}
        with mock.patch.dict(os.environ, env, clear=True):
            app_id, access_key, affiliate_id = rakuten_api._credentials()
        self.assertEqual(app_id, "app-1")
        self.assertEqual(access_key, "key-1")
        self.assertIsNone(affiliate_id)


class CallUrlBuildingTest(unittest.TestCase):
    def setUp(self):
        self.env_patch = mock.patch.dict(
            os.environ, {"RAKUTEN_APPLICATION_ID": "app-1", "RAKUTEN_ACCESS_KEY": "key-1"}, clear=True
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def _mock_response(self, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        cm = mock.MagicMock()
        cm.__enter__.return_value.read.return_value = body
        return cm

    def test_get_area_class_sends_expected_query_and_endpoint(self):
        with mock.patch("urllib.request.urlopen", return_value=self._mock_response({"largeClasses": []})) as urlopen:
            get_area_class()
        called_url = urlopen.call_args[0][0]
        parsed = urlparse(called_url)
        self.assertEqual(parsed.path, "/engine/api/Travel/GetAreaClass/20140210")
        qs = parse_qs(parsed.query)
        self.assertEqual(qs["applicationId"], ["app-1"])
        self.assertEqual(qs["accessKey"], ["key-1"])
        self.assertEqual(qs["format"], ["json"])
        self.assertEqual(qs["formatVersion"], ["2"])

    def test_vacant_hotel_search_query_params(self):
        with mock.patch("urllib.request.urlopen", return_value=self._mock_response({"hotels": []})) as urlopen:
            vacant_hotel_search(middle_class_code="mc", small_class_code="sc", checkin="2026-08-11", checkout="2026-08-12", adults=2, rooms=1)
        parsed = urlparse(urlopen.call_args[0][0])
        self.assertIn("VacantHotelSearch", parsed.path)
        qs = parse_qs(parsed.query)
        self.assertEqual(qs["middleClassCode"], ["mc"])
        self.assertEqual(qs["smallClassCode"], ["sc"])
        self.assertEqual(qs["checkinDate"], ["2026-08-11"])
        self.assertEqual(qs["checkoutDate"], ["2026-08-12"])
        self.assertEqual(qs["adultNum"], ["2"])
        self.assertEqual(qs["roomNum"], ["1"])


class FindAreaCodesTest(unittest.TestCase):
    """GetAreaClass takes no area-code input filters (confirmed from Rakuten's
    own docs) - it returns the whole tree in one call, which find_area_codes
    walks locally. Test both plausible nesting shapes the tree's entries
    might use (flat dicts vs. lists of single-key dicts to merge)."""

    def _flat_tree(self):
        return {
            "largeClasses": [
                {
                    "largeClassCode": "japan",
                    "largeClassName": "日本",
                    "middleClasses": [
                        {
                            "middleClassCode": "okinawa",
                            "middleClassName": "沖縄",
                            "smallClasses": [
                                {"smallClassCode": "onnason", "smallClassName": "恩納村"},
                            ],
                        }
                    ],
                }
            ]
        }

    def _wrapped_tree(self):
        return {
            "largeClasses": [
                {
                    "largeClass": [
                        {"largeClassCode": "japan", "largeClassName": "日本"},
                        {
                            "middleClasses": [
                                {
                                    "middleClass": [
                                        {"middleClassCode": "okinawa", "middleClassName": "沖縄"},
                                        {
                                            "smallClasses": [
                                                {
                                                    "smallClass": {
                                                        "smallClassCode": "onnason",
                                                        "smallClassName": "恩納村",
                                                    }
                                                }
                                            ]
                                        },
                                    ]
                                }
                            ]
                        },
                    ]
                }
            ]
        }

    def test_resolves_three_levels_from_flat_tree(self):
        with mock.patch.object(rakuten_api, "get_area_class", return_value=self._flat_tree()) as m:
            result = find_area_codes("日本", "沖縄", "恩納村")
        self.assertEqual(result["largeClassCode"], "japan")
        self.assertEqual(result["middleClassCode"], "okinawa")
        self.assertEqual(result["smallClassCode"], "onnason")
        m.assert_called_once_with()

    def test_resolves_three_levels_from_wrapped_tree(self):
        with mock.patch.object(rakuten_api, "get_area_class", return_value=self._wrapped_tree()):
            result = find_area_codes("日本", "沖縄", "恩納村")
        self.assertEqual(result["largeClassCode"], "japan")
        self.assertEqual(result["middleClassCode"], "okinawa")
        self.assertEqual(result["smallClassCode"], "onnason")

    def test_large_only_lookup(self):
        with mock.patch.object(rakuten_api, "get_area_class", return_value=self._flat_tree()):
            result = find_area_codes("日本")
        self.assertEqual(result, {"largeClassCode": "japan", "largeClassName": "日本"})

    def test_stops_early_when_large_class_not_found(self):
        with mock.patch.object(rakuten_api, "get_area_class", return_value={"largeClasses": []}):
            result = find_area_codes("存在しない", "沖縄")
        self.assertIsNone(result)

    def test_returns_partial_result_when_middle_not_found(self):
        with mock.patch.object(rakuten_api, "get_area_class", return_value=self._flat_tree()):
            result = find_area_codes("日本", "存在しない県")
        self.assertEqual(result, {"largeClassCode": "japan", "largeClassName": "日本"})


class ExtractHotelPlansTest(unittest.TestCase):
    def test_extracts_plans_from_documented_shape(self):
        raw = {
            "hotels": [
                {
                    "hotel": [
                        {"hotelBasicInfo": {"hotelName": "ハレクラニ沖縄", "hotelNo": 12345}},
                        {
                            "roomInfo": [
                                {
                                    "roomBasicInfo": {"planName": "デラックスオーシャンビュー"},
                                    "dailyCharge": {"total": 80000},
                                },
                                {
                                    "roomBasicInfo": {"planName": "スタンダード"},
                                    "dailyCharge": {"rakutenCharge": 40000},
                                },
                            ]
                        },
                    ]
                }
            ]
        }
        records = extract_hotel_plans(raw, "W1")
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["hotel_name"], "ハレクラニ沖縄")
        self.assertEqual(records[0]["week"], "W1")
        self.assertEqual(records[0]["plan_name"], "デラックスオーシャンビュー")
        self.assertEqual(records[0]["price"], 80000)
        self.assertEqual(records[0]["room_type"], "T2")
        self.assertEqual(records[1]["price"], 40000)
        self.assertEqual(records[1]["room_type"], "T1")

    def test_skips_hotels_missing_a_name(self):
        raw = {"hotels": [{"hotel": [{"hotelBasicInfo": {}}]}]}
        self.assertEqual(extract_hotel_plans(raw, "W1"), [])

    def test_skips_rooms_missing_a_price(self):
        raw = {
            "hotels": [
                {
                    "hotel": [
                        {"hotelBasicInfo": {"hotelName": "Test Hotel"}},
                        {"roomInfo": [{"roomBasicInfo": {"planName": "満室"}, "dailyCharge": {}}]},
                    ]
                }
            ]
        }
        self.assertEqual(extract_hotel_plans(raw, "W1"), [])

    def test_empty_hotels_returns_empty_list(self):
        self.assertEqual(extract_hotel_plans({"hotels": []}, "W1"), [])


if __name__ == "__main__":
    unittest.main()
