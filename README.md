# Ashol Dam (আসল দাম)

**Is that Daraz discount real?** Paste a Daraz product link and Ashol Dam tells you in a few seconds:

- whether the "% off" is a real saving or a fake one,
- which trusted seller sells the **same product** for less (price + delivery),
- what the price did before (is it being raised before a sale?).

Live site: **https://ashol-daam.vercel.app**

---

## What it does

| Feature | In plain words |
|---|---|
| **Instant verdict** | Real deal, Fair price, Fake discount, Overpriced, or "can't tell yet", with the reasons. |
| **Fake discount check** | Compares the price with other sellers of the same item and with its own price history. A made-up "old price" gets crossed out in red. |
| **Price raised before a sale** | If a price went up recently and now shows a "discount" (common before 11.11 / 12.12), it's flagged. |
| **Where to buy** | Sellers ranked by **price + delivery fee**, rating and number of reviews. Sellers with few reviews are listed separately. |
| **Same product only** | Matches by the words that *name* the product and by the **product photo**, in the same Daraz category, kind of item, size and pack size. |
| **Alternatives** | If no other seller has the exact item, you see similar items, clearly marked "not the same", which never affect the verdict. |
| **Sizes** | For a 30 ML perfume, only other 30 ML listings are compared, with each size's own sale price. |
| **Price history** | Every product is re-checked at **10 AM and 10 PM** (Dhaka time), and a chart shows how the price moved. |
| **Private history** | "Recently checked" shows only what *you* checked in your browser. |
| **Telegram alerts** (optional) | Get a message when a price drops. |
| **Search** | Find any product you've checked: the search box on the list, or **Ctrl + K** anywhere. The list shows 4 products; pull the handle for the rest. |
| **Install as an app** | "Install app" puts Ashol Dam on your phone or PC. On Android, share a product from the Daraz app straight to Ashol Dam. Products you've checked still open offline. |

## How a check works

1. **Quick step (a few seconds):** reads the product page and searches Daraz for the same item, then shows the verdict.
2. **Detail step (in the background):** opens a few sellers' pages to read sizes, sale prices and delivery fees, and compares product photos. "Where to buy" fills in as it finishes.

Daraz shows some prices (sale prices of sizes, delivery fees) only after the page loads in a browser, so the site opens those pages in a hidden browser: Edge/Chrome on your PC, or a browser service (Browserless) on the live site.

---

## Run it on your computer (Windows)

First time only:
```powershell
python -m venv ..\.venv
..\.venv\Scripts\activate
pip install -r requirements-local.txt
```
After that, just **double-click `start.bat`**. It installs anything new, opens `http://localhost:8000` and picks up code changes by itself.

Run the tests: `pytest`

## Put it online

The live site runs on **Vercel** with a free **Neon** database, and **GitHub Actions** does the twice-daily checks. Step by step: see **[DEPLOY.md](DEPLOY.md)**.

To upload changes:
```powershell
git pull --rebase
git add .
git commit -m "What I changed"
git push
```

---

## Project layout (short)

```
app/adapters/daraz.py   reads Daraz product pages and search results
app/market.py           decides which listings are the SAME product; ranks sellers
app/images.py           compares product photos
app/browser.py          hidden browser for prices Daraz only shows after loading
app/verdict.py          real deal / fake discount / ... and the reasons
app/services.py         puts it all together; saves prices
app/main.py             the website's API
static/                 the website (receipt design, animations)
tests/                  automatic tests, many built from real Daraz data
```

## Good to know

- **Not part of Daraz.** An independent student project. Always double-check on Daraz before you buy.
- **Prices can be a few hours old.**
- Daraz sometimes shows **robot checks** to servers. The site then stops, never tries to get past them, and tries again at the next check.
- Matching is careful on purpose: when it isn't sure two listings are the same item, it leaves them out (or shows them as alternatives).

## What's next

- [x] Daraz price checks, verdicts, sellers, sizes, delivery fees, photos, alerts, live site
- [ ] Browser extension: show the verdict right on the Daraz page
- [ ] More shops (Pickaboo, Star Tech, …)
- [ ] বাংলা language option
