import unittest

from scraper.roomtype import classify_room_type


class ClassifyRoomTypeTest(unittest.TestCase):
    def test_standard(self):
        self.assertEqual(classify_room_type("スタンダードツイン"), "T1")

    def test_deluxe_ocean_view(self):
        self.assertEqual(classify_room_type("デラックスオーシャンビュー"), "T2")
        self.assertEqual(classify_room_type("Superior Ocean View Room"), "T2")

    def test_suite(self):
        self.assertEqual(classify_room_type("プレミアムスイート"), "T3")

    def test_villa_condo(self):
        self.assertEqual(classify_room_type("プール付きヴィラ"), "T4")
        self.assertEqual(classify_room_type("コンドミニアム 2LDK"), "T4")

    def test_villa_wins_over_deluxe_when_both_present(self):
        # T4 keywords are checked before T2, so a "deluxe villa" lands in T4.
        self.assertEqual(classify_room_type("デラックスヴィラ"), "T4")

    def test_unknown_returns_none(self):
        self.assertIsNone(classify_room_type("特別プラン"))

    def test_empty_returns_none(self):
        self.assertIsNone(classify_room_type(""))
        self.assertIsNone(classify_room_type(None))


if __name__ == "__main__":
    unittest.main()
