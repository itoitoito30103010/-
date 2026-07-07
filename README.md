# Rakuten Hotel Scraper

Scrapes hotel name/price listings from Rakuten Travel using Playwright with
playwright-stealth, and can fill the results into the
`沖縄県恩納村エリア_競合料金調査_再構築フレームワーク.xlsx` competitor-rate survey
workbook. Two scrape modes:

- **area**: a multi-hotel vacancy-search results page (default; e.g. all
  Onna-son, Okinawa hotels on one listing page).
- **hotel**: a single hotel's own vacancy/rate-calendar page, returning one
  row per room plan. This is what the workbook's `05_採取手順・定義` sheet
  asks for: one scrape per hotel per target week (W1 peak / W2 shoulder / W3
  off), ideally sampling both a weekday and a weekend date per week.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
```

## Usage

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
name in the workbook's `02_競合セット`/`03_料金採取テンプレ` sheets so the
fill step below can find the right row. Pass `--url` twice (weekday +
weekend) to sample both, per the workbook's sampling rule — matching prices
for the same room type are averaged automatically when filled.

```bash
python -m scraper.cli --mode hotel \
    --hotel-name "ハレクラニ沖縄" --week W1 \
    --url "https://travel.rakuten.co.jp/HOTEL/<hotel_no>/yoyaku.html?f_stay_year=2026&f_stay_month=8&f_stay_day=11&f_nights=1&f_stay_adult_n=2&f_room_num=1" \
    --url "https://travel.rakuten.co.jp/HOTEL/<hotel_no>/yoyaku.html?f_stay_year=2026&f_stay_month=8&f_stay_day=15&f_nights=1&f_stay_adult_n=2&f_room_num=1" \
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

- Rakuten renders results client-side and periodically changes its CSS
  class names. `scraper/scraper.py` tries short lists of known selector
  candidates (`HOTEL_CARD_SELECTORS`/`NAME_SELECTORS`/`PRICE_SELECTORS` for
  area mode, `PLAN_CARD_SELECTORS`/`PLAN_NAME_SELECTORS`/`PLAN_PRICE_SELECTORS`
  for hotel mode); if a run returns zero results, inspect the live page and
  add the current class names to those lists.
- Be a good citizen: keep request volume low, respect Rakuten's Terms of
  Service and `robots.txt`, and don't hammer the site with concurrent
  requests.
- Run the tests with `python -m unittest discover -s tests` — they cover the
  room-type classifier and the template-filling logic without touching the
  network.
