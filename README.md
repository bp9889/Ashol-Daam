# Ashol Daam (আসল দাম)

Paste a Daraz product link and find out whether the discount is real.
Asol Dam records the product's price over time and compares today's "sale" price with what it usually sells for.

## Run it

You need Python 3.10 or newer.

```bash
cd asol-dam
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements-local.txt
cp .env.example .env                    # optional, defaults work
uvicorn app.main:app --reload
```

Open http://localhost:8000. Five sample products (marked "Sample") are loaded so you can see every verdict straight away. Set `SEED_DEMO_DATA=0` in `.env` to turn them off.

Run the tests:

```bash
pytest
```

## Automatic price checks

While `uvicorn` is running, every tracked product is checked at **10:00 and 22:00 (Dhaka time)**. Change this with `CHECK_TIMES` and `TIMEZONE` in `.env`. If the server starts after a long gap (your laptop was off), it checks once about 30 seconds after starting. You'll see the progress in the terminal.

To check everything right now by hand:

```bash
python -m app.collector
```

To keep checking while your laptop is off, host it online: see **[DEPLOY.md](DEPLOY.md)**.

## Telegram alerts

1. In Telegram, open **@BotFather**, send `/newbot`, and pick a name and a username ending in `bot` (e.g. `AsolDamBot`).
2. BotFather replies with a **token** like `123456789:AAH...`. Keep it secret.
3. Put both in your `.env` file:
   ```
   TELEGRAM_BOT_TOKEN=123456789:AAH...
   TELEGRAM_BOT_USERNAME=AsolDamBot
   ```
4. Restart `uvicorn`. Open a real (not sample) product on the site: a **"Get a Telegram message when it drops"** box appears.
5. Set an alert, press **Open Telegram**, then **Start**. The bot confirms. It messages you after a price check finds the price at or below your target (or 5%+ lower, if you left the target empty).

Bot commands: `/list` shows your alerts, `/stop` turns them all off.

## How it decides

Every product gets a verdict the moment it's pasted. What it's based on depends on what we know:

| Based on | When | How |
|---|---|---|
| **Its own price history** | 7+ days and 4+ checks | Compares today's price with its usual (30-day median) price. The only way to catch a price raised just before a sale. |
| **Other sellers** | Day one, if 2+ other sellers on Daraz sell the same product | Searches Daraz, keeps listings of the same model (`app/market.py`) and compares with their typical price. |
| **The page only** | Day one, no other sellers found | Can't confirm; warns if the claimed discount is 40% or more. |

| Verdict | Meaning |
|---|---|
| Real deal | Clearly cheaper than usual / than other sellers |
| Normal price | About what it usually costs / what others charge |
| Fake discount | Claims a discount, but the "was" price is inflated, the price was pumped before the sale, or it's not actually cheaper |
| Cheaper elsewhere | Other sellers sell the same product for 10%+ less |
| Can't confirm yet | Nothing to compare with yet |

The rules live in `app/verdict.py` and `app/market.py`, covered by `tests/test_verdict.py` and `tests/test_market.py`. Tune the thresholds there.

## Where to buy

For every product with other sellers, the site ranks them so people know where to buy from:

- **Ranked list:** sellers with at least 5 reviews and a rating of 3.8★ or more, or official Daraz Mall stores. The score is half price (each 1% above the cheapest trusted seller costs 3%) and half trust. Trust is the rating pulled toward 3.5★ when there are few reviews (a Bayesian average), so one 5★ review counts for little and 200 reviews count for a lot. Small extras for Mall stores and many sales; a small penalty for shipping from overseas.
- **Cheap but unproven:** no reviews, too few reviews, or poorly rated. Shown separately with the reason, because a low price alone isn't a good enough reason to buy.

Ratings and review counts are for each seller's *listing* of the product, as shown in Daraz search. Tune the numbers at the top of the ranking section in `app/market.py`.

**Checking the Daraz reader yourself.** If something looks off, these print exactly what the site sees:

