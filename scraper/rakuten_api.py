"""Thin client for Rakuten Travel's official REST APIs, as an alternative to
scraping travel.rakuten.co.jp directly.

Credentials are read from environment variables - both are required
together, per Rakuten's current auth scheme:

    RAKUTEN_APPLICATION_ID   - "アプリID" from your Rakuten Developers app
    RAKUTEN_ACCESS_KEY       - "アクセスキー" from the same app
    RAKUTEN_AFFILIATE_ID     - optional "アフィリエイトID"

Never hardcode these values in source, and never pass them as CLI arguments
(they'd end up in shell history / process listings) - set them as
environment variables instead.

The endpoint base and GetAreaClass's version (20140210) are taken directly
from Rakuten Developers' own API reference page. VacantHotelSearch's
endpoint version below is *not* independently verified from this sandbox
(outbound access to rakuten.co.jp is blocked here) - confirm the current
version on https://webservice.rakuten.co.jp/ before relying on it, and the
same goes for `extract_hotel_plans`'s response key paths: they follow
Rakuten's documented response shape, but adjust them if a real response
doesn't match.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from urllib.parse import urlencode

from .roomtype import classify_room_type

logger = logging.getLogger(__name__)

API_BASE = "https://openapi.rakuten.co.jp/engine/api/Travel"
GET_AREA_CLASS_VERSION = "20140210"
VACANT_HOTEL_SEARCH_VERSION = "20170426"  # unverified from this sandbox - confirm against Rakuten's docs


class RakutenAPIError(RuntimeError):
    pass


class RakutenCredentialsError(RakutenAPIError):
    pass


def _credentials() -> tuple[str, str, str | None]:
    app_id = os.environ.get("RAKUTEN_APPLICATION_ID")
    access_key = os.environ.get("RAKUTEN_ACCESS_KEY")
    if not app_id or not access_key:
        raise RakutenCredentialsError(
            "Set RAKUTEN_APPLICATION_ID and RAKUTEN_ACCESS_KEY environment variables "
            "(both required together) before calling the Rakuten Travel API."
        )
    return app_id, access_key, os.environ.get("RAKUTEN_AFFILIATE_ID")


def _call(endpoint: str, version: str, params: dict) -> dict:
    app_id, access_key, affiliate_id = _credentials()
    query = {
        "applicationId": app_id,
        "accessKey": access_key,
        "format": "json",
        "formatVersion": 2,
        **params,
    }
    if affiliate_id:
        query["affiliateId"] = affiliate_id
    url = f"{API_BASE}/{endpoint}/{version}?{urlencode(query)}"
    logger.debug("Calling %s", url.replace(access_key, "***"))
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        raise RakutenAPIError(f"{endpoint} request failed: HTTP {e.code} {e.reason}") from e
    except urllib.error.URLError as e:
        raise RakutenAPIError(f"{endpoint} request failed: {e.reason}") from e
    return json.loads(body)


def get_area_class(
    large_class: str | None = None,
    middle_class: str | None = None,
    small_class: str | None = None,
) -> dict:
    """Call GetAreaClass, drilling down a level at a time.

    Per Rakuten's docs: omit all filters to get `largeClasses`; pass a
    resolved `large_class` code to get its `middleClasses`; pass both to get
    `smallClasses`; pass all three to get `detailClasses`.
    """
    params = {}
    if large_class:
        params["largeClassCode"] = large_class
    if middle_class:
        params["middleClassCode"] = middle_class
    if small_class:
        params["smallClassCode"] = small_class
    return _call("GetAreaClass", GET_AREA_CLASS_VERSION, params)


def _find_class(classes: list[dict], key: str, name: str) -> dict | None:
    for entry in classes:
        node = entry.get(key, entry)  # tolerate both {"largeClass": {...}} and flat shapes
        if node.get(f"{key}Name") == name:
            return node
    return None


def find_area_codes(
    large_class_name: str, middle_class_name: str, small_class_name: str | None = None
) -> dict | None:
    """Look up area codes by their Japanese display names (e.g.
    large="日本", middle="沖縄", small="恩納村"), drilling down through
    GetAreaClass one level at a time.

    Returns a dict with whichever of large/middle/small class codes+names
    were resolved (fewer keys if a deeper name wasn't found), or None if
    even the large-class name didn't match anything.
    """
    large = get_area_class()
    large_match = _find_class(large.get("largeClasses", []), "largeClass", large_class_name)
    if not large_match:
        logger.warning("No largeClass matched %r", large_class_name)
        return None
    result = {"largeClassCode": large_match["largeClassCode"], "largeClassName": large_match.get("largeClassName")}

    middle = get_area_class(large_class=large_match["largeClassCode"])
    middle_match = _find_class(middle.get("middleClasses", []), "middleClass", middle_class_name)
    if not middle_match:
        logger.warning("No middleClass matched %r under %r", middle_class_name, large_class_name)
        return result
    result["middleClassCode"] = middle_match["middleClassCode"]
    result["middleClassName"] = middle_match.get("middleClassName")

    if not small_class_name:
        return result

    small = get_area_class(large_class=large_match["largeClassCode"], middle_class=middle_match["middleClassCode"])
    small_match = _find_class(small.get("smallClasses", []), "smallClass", small_class_name)
    if not small_match:
        logger.warning("No smallClass matched %r under %r/%r", small_class_name, large_class_name, middle_class_name)
        return result
    result["smallClassCode"] = small_match["smallClassCode"]
    result["smallClassName"] = small_match.get("smallClassName")
    return result


def vacant_hotel_search(
    middle_class_code: str | None = None,
    small_class_code: str | None = None,
    detail_class_code: str | None = None,
    checkin: str | None = None,
    checkout: str | None = None,
    adults: int = 2,
    rooms: int = 1,
    version: str = VACANT_HOTEL_SEARCH_VERSION,
) -> dict:
    """Raw call to VacantHotelSearch. See module docstring: this endpoint's
    version is unverified from this sandbox - confirm against Rakuten's docs.
    """
    params = {"adultNum": adults, "roomNum": rooms}
    if middle_class_code:
        params["middleClassCode"] = middle_class_code
    if small_class_code:
        params["smallClassCode"] = small_class_code
    if detail_class_code:
        params["detailClassCode"] = detail_class_code
    if checkin:
        params["checkinDate"] = checkin
    if checkout:
        params["checkoutDate"] = checkout
    return _call("VacantHotelSearch", version, params)


def extract_hotel_plans(raw_response: dict, week: str) -> list[dict]:
    """Best-effort extraction of per-plan records - in the same shape
    `fill_template.fill_from_records` expects - from a VacantHotelSearch
    response.

    Rakuten's documented response shape nests each hotel's info under a
    "hotel" list of single-key dicts (one with "hotelBasicInfo", one with
    "roomInfo"); this hasn't been checked against a live response from this
    sandbox, so treat it as a starting point - if it returns an empty list
    against a real response, inspect that response's actual structure and
    adjust the key paths below.
    """
    records: list[dict] = []
    for hotel_entry in raw_response.get("hotels", []):
        sections = hotel_entry.get("hotel", [hotel_entry])
        basic = next((s["hotelBasicInfo"] for s in sections if "hotelBasicInfo" in s), {})
        hotel_name = basic.get("hotelName")
        if not hotel_name:
            continue

        room_sections = next((s["roomInfo"] for s in sections if "roomInfo" in s), [])
        for room_entry in room_sections:
            room_basic = room_entry.get("roomBasicInfo", room_entry)
            daily_charge = room_entry.get("dailyCharge", {})
            plan_name = room_basic.get("planName") or room_basic.get("roomClass") or "No Name"
            price = daily_charge.get("total") or daily_charge.get("rakutenCharge")
            if price is None:
                continue
            records.append(
                {
                    "hotel_name": hotel_name,
                    "week": week,
                    "plan_name": plan_name,
                    "price": price,
                    "room_type": classify_room_type(plan_name),
                }
            )
    return records
