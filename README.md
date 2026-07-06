# Rakuten Hotel Scraper

Scrapes hotel name/price listings from a Rakuten Travel vacancy-search
results page (default: Onna-son, Okinawa) using Playwright with
playwright-stealth.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
```

## Usage

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

## Notes

- Rakuten renders results client-side and periodically changes its CSS
  class names. `scraper/scraper.py` tries a short list of known selector
  candidates (`HOTEL_CARD_SELECTORS`, `NAME_SELECTORS`, `PRICE_SELECTORS`);
  if a run returns zero hotels, inspect the live page and add the current
  class names to those lists.
- Be a good citizen: keep request volume low, respect Rakuten's Terms of
  Service and `robots.txt`, and don't hammer the site with concurrent
  requests.
