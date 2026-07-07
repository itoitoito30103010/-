# Rakuten Hotel Scraper

Gets hotel name/room-plan/price data from Rakuten Travel and fills it into
the `沖縄県恩納村エリア_競合料金調査_再構築フレームワーク.xlsx` competitor-rate
survey workbook. Two ways to get the data:

- **`scraper.api_cli`** (recommended if you have a Rakuten Developers app):
  calls Rakuten's official Travel APIs (GetAreaClass / VacantHotelSearch)
  over HTTPS with your `applicationId`/`accessKey` - structured JSON, no
  browser, no CSS-selector guessing.
- **`scraper.cli`** (Playwright + playwright-stealth): scrapes
  travel.rakuten.co.jp's rendered pages directly, for when you don't have
  API credentials. Two modes:
  - **area**: a multi-hotel vacancy-search results page (default; e.g. all
    Onna-son, Okinawa hotels on one listing page).
  - **hotel**: a single hotel's own vacancy/rate-calendar page, returning one
    row per room plan.

Both paths emit the same JSON record shape (`hotel_name`/`week`/`plan_name`/
`price`/`room_type`) that `scraper.fill_template` consumes, so the workbook
fill step (see below) works the same regardless of which one you used. This
is what the workbook's `05_採取手順・定義` sheet asks for either way: one
lookup per hotel per target week (W1 peak / W2 shoulder / W3 off), sampling
both a weekday and a weekend date per week.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
```

## Usage

### Official API mode (`scraper.api_cli`)

Requires a Rakuten Developers app (webservice.rakuten.co.jp) with its
`applicationId` ("アプリID") and `accessKey` ("アクセスキー") - both are
required together. **Never commit these values or put them in this
repo** - set them as environment variables in your own shell:

```bash
export RAKUTEN_APPLICATION_ID="<your app id>"
export RAKUTEN_ACCESS_KEY="<your access key>"
export RAKUTEN_AFFILIATE_ID="<optional affiliate id>"
```

First, resolve the area codes VacantHotelSearch needs. GetAreaClass takes no
area-code filters itself - one call returns the entire large/middle/small/
detailClasses tree, which `area-codes` walks locally by display name:

```bash
python -m scraper.api_cli area-codes --large "日本" --middle "沖縄" --small "恩納村"
```

Then search vacant hotels/plans for a target week and write records straight
to a JSON file:

```bash
python -m scraper.api_cli search \
    --middle-class-code <code from area-codes> --small-class-code <code from area-codes> \
    --checkin 2026-08-11 --checkout 2026-08-12 --adults 2 --rooms 1 \
    --week W1 --output results/w1.json
```

Repeat per target week (W1/W2/W3), then feed all the resulting JSON files to
`scraper.fill_template` as usual (see below).

### Area mode (listing page)

```bash
# Default: Onna-son, Okinawa, 2 adults, 1 room, page 1
python -m scraper.cli

# Custom area / occupancy / dates
python -m scraper.cli --area onnason --pref okinawa --adults 2 --rooms 1 \
    --checkin 2026-08-01 --checkout 2026-08-02

# Fetch multiple result pages and write to CSV
python -m scraper.cli --pages 3 --output hotels.csv

# Pass a full URL directly (repeatable) instead of building one
python -m scraper.cli --url "https://travel.rakuten.co.jp/search/mih/okinawa/onnason/list.html?f_stay_adult_n=2&f_room_num=1"

# Watch the browser while debugging selectors
python -m scraper.cli --no-headless -v
```

### Hotel mode (per-hotel rate calendar, for the survey workbook)

Run once per hotel per target week. `--hotel-name` must match the hotel's
name in the workbook's `02_競合セット`/`03_料金採取テンプレ` sheets so both
URL resolution and the fill step below can find the right hotel/row.

**Auto-resolve the URL from the hotel's name** (recommended) by passing
`--stay-date` instead of `--url`: the scraper looks the hotel up on Rakuten's
keyword search, follows its result card to the hotel's own page, extracts
its Rakuten hotel number, and builds one vacancy-page URL per `--stay-date`.
Pass `--stay-date` twice (a weekday + a weekend date) to sample both per the
workbook's sampling rule — matching prices for the same room type are
averaged automatically when filled.

```bash
python -m scraper.cli --mode hotel \
    --hotel-name "ハレクラニ沖縄" --week W1 \
    --stay-date 2026-08-11 --stay-date 2026-08-15 \
    --output results/harekurani_w1.json
