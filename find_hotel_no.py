#!/usr/bin/env python3
"""
find_hotel_no.py  ―  ホテル名から楽天トラベルの施設番号(hotelNo)を検索。

config.yaml の hotels[].name を使ってキーワード検索し、候補を表示します。
表示された hotel_no を config.yaml に転記すると、以後は施設番号での
高速・確実な取得に切り替わります。

    python find_hotel_no.py
    python find_hotel_no.py "ハレクラニ沖縄"
"""
from __future__ import annotations
import os
import sys
import yaml
from rakuten_client import RakutenTravelClient

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> None:
    cfg_path = os.path.join(HERE, "config.yaml")
    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    app_id = os.getenv("RAKUTEN_APP_ID") or cfg["credentials"]["application_id"]
    access = os.getenv("RAKUTEN_ACCESS_KEY") or cfg["credentials"]["access_key"]

    client = RakutenTravelClient(application_id=app_id, access_key=access,
                                 interval_sec=cfg["search"]["request_interval_sec"])

    if len(sys.argv) > 1:
        names = [" ".join(sys.argv[1:])]
    else:
        names = [h["name"] for h in cfg["hotels"]]

    print("以下の hotel_no を config.yaml の該当ホテルに転記してください。\n")
    for name in names:
        print(f"■ 検索: {name}")
        try:
            hits = client.find_hotel_no(name)
        except Exception as e:  # noqa: BLE001
            print(f"   エラー: {e}")
            continue
        if not hits:
            print("   候補なし（表記を短くして再検索してみてください）")
        for h in hits[:5]:
            print(f"   hotel_no: {h['hotelNo']:>8}   {h['hotelName']}")
        print()


if __name__ == "__main__":
    main()
