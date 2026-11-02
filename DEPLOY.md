# Put Ashol Dam online for free (Vercel)

When the site runs on your laptop, prices are only checked while the laptop is on.
This setup keeps everything running 24/7 at no cost:

| Part | Service | Note |
|---|---|---|
| Website | **Vercel** | Finds the FastAPI app in `app/main.py` by itself. No settings file needed. |
| Database | **Neon** (PostgreSQL), added from inside Vercel | Vercel can't keep files, so the database lives here. |
| Twice-daily price checks | **GitHub Actions** | Runs `python -m app.collector` at 10 AM and 10 PM Dhaka time, with Chrome, so sizes' sale prices are read too. |
| Telegram alerts | Your bot | Messages come in through the website (webhook). |

Vercel can't run a browser itself. Without step 6, pasting a product on the live site shows
other sellers' sizes at their **regular** price (with a **Check its price** button) and no delivery
fees; the twice-daily checks on GitHub fill in the rest within a day. Step 6 fills in the rest during the check itself.

---

## 1. Code on GitHub

Already done: the project is in your GitHub account as `Ashol-Daam`.
`.env` and `*.db` are in `.gitignore`, so secrets and your local database never go online.

To upload later changes from your laptop, install Git (git-scm.com), then in the project folder:

```bash
git add .
git commit -m "What I changed"
git push
```

Vercel puts every push live by itself within a minute or two.

## 2. Deploy the website

1. Go to **vercel.com** and sign up with **Continue with GitHub**.
2. **Add New… → Project**, find `Ashol-Daam`, press **Import**. If you don't see it, press
   **Adjust GitHub App Permissions** and allow access to the repository.
3. Leave the settings as they are and press **Deploy**.

## 3. Add the database

1. In your Vercel project: **Storage → Create Database → Neon** (free plan), region **Singapore**.
2. Connect it to the project for all environments. Vercel adds `DATABASE_URL` for you.
3. **Deployments →** the latest one **→ ⋯ → Redeploy**, so the site picks up the database.
4. Open your site (`https://ashol-daam.vercel.app`) and paste a Daraz link.

## 4. Turn on the twice-daily checks (GitHub Actions)

1. In Vercel: **Settings → Environment Variables**, reveal `DATABASE_URL` and copy it.
2. In GitHub, in the `Ashol-Daam` repository: **Settings → Secrets and variables → Actions → New repository secret**
   - Name `DATABASE_URL`, value: what you copied.
   - `TELEGRAM_BOT_TOKEN`: your bot token (only if you use alerts).
3. Go to the **Actions** tab, open **Check prices**, press **Run workflow** to try it now.
   The log shows lines like `[1/3] Product name: 2499.00`.

From then on it runs by itself at 10:00 and 22:00 Dhaka time. This is what catches prices being
raised before 11.11 and 12.12.

Keep `DATABASE_URL` secret: anyone with it can read and change your database.

## 5. Telegram alerts on the live site (optional)

1. In Vercel → **Settings → Environment Variables**, add `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`
   and `TELEGRAM_WEBHOOK_SECRET` (any long random text), then redeploy.
2. On your laptop, in the project folder (with your venv active), PowerShell:
   ```powershell
   $env:TELEGRAM_BOT_TOKEN="your-token"; $env:TELEGRAM_WEBHOOK_SECRET="the-same-secret"
   python -m app.telegram set-webhook https://your-site.vercel.app
   ```
3. Message your bot `/start`. It should reply.

To test alerts on your laptop again: `python -m app.telegram delete-webhook`.

## 6. Sale prices and delivery fees during each check on the live site (Browserless)

1. Sign up free at **browserless.io** and copy your **API token** from the dashboard.
2. In Vercel → **Settings → Environment Variables**, add
   - Key `BROWSER_WS_URL`
   - Value `wss://production-sfo.browserless.io?token=YOUR_TOKEN` (your token instead of YOUR_TOKEN)
3. Redeploy. Checks that open sellers' pages take 10–30 seconds; the page tells visitors to wait.

The free plan has a monthly limit. When it runs out, or if Daraz shows Browserless a robot check,
the site falls back to how it worked before step 6. Keep the token secret.

---

## If Daraz blocks the checks

Daraz may show a robot check to cloud servers (GitHub, Vercel) more often than to a home connection.
The GitHub log then says `Stopped: Daraz showed a robot check…`. If that keeps happening, run the
checks from your laptop but save them to the online database: put the same `DATABASE_URL` in your
laptop's `.env` and start the site with `start.bat`. The live site shows the same data.

## Moving your laptop's products online

Open the live site and paste your product links again; their history starts from then.
Or put the online `DATABASE_URL` in your laptop's `.env`, and everything you check on your laptop
goes straight online.