```bash
python -m app.adapters.daraz product https://www.daraz.com.bd/products/...
python -m app.adapters.daraz search "redmi buds 6 active"
```

## Sizes and options

Many products come in sizes (a perfume in 3 ML to 100 ML). Daraz's search shows each listing at the
price of its *cheapest* size, and its page data only has each size's *regular* price; the sale price
is added by the page's scripts. So for your size Asol Dam:

1. compares only with listings of the same size, opening listings that sell several sizes to find it;
2. reads the sale price the page shows by opening it in a hidden Edge/Chrome (`app/browser.py`),
   a few pages at a time, and stops if Daraz shows a robot check (`BROWSER_PRICES=0` turns it off);
3. if that isn't possible, shows the regular price marked REGULAR with a **Check its price** button,
   and reuses any price confirmed on this site in the last 3 days.

## Project layout

```
app/
  adapters/       one module per store; all return the same ProductData
    base.py       the Adapter interface
    daraz.py      reads Daraz product pages (4 fallbacks: moduleData, tracking data, JSON-LD, Open Graph)
  verdict.py      real deal / normal / fake discount logic
  services.py     track a link, save a price, build the report
  models.py       products + price_snapshots tables (SQLAlchemy)
  collector.py    re-check every tracked product, politely spaced out
  scheduler.py    runs the collector at CHECK_TIMES while the server is up
  alerts.py       when an alert fires, and what the message says
  telegram.py     Telegram bot: linking, /list, /stop, polling or webhook
  seed.py         sample products
  main.py         FastAPI routes + serves the website
static/           the website (HTML, CSS, vanilla JS, hand-drawn SVG chart)
sql/
  schema.sql      the same tables as plain SQL
  queries.sql     analysis queries (window functions, medians, CTEs): good SQL practice
tests/
render.yaml                         Render hosting (alternative to Vercel)
.github/workflows/check-prices.yml  twice-daily checks on GitHub Actions
DEPLOY.md                           free hosting guide
```

## API

| Method | Path | What it does |
|---|---|---|
| POST | `/api/track` `{"url": "..."}` | Start tracking a link (or return it if checked recently) |
| GET | `/api/products` | Every tracked product with its verdict |
| GET | `/api/products/{id}` | Full price history and verdict |
| POST | `/api/products/{id}/refresh` | Check the price again (at most every `MIN_REFRESH_HOURS`) |
| POST | `/api/products/{id}/alerts` `{"target_price": 2250}` | Create a Telegram alert; returns the `t.me` link to confirm it |
| GET | `/api/status` | Check times, next automatic check, whether alerts are on |

Interactive docs: http://localhost:8000/docs

## Being a good citizen

- Only products that users paste are tracked, never the whole site.
- The same product is checked at most every 6 hours (`MIN_REFRESH_HOURS`), and the collector waits 4–9 seconds between products.
- If Daraz shows a robot check, the collector stops instead of retrying.
- Automated collection may go against Daraz's terms of use. Phase 3 (browser extension) removes the need for the server to fetch pages at all.

## Phases

- [x] **Phase 1: core.** Database, Daraz adapter, verdict engine, API, website.
- [x] **Phase 2: automation.** Twice-daily checks, Telegram price-drop alerts, real-deal / fake-discount filters, free hosting setup (Vercel + Neon + GitHub Actions, see DEPLOY.md).
- [ ] **Phase 3: browser extension.** Records the price whenever a user opens a Daraz product page and shows the verdict right on the page. Crowdsourced, no server scraping.
- [ ] **Phase 4: grow.** More stores via new adapters (Amazon through its official Creators API, Pickaboo, Rokomari…), accounts, public "11.11 report".

## Note on the Daraz adapter

The parser was written against Daraz's known page structure and tested with a sample page in `tests/fixtures/`. Daraz changes its pages from time to time. If prices stop being found, save a real product page (`Ctrl+S`) into `tests/fixtures/`, add a test, and adjust `app/adapters/daraz.py`.

Not affiliated with Daraz.
