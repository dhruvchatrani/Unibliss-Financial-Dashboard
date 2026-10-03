# Unibliss Financial Dashboard — Windows User Manual

**Start here if you just want to get the dashboard running on your Windows computer.**

This guide walks you through: what the app is → what you need → how to start it → how to use it → and what to do if something goes wrong.

---

## 1. What Is This?

The **Unibliss Financial Dashboard** is a small web app that runs entirely on **your own computer** (offline). You upload your Amazon Seller Central reports and it shows you:

- Income, expenses, and net profit for the month
- Per-SKU profitability (which products actually make money)
- Advertising performance (ACOS, ROAS, spend vs. sales)
- Payout reconciliation (does Amazon's deposit match what it should be?)
- Month-on-month and year-on-year comparisons

Your financial data **never leaves your machine**. Everything is stored in a local database file on your computer.

---

## 2. What You Need Before Starting

| Item | Requirement |
|---|---|
| **Windows** | Windows 10 or Windows 11 |
| **Python** | Version **3.10 or higher** (see Step 1 below) |
| **Internet** | Only needed on the **very first launch** (to download dependencies). After that, it works fully offline. |
| **The app files** | The `unibliss` project folder (see Step 2 below) |
| **Your Amazon reports** | Downloaded from Seller Central (Settlement CSV is required; others optional) |

> 💡 **No account, no login, no cloud service.** There is nothing to sign up for.

---

## 3. Step 1 — Install Python (Do This Once)

1. Go to **https://www.python.org/downloads/**
2. Click the big **Download Python 3.1x** button.
3. Run the downloaded installer.
4. ⚠️ **CRITICAL:** On the very first screen of the installer, tick the checkbox:
   > **"Add Python to PATH"**
   
   If you skip this, the app will not start and you'll get an error saying `'python' is not recognized`.
5. Click **Install Now** and wait for it to finish.
6. *(Optional but recommended)* Verify: press `Windows Key + R`, type `cmd`, press Enter, then type:
   ```
   python --version
   ```
   You should see something like `Python 3.13.x`. If you see a version number, you're good. If you see an error, Python is not on PATH — re-run the installer and tick the checkbox this time.

---

## 4. Step 2 — Get the App Files

**Option A — Download a ZIP (easiest):**
1. Open the project page on GitHub.
2. Click the green **<> Code** button → **Download ZIP**.
3. Extract the ZIP to a folder you'll remember, e.g. `C:\Users\YourName\Documents\unibliss`.

**Option B — Git clone (if you use Git):**
```
git clone https://github.com/your-username/unibliss.git
```

When you're done, you should see a file named **`Start_Dashboard.bat`** inside the folder.

> ⚠️ **Right-click → Extract All** when unzipping. Do **not** run the app from inside the ZIP file.

---

## 5. Step 3 — First Launch (Do This Once)

1. Open the `unibliss` folder in File Explorer.
2. **Double-click `Start_Dashboard.bat`.**

A **black terminal window** will open with a blue title bar. Wait for it — the first launch does these things automatically:

1. **Creates a virtual environment** (`venv` folder) — takes a few seconds.
2. **Installs dependencies** from `requirements.txt` — this is the slow part and can take **1–5 minutes**. Be patient. You'll see lots of text scrolling.
3. **Starts the dashboard server.**
4. **Opens your browser** at **http://127.0.0.1:8000** automatically.

> 🟦 **IMPORTANT: Do NOT close the black window.** That window *is* the app. Closing it stops the dashboard. Keep it open in the background while you work.

### What you should see

- The black window ends with: *"Dashboard is running. You can now use your browser."*
- Your browser opens on the **Unibliss dashboard** (the main overview page with sales, net income, and chart sections).

If the browser opened but the page looks broken or empty, refresh the page once.

---

## 6. Step 4 — Starting the App on Later Days

From now on, it's the same every time:

1. Double-click **`Start_Dashboard.bat`**.
2. The setup step is **skipped** (it knows `venv` already exists), so it starts in a few seconds.
3. The browser opens on the dashboard.

---

## 7. Using the Dashboard (Quick Tour)

The app is now running in your browser. It has several sections reachable from the top navigation bar:

| Page | What it does |
|---|---|
| **Dashboard** (`/`) | Overall summary: sales, net income, COGS, ads cost, refunds, period comparisons |
| **Monthly Audit** (`/audit`) | Where you **upload** your monthly Amazon reports |
| **Advertising** (`/advertising`) | Ad spend, ACOS, ROAS, search terms |
| **Reconciliation** (`/reconciliation`) | Expected payout vs. actual Amazon deposit |
| **SKU Insights** (`/sku-insights`) | Per-product profitability and cashflow health |
| **Promotions** (`/promotions`) | Coupon / deal tracker |
| **IQO Log** (`/iqo`) | Experiment tracking (one change at a time) |
| **Board** (`/board`) | Action/accountability board |
| **SOP / Docs** (`/docs`) | Step-by-step monthly review procedure |
| **Admin** (`/admin`) | Inventory, COGS, expenses, GST rate, backup, reset |

### Your monthly routine in 2 minutes

1. Go to **Monthly Audit**, pick the month, upload your **Settlement CSV** (required) plus any other reports you have, and click **Upload & Sync**.
2. Review the numbers on the **Dashboard**.
3. Run through the 8-step checklist under **SOP / Docs**.
4. When you're done for the month, close the black terminal window to shut everything down.

---

## 8. Shutting Down

- **When you're done, close the black terminal window** (or press `Ctrl + C` inside it).
- That's it — everything is saved automatically in the local database.
- If the window ever gets closed by accident, just double-click `Start_Dashboard.bat` again and you'll be right back where you left off.

---

## 9. Troubleshooting

| Problem | Likely cause | Fix |
|---|---|---|
| **`'python' is not recognized as an internal or external command`** | Python not added to PATH | Re-run the Python installer and tick **"Add Python to PATH"**. Then close and reopen the terminal/bat. |
| **First launch takes forever / looks stuck** | Downloading dependencies the first time | Leave it. First install can take 1–5 minutes. Only worry if nothing changes for 10+ minutes. |
| **`pip install` errors / dependency download fails** | No internet, or a temporary network issue | Check internet connection and try again. Everything is pinned to known-good versions in `requirements.txt`. |
| **Browser doesn't open automatically** | Rare browser-blocking quirk | Manually open your browser and go to **http://127.0.0.1:8000** |
| **Page won't load / "can't reach this page"** | The server didn't fully start, or the window was closed | Close the black window, double-click `Start_Dashboard.bat` again, and wait for the "Dashboard is running" message. |
| **"Address already in use"** when starting | Something else is using port 8000 | Close other programs (e.g., another instance of the dashboard) and restart the bat. |
| **Windows SmartScreen / security warning** | The `.bat` file was downloaded from the internet | Click **More info → Run anyway**. This is normal for unsigned local scripts; the app runs fully offline and doesn't touch the internet. |
| **A blank/error page inside the dashboard** | Usually a temporary glitch or stale page | Refresh the page. If it persists, restart the app as above. |
| **I closed the window and now nothing works** | The server died with the window | Double-click `Start_Dashboard.bat` again. Nothing is lost. |
| **The app looks funny in the terminal (extra characters)** | Terminal font/encoding mismatch | Ignore it — the terminal text is cosmetic. The dashboard itself (in the browser) is unaffected. |

### What does NOT need troubleshooting

- **No firewall permission** is needed — the app only listens on `127.0.0.1` (your own machine), so Windows will not prompt you.
- **No `.env` setup** — the Amazon API keys in `.env.example` are unused by the dashboard; you do not need to touch them.

---

## 10. Where Your Data Lives & Backups

All your data is stored **locally** in the project folder:

| Item | Location |
|---|---|
| **Your database** (all uploaded financial data) | `unibliss_erp.db` |
| **Config / alert thresholds** | `config.json` |
| **Temporary uploads** | `uploads\` folder |

**Backup tip (recommended, monthly):** copy the whole `unibliss` folder — or at least `unibliss_erp.db` and `config.json` — to another drive or a cloud folder. To restore, replace the files and start the app again.

**Reset safely:** the **Admin → reset database** option clears uploaded records. Use it only if you intentionally want to start fresh — there is no undo.

---

## 11. Getting Help

| Doc | What you'll find |
|---|---|
| `README.md` | Project overview and installation notes |
| `user_sop.md` | The full 8-step monthly review procedure |
| `MASTER_DOCUMENT.md` | Technical details, architecture, and formula reference |
| This file | Everyday, plain-English usage without any technical background |

---

*Last updated: September 2026 — Windows 10/11, Python 3.10+, single-file launcher (`Start_Dashboard.bat`).*