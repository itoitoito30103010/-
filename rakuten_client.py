"""
rakuten_client.py
楽天トラベル空室検索API (VacantHotelSearch v2017-04-26) の薄いラッパー。

- レートリミット（連続アクセス間隔）
- 429 / 5xx の指数バックオフ再試行
- 404 (not_found = 空室なし) を例外ではなく「空の結果」として返す
"""

from __future__ import annotations

import time
import logging
from typing import Any, Iterable

import requests

logger = logging.getLogger("rakuten")

ENDPOINT = "https://app.rakuten.co.jp/services/api/Travel/VacantHotelSearch/20170426"
KEYWORD_ENDPOINT = "https://app.rakuten.co.jp/services/api/Travel/KeywordHotelSearch/20170426"


class RakutenTravelClient:
    def __init__(
        self,
        application_id: str,
        access_key: str = "",
        affiliate_id: str = "",
        interval_sec: float = 1.0,
        max_retries: int = 4,
        timeout: int = 20,
    ):
        if not application_id:
            raise ValueError(
                "application_id が未設定です。楽天ウェブサービスで取得し、"
                "config.yaml か環境変数 RAKUTEN_APP_ID に設定してください。"
            )
        self.application_id = application_id
        self.access_key = access_key
        self.affiliate_id = affiliate_id
        self.interval_sec = interval_sec
        self.max_retries = max_retries
        self.timeout = timeout
        self._last_call = 0.0
        self._session = requests.Session()

    # ---- 内部: レート制御付きGET -------------------------------------
    def _throttle(self) -> None:
        wait = self.interval_sec - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)

    def _base_params(self) -> dict[str, Any]:
        p = {"applicationId": self.application_id, "format": "json", "formatVersion": 2}
        if self.access_key:
            p["accessKey"] = self.access_key
        if self.affiliate_id:
            p["affiliateId"] = self.affiliate_id
        return p

    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any] | None:
        """成功→dict / 空室なし(404)→None / それ以外→再試行後に例外."""
        attempt = 0
        while True:
            self._throttle()
            try:
                resp = self._session.get(url, params=params, timeout=self.timeout)
                self._last_call = time.time()
            except requests.RequestException as e:
                attempt += 1
                if attempt > self.max_retries:
                    raise
                back = min(2 ** attempt, 30)
                logger.warning("通信エラー %s。%ds後に再試行(%d/%d)", e, back, attempt, self.max_retries)
                time.sleep(back)
                continue

            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 404:
                return None  # not_found = 検索条件に合う空室なし
            if resp.status_code in (429, 500, 503):
                attempt += 1
                if attempt > self.max_retries:
                    resp.raise_for_status()
                back = min(2 ** attempt, 60)
                logger.warning("HTTP %s。%ds後に再試行(%d/%d)", resp.status_code, back, attempt, self.max_retries)
                time.sleep(back)
                continue
            # 400 など → 内容を出して例外
            logger.error("HTTP %s: %s", resp.status_code, resp.text[:300])
            resp.raise_for_status()

    # ---- 公開: 空室検索 ----------------------------------------------
    def search_vacant(
        self,
        checkin: str,
        checkout: str,
        adult_num: int = 2,
        room_num: int = 1,
        hotel_no: Iterable[int] | None = None,
        large_class_code: str | None = None,
        middle_class_code: str | None = None,
        small_class_code: str | None = None,
        max_pages: int = 5,
        squeeze_condition: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        検索パターン1（宿泊プランごと）＋responseType=large で、
        全ページの hotel レコードをフラットなリストで返す。
        1件も無ければ空リスト。
        """
        params = self._base_params()
        params.update(
            {
                "checkinDate": checkin,
                "checkoutDate": checkout,
                "adultNum": adult_num,
                "roomNum": room_num,
                "searchPattern": 1,        # 宿泊プラン・客室単位
                "responseType": "large",   # 全フィールド取得
                "sort": "+roomCharge",     # 安い順
                "hits": 30,
            }
        )
        if hotel_no:
            params["hotelNo"] = ",".join(str(h) for h in hotel_no)
        if large_class_code:
            params["largeClassCode"] = large_class_code
        if middle_class_code:
            params["middleClassCode"] = middle_class_code
        if small_class_code:
            params["smallClassCode"] = small_class_code
        if squeeze_condition:
            params["squeezeCondition"] = squeeze_condition

        all_hotels: list[dict[str, Any]] = []
        page = 1
        while page <= max_pages:
            params["page"] = page
            data = self._get(ENDPOINT, params)
            if not data:
                break
            hotels = data.get("hotels", [])
            all_hotels.extend(hotels)
            paging = data.get("pagingInfo", {})
            page_count = paging.get("pageCount", 1) or 1
            if page >= page_count:
                break
            page += 1
        return all_hotels

    # ---- 公開: 名前から施設番号を検索 --------------------------------
    def find_hotel_no(self, keyword: str) -> list[dict[str, Any]]:
        params = self._base_params()
        params.update({"keyword": keyword, "hits": 10})
        data = self._get(KEYWORD_ENDPOINT, params)
        results = []
        if data:
            for h in data.get("hotels", []):
                info = _extract_basic(h)
                if info:
                    results.append(
                        {"hotelNo": info.get("hotelNo"), "hotelName": info.get("hotelName")}
                    )
        return results


# ======================================================================
#  レスポンス構造ヘルパー（formatVersion=2 / =1 の両対応）
# ======================================================================
def _iter_hotel_blocks(hotel_record: dict[str, Any]) -> list[dict[str, Any]]:
    """1つの hotel レコードから、内部の {hotelBasicInfo|roomInfo...} ブロック列を返す."""
    # formatVersion=2: {"hotel": [ {...}, {...} ]}
    # formatVersion=1: {"hotel": [ {"hotelBasicInfo": {...}}, {"roomInfo": [...]} ]}
    return hotel_record.get("hotel", [])


def _extract_basic(hotel_record: dict[str, Any]) -> dict[str, Any]:
    for block in _iter_hotel_blocks(hotel_record):
        if "hotelBasicInfo" in block:
            return block["hotelBasicInfo"]
    return {}
