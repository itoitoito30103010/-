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

The endpoint base, GetAreaClass's version (20140210), and its documented
*input* parameters (application ID/access key/affiliate ID/format/
formatVersion/elements/callback - no area-code filters) are taken directly
from Rakuten Developers' own API reference page: GetAreaClass takes no
area-code arguments and returns the full large/middle/small/detailClasses
tree in a single response; `find_area_codes` walks that tree by name rather
than drilling down with repeated filtered calls.

VacantHotelSearch's endpoint version, and the exact nesting of
`get_area_class`'s and `extract_hotel_plans`'s *response* shapes, are *not*
independently verified from this sandbox (outbound access to rakuten.co.jp
is blocked here) - confirm the current version on
https://webservice.rakuten.co.jp/ and check a real response before relying
on them. `_flatten_entry`/`extract_hotel_plans` are written to tolerate a
couple of plausible nesting shapes (Rakuten's family of Travel APIs
sometimes represents a node as a flat dict, sometimes as a list of
single-key dicts to merge), but adjust them if a live response doesn't
match either.
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


def get_area_class() -> dict:
    """Call GetAreaClass and return the full area-code hierarchy.

    Per Rakuten's documented input parameters, this endpoint takes no
    area-code filters - it returns the entire largeClasses/middleClasses/
    smallClasses/detailClasses tree in one response. `find_area_codes` walks
    that tree by display name to resolve the codes you need.
    """
    return _call("GetAreaClass", GET_AREA_CLASS_VERSION, {})


_LEVELS = ("large", "middle", "small", "detail")


def _flatten_entry(entry, level: str) -> dict:
    """Normalize one `{level}Classes` list entry to a flat dict exposing at
    least `{level}ClassCode`/`{level}ClassName` (and, if present, the next
    level's `{nextLevel}Classes` list to descend into).

    Tolerates a `{"largeClass": ...}`-wrapped shape and a flat shape, and -
    since this API family sometimes represents a node as a list of
    single-key dicts to merge (see module docstring) - flattens that too.
    """
    if isinstance(entry, dict) and f"{level}Class" in entry:
        entry = entry[f"{level}Class"]
    if isinstance(entry, list):
        merged: dict = {}
        for part in entry:
            if isinstance(part, dict):
                merged.update(part)
        return merged
    return entry if isinstance(entry, dict) else {}


def find_area_codes(
    large_class_name: str,
    middle_class_name: str | None = None,
    small_class_name: str | None = None,
    detail_class_name: str | None = None,
) -> dict | None:
    """Look up area codes by their Japanese display names (e.g.
    large="日本", middle="沖縄", small="恩納村") in a single GetAreaClass
    response's nested tree.

    Returns a dict with whichever of large/middle/small/detail class
    codes+names were resolved along the requested chain (fewer keys if a
    deeper name wasn't given or wasn't found), or None if even the
    large-class name didn't match anything.
    """
    names = (large_class_name, middle_class_name, small_class_name, detail_class_name)
    container = get_area_class()
    result: dict = {}

    for level, name in zip(_LEVELS, names):
        if name is None:
            break
        entries = container.get(f"{level}Classes", [])
        match = None
        for raw_entry in entries:
            flat = _flatten_entry(raw_entry, level)
            if flat.get(f"{level}ClassName") == name:
                match = flat
                break
        if not match:
            logger.warning("No %sClass matched %r", level, name)
            break
        result[f"{level}ClassCode"] = match.get(f"{level}ClassCode")
        result[f"{level}ClassName"] = match.get(f"{level}ClassName")
        container = match

    return result or None


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