```

Or pass the hotel's vacancy-page URL(s) directly with `--url` to skip
auto-resolution entirely (e.g. if keyword search picks the wrong hotel, or
you already have the URL):

```bash
python -m scraper.cli --mode hotel \
    --hotel-name "ハレクラニ沖縄" --week W1 \
    --url "https://travel.rakuten.co.jp/HOTEL/<hotel_no>/yoyaku.html?f_stay_adult_n=2&f_room_num=1&f_check_in=2026-08-11&f_check_out=2026-08-12" \
    --url "https://travel.rakuten.co.jp/HOTEL/<hotel_no>/yoyaku.html?f_stay_adult_n=2&f_room_num=1&f_check_in=2026-08-15&f_check_out=2026-08-16" \
    --output results/harekurani_w1.json
```

Repeat for each of the ~20 hotels × 3 weeks (W1/W2/W3), writing each run's
`--output` to its own JSON file. Each scraped plan's room type is
auto-suggested from its plan name (see `scraper/roomtype.py`); the workbook's
own rule is to hand-check anything ambiguous, so double-check the
`room_type` field before filling — or set/override it directly in the JSON.

### Filling the survey workbook

Once you have one or more JSON result files from hotel-mode runs:

```bash
python -m scraper.fill_template \
    --xlsx "沖縄県恩納村エリア_競合料金調査_再構築フレームワーク.xlsx" \
    --data results/*.json \
    --output "沖縄県恩納村エリア_競合料金調査_再構築フレームワーク_filled.xlsx"
```

This writes each record's price into the matching hotel row / week / T1-T4
column on `03_料金採取テンプレ` (averaging multiple samples on the same
cell), and prints a warning for any record it couldn't place — unresolved
room type, unmatched hotel name, or an unparseable price — rather than
guessing. The `04_再構築分析` sheet's averages/medians recalculate
automatically from its existing formulas once opened in Excel/Sheets.

## Notes

- `scraper/rakuten_api.py`'s GetAreaClass endpoint/version (`20140210`) is
  taken directly from Rakuten Developers' own API reference page.
  VacantHotelSearch's endpoint version and `extract_hotel_plans`'s response
  key paths are best-effort, based on Rakuten's documented response shape,
  but are *not* independently verified against a live response (outbound
  access to rakuten.co.jp is blocked in this sandbox) - if a real search
  returns zero records, inspect the raw response and adjust
  `extract_hotel_plans` accordingly.
- Never commit `RAKUTEN_APPLICATION_ID`/`RAKUTEN_ACCESS_KEY` values, put them
  in code, or pass them as CLI flags (they'd land in shell history) - set
  them as environment variables only. `.env`/`.env.*` are gitignored if you
  keep them in a local dotenv file.
- Rakuten renders results client-side and periodically changes its CSS
  class names. `scraper/scraper.py` tries short lists of known selector
  candidates (`HOTEL_CARD_SELECTORS`/`NAME_SELECTORS`/`PRICE_SELECTORS` for
  area mode, `PLAN_CARD_SELECTORS`/`PLAN_NAME_SELECTORS`/`PLAN_PRICE_SELECTORS`
  for hotel mode, `HOTEL_LINK_SELECTORS` for name-based URL resolution); if a
  run returns zero results, inspect the live page and add the current class
  names to those lists. `build_keyword_search_url`'s `/dsearch/` endpoint and
  param names are likewise a best-effort guess, unverified against a live
  page — check it resolves to the expected hotel before relying on it.
- Be a good citizen: keep request volume low, respect Rakuten's Terms of
  Service and `robots.txt`, and don't hammer the site with concurrent
  requests.
- Run the tests with `python -m unittest discover -s tests` — they cover the
  room-type classifier and the template-filling logic without touching the
  network.
