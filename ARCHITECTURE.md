# Unibliss — Architecture Audit & Refactoring Plan

**Date:** 2026-10-05
**Scope:** full repository audit — 5 Python modules (1,819 LOC), 10 Jinja templates (2,067 LOC), 11 SQLite tables, 20 HTTP routes, Alembic history, docs, and tooling.
**Method:** static read of every source file, live inspection of `unibliss_erp.db` (`sqlite3` pragmas + `sqlite_master`), cross-referencing of template contracts against route context, and git history review.

> **Bottom line:** this is not a scaling problem — it is a *correctness* and *coupling* problem. The stack (FastAPI + SQLite + Jinja) is the right choice and should be kept. The problems are that business logic lives in HTTP handlers, the domain is welded to the ORM and the filesystem, every report re-derives every number from scratch in Python, thresholds and currency formatting have leaked into templates as literals, and there is no test suite to catch any of it. Fix those five things and the app becomes auditable, which is the only thing a financial tool actually needs.

---

## Table of Contents

1. [Current shape](#1-current-shape)
2. [Findings](#2-findings)
   - [S1 — Critical](#s1--critical-live-money-and-security-bugs)
   - [S2 — High](#s2--high)
   - [S3 — Medium](#s3--medium)
   - [S4 — Low / cleanup](#s4--low--cleanup)
3. [Root causes](#3-root-causes)
4. [Target architecture](#4-target-architecture)
5. [Principles](#5-principles)
6. [Non-goals](#6-non-goals)
7. [Phased migration plan](#7-phased-migration-plan)
8. [Open decisions for the owner](#8-open-decisions-for-the-owner)
9. [Appendix A — Formula conflicts](#appendix-a--formula-conflicts)
10. [Appendix B — Dead code inventory](#appendix-b--dead-code-inventory)
11. [Appendix C — Schema gaps](#appendix-c--schema-gaps)

---

## 1. Current shape

| Asset | Size | Notes |
|---|---|---|
| `main.py` | 607 L, 20 routes, 24 `async def`, 12 `db.query` | God module: routes, middleware, exception handling, migration runner, config file I/O, upload staging, business logic, pandas |
| `data_processor.py` | 579 L, 15 `db.query`, 6 references to `calculate_monthly_summary` | Financial math bound to `Session` + ORM + pandas; full-table Python aggregation |
| `processor.py` | 402 L, 4 `db_session.query` | Ingestion: parse logic inline, destructive scoped deletes, no validation layer |
| `models.py` | 151 L, 10 tables | `Float` money, no FKs, 2 dead tables |
| `database.py` | 23 L | Global engine, no pragmas, CWD-relative path |
| `auditor.py` | 43 L | **Dead — `audit_health()` is never called** |
| `archive/api_connector.py` | 220 L | **Dead — never imported** |
| `templates/` | 2,067 L, 10 files | **Zero** `{% extends %}` / `{% include %}` / `{% macro %}` |
| `static/` | empty | Mounted at `main.py:46`, zero assets, zero `url_for` |
| Tests / CI / lint config | — | **None.** `.pytest_cache/` exists but nothing is committed; `.github/` absent; no `pyproject.toml` |

**Live database (verified 2026-10-05):**

```
alembic_version = a123b456c78d (head)
PRAGMA journal_mode = delete        <-- no WAL
PRAGMA foreign_keys  = 0            <-- FKs not enforced even if declared

row counts:  financial_events 76   ads_metrics 903   business_metrics 20
             operating_expenses 1  sync_logs 1       cogs_history 0
             inventory 0  iqo_log 0  kanban_cards 0  promotions 0
```

`cogs_history`, `inventory`, `iqo_log`, `kanban_cards` and `promotions` are **empty** — meaning COGS per-unit cost is currently 0 for every SKU, so every margin, ROI and "cashflow healthy" figure rendered today is structurally understated. This alone makes the golden-file test suite (P1) urgent.

---

## 2. Findings

### S1 — Critical (live money and security bugs)

#### F1 · `POST /settings` silently deletes `gst_rate`
`SettingsUpdate` (`main.py:28-33`) declares five thresholds and **no `gst_rate`**. `update_settings` writes `settings.model_dump()` wholesale (`main.py:475-479`). Any settings save therefore **removes the GST rate from `config.json`**, after which `data_processor.py:121` reads `.get('gst_rate', 0)` → GST liability becomes `0.0` → **Net Income is silently overstated**. No log, no error, no visible symptom other than a wrong profit number.

**Fix:** one `Settings` model that includes every key; the repository validates the full schema on write and rejects unknown/incomplete input. **Never `model_dump()` into a shared config file.**

#### F2 · Three different Net Income formulas exist in one codebase
| Location | Formula |
|---|---|
| `data_processor.py:128-138` (actual) | `Sales − COGS − Ads − Refunds − FBA − Selling − Promotions − OpEx − GST` |
| `reconciliation.html:143-166` (displayed + documented) | `Sales + Reimbursements − FBA − Selling − Refunds − Promotions` |
| `docs.html:317-329` | `Sales + Reimbursements − … − Other Amazon Fees` |
| `index.html:93` (Gross Margin tooltip) | `(Sales + Reimbursements − Refunds − COGS − FBA − Selling − Promotions − Other Fees) / Sales` |
| `FINANCIAL_FORMULA_AUDIT.md:78-79` | asserts Reimbursements and Other Fees **are** included, marked ✅ |

The code omits `Reimbursements` and `Other_Amazon_Fees`. `Other_Amazon_Fees` is computed at `data_processor.py:50,64` and then **used by nothing and rendered nowhere**. The discrepancy is currently masked because `config.json:7 gst_rate = 0.0` and `promotions.html`/`reconciliation.html` are the only surfaces that show the term.

**Fix:** one authoritative formula in `domain/pnl.py`; the template receives the computed value and never recomputes; regenerate the formula docs from the code.

#### F3 · Mixed-source P&L — revenue basis ≠ cost basis
`summary['Sales']` is first accumulated from `FinancialEvent.product_sales` (`data_processor.py:40`), then **overwritten** by `BusinessMetric.ordered_product_sales` if that is non-zero (`:107-108`). `Units_Sold` is likewise switched (`:108-109`). But fees, refunds and reimbursements remain sourced from `FinancialEvent`, and the two tables use *different date semantics* — `posted_date` vs `report_month`.

Consequences:
- Revenue comes from the business report while costs come from settlements → they describe different populations.
- `Return_Pct` (`:141-142`) divides a refund count from `FinancialEvent` by a unit count from `BusinessMetric`.
- The period filter silently changes meaning depending on which tables happen to be populated.
- The override is conditional on `> 0`, so behaviour changes as data is loaded — non-deterministic across months.

**Fix:** an explicit, documented revenue-source policy in `domain/ledger.py` (recommend: settlements are the accounting system of record; business report is a *traffic* source only). One source per number.

#### F4 · COGS versioning is decorative
`models.COGS` carries `effective_start_date` / `effective_end_date`, but both consumers read **only the currently-active row**: `data_processor.py:67-68` and `:221-222`. There is no `effective_start_date <= period_end` filter anywhere. **Adding a new COGS row silently restates every historical month.**

**Fix:** resolve the cost *as of the event date* in `domain/ledger.py`, and add a golden test that proves a COGS change does not alter a closed period.

#### F5 · Two different sources for ad spend
`sync_ads_report` writes spend into `AdsMetric.spend` (`processor.py:288`) **and** into an `OperatingExpense(category='Amazon Ads')` row (`processor.py:291-304`).
- `calculate_monthly_summary` reads `Ads_Cost` from `AdsMetric` (`:85-91`) and deliberately excludes the `Amazon Ads` expense row (`:81`).
- `calculate_sku_metrics` allocates SKU-level ad cost from the `OperatingExpense` rows (`:252-265`).

Two reports on the same page therefore use different ad costs for the same period.

**Fix:** `AdsMetric` is the single source; delete the `OperatingExpense` write, or make it a derived read-model.

#### F6 · Money is `Float`
Every monetary column in `models.py` is `Float`. Binary floating point in a P&L that gates pricing decisions, ad budgets and Seller Support claims. `0.1 + 0.2` drift is guaranteed, and `Float` columns cannot be summed correctly in SQL.

**Fix:** `Numeric(14, 2)` in storage, `Decimal` in the domain, one documented rounding policy in `core/money.py`.

#### F7 · Parse failures become silent zeros
`utils.clean_numeric` returns `0.0` on any unparseable value (`utils.py:13`). A mangled `₹` cell becomes a legitimate-looking zero rather than a rejected row. It also does `str(val)` on floats, so a value like `1234.5600000000001` round-trips as a 16-digit string.

**Fix:** return `Decimal | None`; the ingest use case collects and surfaces every failure with row number, column name and raw value. Never coerce to zero.

#### F8 · Ingestion is destructive, not idempotent
`processor.py:93-98` deletes every `FinancialEvent` in a date window **before** inserting the new file's rows. Uploading an overlapping file destroys any manual correction and can leave the ledger in a mixed state across two files. There is no natural key and no uniqueness constraint.

**Fix:** parse → validate into a staging structure → upsert on a natural key (`settlement_id`, `order_id`, `line_no`, `event_type`). Deletion becomes *supersede*, never blind `DELETE`.

#### F9 · No authentication, no authorization, no CSRF
There is no auth anywhere in `app`. Unprotected destructive/critical endpoints:

| Endpoint | Impact |
|---|---|
| `GET /admin/backup` (`main.py:324-329`) | streams the entire financial database |
| `POST /admin/reset-db` (`main.py:379-391`) | deletes all rows from 9 tables |
| `POST /settings` (`main.py:475-479`) | rewrites business configuration |
| `POST /admin/*`, `/promotions/*` | writes |

The only control is `Start_Dashboard.bat:24` binding to `127.0.0.1` — a launcher convention, not an application invariant. There is **no CSRF protection and no `SessionMiddleware`**, so any web page the operator visits can POST a plain HTML form to `http://127.0.0.1:8000/admin/reset-db`. No preflight, no CORS requirement. The sole guard is a client-side `confirm()` (`admin.html:216-234`), which is trivially bypassed. **Localhost does not protect you.**

**Fix:** authentication + per-router authorization, CSRF tokens, and destructive actions gated behind a typed confirmation + an audit record + an automatic pre-backup.

---

### S2 — High

#### F10 · Reflected XSS in the upload error path
`audit.html:32` renders `{{ error | safe }}`. The value is built at `main.py:602-605` as `"<br>".join(errors)`, where each error is `f"{kind}: {e}"` from parsing the **user-supplied uploaded file**. A filename or cell value containing `<img src=x onerror=…>` executes in the operator's session. This is the only place autoescaping is disabled on untrusted data.

**Fix:** pass a `list[str]`, render the separator as markup, keep the values escaped.

#### F11 · Internal errors leaked to the browser
The global handler renders `str(exc)` in `error.html:16` — potentially SQL statements and absolute file paths.

#### F12 · Unbounded uploads, shared staging directory
`main.py:511-516`: `await uf.read()` loads the whole file into memory with no size cap; the path is `uploads/<original filename>`, so two concurrent uploads of `settlement.csv` collide; a crash mid-upload leaves files behind; no content-type validation.

**Fix:** streaming copy with a hard byte limit into a unique temp directory, validated extension, and guaranteed cleanup in a `finally`.

#### F13 · The "initial" migration is not a migration
`alembic/versions/9793b44f0aa7_initial.py:24-33` does `import models` and then `create`s whatever tables exist in *today's* model definitions. Consequences:
- Replaying it today produces a **different schema** than it did on 2026-05-30. Revisions must be immutable.
- It silently creates any missing table, so `alembic_version` already reads `head` while the actual schema can drift — **drift becomes invisible**. A future column added to `models.py` will never reach an existing database.

#### F14 · Migrations run implicitly at every boot
`main.py:35-39` runs `alembic upgrade head` inside `lifespan`. A migration error prevents the app from starting; it is unsafe past a single worker; and there is no way to see the schema version the app is running.

**Fix:** migrations run as an explicit CLI step. Startup only *verifies* the schema is at head and refuses to serve otherwise. Expose the version on `/health`.

#### F15 · Schema has no integrity
Verified on the live DB: `foreign_keys = 0`, `journal_mode = delete`. Additionally:
- **`posted_date` is not indexed** — and it is the filter on *every* financial query.
- No composite index on `(report_month, sku)`, `(date, sku)`, `(is_deferred, posted_date)`.
- No `CHECK` constraints on event type, no `NOT NULL` on financial columns, no FKs between `financial_events.sku` → `inventory.sku`.

#### F16 · `config.json` is opened at five call sites with five ad-hoc loaders
`main.py:311`, `main.py:368`, `main.py:470`, `data_processor.py:119`, `data_processor.py:499`, `auditor.py:4`. No schema, no validation, no cache, non-atomic write (`main.py:376`). If the write is interrupted, every reader falls into `except: pass` and silently uses `threshold = 100.0, gst_rate = 0` — **wrong numbers with no warning**. `auditor.py:11-18` would additionally `KeyError` on a partial file.

#### F17 · Every route blocks the event loop
All 20 routes are `async def`, and all of them perform synchronous SQLAlchemy queries, pandas work, and file I/O. One request serializes the entire server.

**Fix:** DB-backed routes become plain `def` (FastAPI runs them in a threadpool); heavy ingestion moves to a background job.

#### F18 · Aggregation in Python; ~6-8 full table scans per page load
`calculate_monthly_summary` does `query.all()` (`:32`) then loops in Python. `calculate_sku_metrics` materialises a dict per event and `groupby`s in pandas (`:190-217`). `get_comparison_data` calls `calculate_monthly_summary` **4×** (`:290-322`), each a fresh full scan.

- `GET /` → 5 full scans + 1 more for `daily_data` (`main.py:112-116`) = **6**
- `GET /sku-insights` → 4 × `calculate_sku_metrics` + 4 × `calculate_monthly_summary` = **8**, and the `comparison` payload it computes at `main.py:203` is **never referenced by the template**.

#### F19 · N+1 query in disbursement deep dive
`get_disbursement_deep_dive` runs 2 queries **per transfer** (`data_processor.py:545-558`). With 76 events today it is invisible; at 10 settlements/month × 3 years it is not.

#### F20 · Financial arithmetic inside Jinja
- `reconciliation.html:166` recomputes a Net-Income-like subtotal that **disagrees with the implementation** (adds `Reimbursements`, omits GST). The block above it (`:143-152`) does the same, so the page's own verification table does not add up to the number it verifies whenever `gst_rate > 0`.
- `promotions.html:79` computes promotion ROI inline with a divide-by-zero guard — the only promotion metric in the system, and it lives in a view.
- `index.html:161-176` encodes the metric taxonomy into `{% if key in [...] %}` chains, repeated 3× for current/MoM/YoY.

#### F21 · Seventeen hardcoded thresholds in templates, duplicating `config.json`
`reconciliation.html:101,102,105` hardcode `< 100` **while ignoring the `recon.reconciliation_threshold` it was handed** (`data_processor.py:522`). Result: a green "Payout Verified" badge (`:36`, config-driven) can render next to a red discrepancy panel (`:101-105`, hardcoded) on the same screen. Other duplications: ₹200 profit/unit (`sku_insights.html:109,112` vs `config.min_net_profit_per_unit`), TACOS 10/15, return 3/5, ACOS 20/35, ROAS 3/1.5, margins, ROI. Margin ladders are internally inconsistent (`index.html:95` uses 30/15; `sku_insights.html:107` uses 20/10). `target_unit_session_pct` appears in **no** template at all.

#### F22 · Zero tests
No `tests/` directory, no `pyproject.toml`, no pytest configuration. `.pytest_cache/v/cache/` exists but no test file is committed. For a system whose output is a P&L, this is the top single risk — and it is why F1-F5 have survived multiple "formula audit" passes.

#### F23 · CWD-relative paths
`alembic.ini` (`main.py:37`), `templates`, `static`, `uploads`, `config.json` (`main.py:311,368,470,499`), and `DB_FILE` (`database.py:6`) all resolve against the **current working directory**. Launching uvicorn from anywhere other than the repo root either fails to start or silently reads/writes the wrong config.

---

### S3 — Medium

#### F24 · No template inheritance at all
Zero `{% extends %}` / `{% include %}` / `{% macro %}` across 2,067 lines.
- **72 duplicated nav lines** — a byte-identical 9-line `<nav>` in 8 templates; 7 of them carry a mis-indented `/help` link (the fingerprint of a scripted text insert that never reformatted).
- 24 duplicated date-form lines; ~42 duplicated metric-card lines; ~60 duplicated FAQ lines; 78 lines of inline JS with no shared file.

#### F25 · Templates are coupled to the ORM
`promotions.html` and `admin.html` read SQLAlchemy attributes directly. Renaming a column breaks them silently. `main.py:304` passes an **un-materialized `Query`**, so a database round-trip fires *during rendering*.

#### F26 · Duplicated date math
`_safe_date_prev_month` and `_safe_date_prev_year` exist **verbatim in two places**: `main.py:156-178` and `data_processor.py:298-322`. A third copy would be a third bug.

#### F27 · Dead code and dead schema
- `auditor.py` — `audit_health()` never called.
- `archive/api_connector.py` — never imported; the only consumer of the SP-API variables in `.env.example`.
- `iqo_log`, `kanban_cards` tables — models exist, zero routes, zero templates; referenced only in `reset_db`.
- `templates/audit_report.html` — 274 lines, **no route renders it**; its `missing_keys`, `metrics.gross_sales`, `metrics.ad_spend`, `metrics.net_payout` exist in **no** `.py` file. 190 lines of dead CSS holding the project's only CSS variables.
- `config.min_net_profit_per_unit` — read by nothing (only `config.json:5` and `main.py:32`).
- `GET/POST /settings` — **no template posts to it**, so every threshold is hand-edited JSON. That is *why* F21 exists.
- `/promotions` — a fully built page with add/delete forms that **no nav bar links to**.

#### F28 · Frontend has no build and no local assets
`static/` is mounted (`main.py:46`) and empty; zero `url_for` calls anywhere. Tailwind is loaded from `cdn.tailwindcss.com` in 9 templates (runtime JIT, no SRI, no version pin) — and `text-{{ color }}-600` at 9 sites only works *because* of runtime JIT; it silently breaks the moment Tailwind is compiled. Plotly is loaded in only 2 templates, so it re-downloads on every navigation between pages. No CSP is possible. `₹` is hardcoded in 78 template lines, and U+2212 `−` is mixed with ASCII `-` on the same page (`reconciliation.html:71` vs `:195`).

#### F29 · Real seller data is committed to git
`.gitignore:68` lists `*.xlsx`, but a 797 KB `bulk-a1bq5iy116wsd6-20260421-20260521-1779389154792.xlsx` is **tracked** (committed before the rule was added). `config.json` is also tracked.

#### F30 · Backup can be corrupt
`GET /admin/backup` (`main.py:326-328`) serves the raw `.db` file via `FileResponse` while the application may be writing to it.

#### F31 · No health endpoint, no startup integrity check
Nothing reports readiness, schema version, or database integrity. `Start_Dashboard.bat:28-31` polls `GET /` in a loop — which runs six full table scans per attempt.

---

### S4 — Low / cleanup

- **Docs have rotted.** `MASTER_DOCUMENT.md` documents `type` and `refunds` columns that were renamed/dropped, "14 routes" (now 20), "9 templates" (now 10), `main.py` "519 lines" (607), and a `GET /docs` route that is actually `GET /help` (`main.py:295-297`). `FINANCIAL_FORMULA_AUDIT.md` marks formulas ✅ that the code does not implement. `docs.html:16,33,463,469` still say **"KABA Brands"**; everything else says "Unibliss".
- **`requirements.txt` mixes runtime and dev tooling** (`ruff`), has no lockfile or hashes, and `requests` is runtime-unused.
- **f-string logging** (`main.py:58,69`) instead of lazy `%`-args; no structured fields.
- **No pagination.** `db.query(...).all()` on promotions and inventory.
- **`/admin` runs two queries the template never reads** (`main.py:305-307`).
- **Ambiguous date parsing.** `_parse_dates` (`main.py:82-90`) tries `%d/%m/%Y` before `%m/%d/%Y`, so `05/06/2026` silently becomes 5 June even for a US-formatted input.
- **`sync_returns_xml` result is discarded** (`main.py:579`) — the Returns upload is a no-op; `Total_Returns` derives only from Refund events.
- **`report_month` is trusted over file content** (`processor.py:271,358`) — the upload form's month label wins, so mislabeling files data under the wrong month, where the next upload deletes it.
- **`upload_manual` commits five times** (`main.py:526,539,554,566,595`), contradicting commit `ad4aeb7` "K-010: wrap multi-file upload in single DB transaction".
- **`import json` inside functions** at `data_processor.py:118,497` and `main.py:310,367`; `pandas` imported into `utils.py` solely for `pd.isna`.

---

## 3. Root causes

Five smells produce essentially every finding above.

| # | Root cause | Findings it explains |
|---|---|---|
| **RC1** | **Business logic lives in HTTP handlers**, so it is unreachable from tests and gets copied into templates | F2, F17, F20, F21, F26, F28 |
| **RC2** | **No layer boundary** — domain, ORM, HTTP and filesystem are mutually entangled in 5 flat root modules | F5, F8, F16, F18, F23, F25, F26 |
| **RC3** | **Numbers are recomputed per request in Python instead of once in the database**, so every report is a full scan and every view can disagree with every other | F2, F3, F4, F5, F18, F19, F20 |
| **RC4** | **Configuration, thresholds and formatting have no home**, so they leak into templates as literals and drift | F1, F16, F21, F27, F28 |
| **RC5** | **No safety net** — no tests, no CI, no migration discipline, no auth | F1-F5, F13, F14, F22 |

---

## 4. Target architecture

```
kareena/
├── app/
│   ├── main.py                     # ASGI assembly ONLY: middleware, routers, lifespan
│   ├── core/                       # no fastapi · no sqlalchemy · no pandas · no jinja
│   │   ├── config.py               # pydantic-settings; Settings + ThresholdPolicy
│   │   ├── money.py                # Decimal, rounding policy, currency formatting
│   │   ├── periods.py              # unambiguous parsing + WoW/MoM/YoY windows
│   │   ├── paths.py                # absolute, CWD-independent resolution
│   │   ├── logging.py              # structured logs, request-id ContextVar
│   │   └── errors.py               # domain exception hierarchy + safe messages
│   ├── domain/                     # PURE — imports nothing from any framework
│   │   ├── events.py               # FinancialEvent value object + EventType enum
│   │   ├── ledger.py               # revenue/cost recognition rules, COGS as-of resolution
│   │   ├── pnl.py                  # P&L, margins, unit economics
│   │   ├── comparison.py           # period windows + deltas
│   │   ├── reconciliation.py       # expected-payout engine
│   │   ├── ads.py                  # ACOS / TACOS / ROAS / CVR
│   │   └── policy.py               # threshold evaluation → {status, flags}
│   ├── application/                # USE CASES — orchestrate domain + ports, own the UoW
│   │   ├── ingest_settlement.py    ingest_business.py  ingest_ads.py  ingest_returns.py
│   │   └── queries.py              # dashboard · sku · advertising · reconciliation read models
│   ├── ports/                      # Protocols (interfaces)
│   │   ├── repositories.py         file_store.py        settings_repo.py
│   ├── infrastructure/             # ADAPTERS — implement the ports
│   │   ├── db/                     base.py · session.py · pragmas.py
│   │   ├── orm/                    models.py · repositories.py
│   │   ├── files/                  local_store.py
│   │   └── settings/               json_settings_repo.py   (atomic + schema-validated)
│   └── interfaces/http/
│       ├── routers/                dashboard · sku · advertising · reconciliation
│       │                           promotions · admin · audit · settings · health
│       ├── schemas.py              # pydantic request models
│       ├── viewmodels.py           # template DTOs: MetricCard, ComparisonRow, Reconciliation
│       └── deps.py                 # auth · csrf · pagination · settings injection
├── templates/
│   ├── base.html                   + partials/ + macros/
├── static/                         css/app.css · js/*.js (locally built & vendored)
├── alembic/versions/               # immutable, explicit DDL — never imports models
├── tests/
│   ├── unit/                       # domain — pure, no DB, milliseconds
│   ├── integration/                # repositories against a temp SQLite DB
│   └── golden/                     # frozen fixture → frozen expected P&L
├── pyproject.toml                  # deps + ruff + pytest config in one place
└── docs/                           ARCHITECTURE.md · FORMULAS.md · OPERATIONS.md
```

### Layer responsibilities and the dependency rule

```
interfaces/http  ──►  application  ──►  domain  ──►  core
       │                  │              │
       └──────────────────┴──────────────┴──►  ports  ◄──  infrastructure
                                                  (implements ports)
```

- **`domain/` imports nothing.** No FastAPI, no SQLAlchemy, no pandas, no Jinja, no filesystem, no config file. It takes value objects and returns value objects. This is what makes the financial rules testable in milliseconds and reviewable by a human who does not write Python.
- **`application/`** owns the transaction boundary (unit of work), orchestrates a domain calculation over repository ports, and converts domain failures into typed outcomes. It knows nothing about HTTP.
- **`infrastructure/`** implements the ports. Swapping SQLite for Postgres means writing one adapter.
- **`interfaces/http/`** parses requests, calls exactly one use case, and renders a **view model**. It contains no formulas and no thresholds.
- **`core/`** holds cross-cutting primitives with no outward dependencies.

**Enforcement:** an architecture test (`tests/unit/test_architecture.py`) that walks the import graph via `ast` and fails if `domain/` or `core/` imports any forbidden module. This is the only way the boundary survives six months of ordinary work.

---

## 5. Principles

Each principle is written to be falsifiable — there is a test or a lint rule that proves it is being upheld.

1. **One calculation, one place.** No financial formula and no threshold ever appears in a template. Every displayed number is produced by `domain/` and delivered as a typed view model carrying its value, unit, pre-formatted string and threshold status.
2. **Dependencies point inward.** `domain` and `core` import nothing external. Enforced by an AST import-graph test.
3. **Ports and adapters at every edge.** HTTP, SQLAlchemy, the filesystem and configuration are all swappable adapters. The domain is testable with no database.
4. **Money is never a float.** `Numeric(14,2)` in storage, `Decimal` in the domain, one documented rounding policy, one currency constant, one number-formatting filter.
5. **Ingestion is idempotent and non-destructive by construction.** Parse → validate into a staging structure → upsert on a natural key. Deletion means *supersede*, never a blind `DELETE` over a date range. Parse failures are loud and carry row, column and raw value.
6. **Migrations are immutable artifacts.** Explicit DDL frozen in time. A revision never imports live models. Migrations run as an explicit CLI step; startup only *verifies* the schema is at head.
7. **Configuration is typed, validated, loaded once, and injected.** No `open('config.json')` inside a computation. Atomic writes (temp file + `os.replace`), schema-validated on read and write, cached, and passed into use cases as a `Settings` object. A missing or invalid key fails loudly.
8. **Blocking work never runs on the event loop.** DB-backed routes are plain `def`; ingestion runs as a background job. One blocking request must not stall the server.
9. **Aggregate in the database, not in Python.** SUM / GROUP BY / period joins are pushed into SQL, with pre-aggregated monthly rollups where needed. No `query.all()` → loop → `groupby` on a request path.
10. **Views receive DTOs, never ORM rows.** No lazy load during rendering. A column rename can never break a template.
11. **Templates render; they do not compute.** One `base.html`, partials for repeated structures, a `metric_card` macro, and a formatting filter fed by Python.
12. **Correlated, structured logging.** Lazy `%`-args, a request-id `ContextVar`, no secrets, no raw SQL. The browser sees a safe message and a request id; the traceback lives in the log.
13. **Security baseline.** Authentication, per-router authorization, CSRF tokens, size-limited and validated uploads into unique staging directories, security headers, and destructive actions gated behind a typed confirmation plus an audit record plus an automatic pre-backup.
14. **A golden-file suite is mandatory.** A frozen fixture dataset with expected P&L, SKU profitability, reconciliation delta and ad metrics. Any formula change breaks a test. This is the highest-value investment in the entire plan.
15. **Quality gates in CI.** ruff, pytest, `alembic check` for drift, and a smoke test that boots the app against a temporary SQLite database.
16. **Explicit non-goals, written down.** See §6. Boring technology is a deliberate choice.

---

## 6. Non-goals

These are recorded so they are not re-litigated. The system is a single-user, single-machine, self-hosted tool. Its problems are coupling and correctness, **not** scale.

- **No microservices.** One process, one SQLite file, one deployable.
- **No Redis, Celery, message queues, or a job broker.** Background work is a thread and a status row.
- **No PostgreSQL migration** unless a real requirement appears. SQLite with WAL, foreign keys and proper indexes serves one user indefinitely.
- **No frontend framework, SPA, or build toolchain beyond Tailwind.** Server-rendered Jinja is the right fit and keeps the deployment self-contained.
- **No API-first rewrite.** There is no second consumer; the HTTP layer stays HTML-first.
- **No abstraction for its own sake.** A repository interface earns its place only where a second implementation or a test double is real.

---

## 7. Phased migration plan

Each phase is independently shippable and leaves the app working.

### P0 — Stop the bleeding · ~1 day

Fix the live money and security bugs with minimal structural change.

- Fix the `gst_rate` wipe (F1) — single complete `Settings` model.
- Reconcile the Net Income formula across code, templates and docs (F2); surface `GST_Cost` and `Other_Amazon_Fees` on the dashboard.
- Add authentication + CSRF; gate `/admin/*` (F9).
- Cap upload size; stream to a unique temp dir; guarantee cleanup (F12).
- Remove `| safe` from the error path (F10); stop rendering `str(exc)` (F11).
- `POST /admin/reset-db` → typed confirmation + automatic backup; `/admin/backup` → SQLite backup API (F30).
- `git rm --cached` the tracked `.xlsx` (F29).
- Resolve all paths to absolute `Path(__file__).parent`-based constants (F23).

**Acceptance:** changing any setting on the `/settings` page preserves `gst_rate`; Net Income on `/` matches the formula printed on `/reconciliation` for the same period; a cross-site POST to `/admin/reset-db` is rejected; the number rendered for Net Income on every page is identical.

---

### P1 — Test harness + golden files · ~2 days

Lock current behaviour **before** any refactor. Without this, P3 is a blind rewrite.

- `pyproject.toml` with ruff + pytest configuration; `requirements-dev.txt`.
- `tests/golden/` — a frozen fixture dataset with expected P&L, per-SKU profitability, reconciliation delta and ad metrics, asserted to the paisa.
- Unit tests for the pure functions that already exist in `data_processor.py` (wrapping them as-is, no refactor).
- CI workflow: ruff → pytest → `alembic check`.

**Acceptance:** CI is green on `main` before any refactor. The golden suite **fails loudly on today's COGS-empty database state**, which is the point — it makes the F-catalog visible rather than latent.

---

### P2 — Foundations · ~2 days

Everything later depends on this phase.

- `core/`: `config`, `money`, `periods`, `paths`, `logging`, `errors`.
- Typed `Settings` loaded once, validated, cached, injected. Atomic writes.
- `Numeric(14,2)` migration + `Decimal` domain arithmetic + documented rounding policy.
- Rewrite the Alembic history: explicit DDL, drop the live-model import, add the missing columns/indexes as real revisions.
- SQLite pragmas: WAL, `foreign_keys=ON`, `busy_timeout`.
- Move migration execution out of `lifespan` into an explicit CLI; startup verifies head.

**Acceptance:** a fresh database built purely from migrations matches the live schema exactly (`alembic check` clean). `alembic current` is visible on `/health`.

---

### P3 — Extract the domain · ~3-4 days

The core win. Moves all financial math into pure, tested functions.

- Move every calculation out of `data_processor.py` into `domain/` as pure functions over value objects.
- Resolve the open accounting decisions explicitly and test each one: `Reimbursements` in/out of Net Income; treatment of `Other_Amazon_Fees`; COGS effective-dating; single ad-cost source; the authoritative revenue source (F3, F4, F5).
- Delete `auditor.py`, `archive/`, the dead tables, and `templates/audit_report.html`.
- Delete the duplicated helpers from `main.py`.

**Acceptance:** `tests/unit/` covers `domain/` with no database. `grep -n "db.query" app/domain/` returns nothing. `app/domain/` passes the import-graph test.

> **Expect the displayed numbers to change.** Fixing F3/F4/F5 changes historical P&L — correctly. That change must be reviewed by the operator before it ships, with the diff explained (see §8, D1).

---

### P4 — Repositories + SQL aggregation · ~3 days

- Port protocols; implement SQLAlchemy adapters.
- Push SUM / GROUP BY / period joins into SQL; add monthly rollup tables where justified.
- Introduce `viewmodels.py`; stop passing ORM rows to templates (F25).
- Fix the N+1 deep dive (F19); delete `sku-insights`' unused comparison payload; add pagination.

**Acceptance:** page-load query counts are constant with respect to data volume. `/sku-insights` issues ≤3 queries. No database round-trip occurs during rendering (asserted in an integration test).

---

### P5 — HTTP layer · ~2 days

- Split `main.py` into routers + use cases; target file ≤120 LOC.
- DB-backed routes become plain `def` (F17).
- One unit-of-work/transaction boundary per request; ingestions become single-transaction (fixes the `ad4aeb7` regression).
- Pydantic schemas for every request body.
- Add `/health` (readiness, schema version, database integrity).

**Acceptance:** no route handler contains arithmetic. No `open()` outside `infrastructure/`. Concurrent requests are served in parallel.

---

### P6 — Frontend · ~2-3 days

- `base.html` + partials + a `metric_card` macro + a number/currency filter; delete all Jinja arithmetic and hardcoded thresholds (F20, F21, F24).
- Build Tailwind locally into `static/`; vendor Plotly; add security headers and a CSP (F28).
- Wire the `/settings` UI so thresholds are editable in the app.
- Decide: ship `/promotions` with a nav link, or delete it.

**Acceptance:** `grep -rn "{% set\|{{.*\*.*}}\|>= [0-9]\{2,\}" templates/` returns nothing but data display. All 17 hardcoded thresholds are gone and resolve from `config.json`. `static/` is non-empty and every asset is served locally.

---

### P7 — Ingestion hardening + docs · ~2 days

- Staging-then-upsert; loud parse errors with row/column context (F7, F8).
- `report_month` derived from file content, validated against the form label (F-misc).
- Persist the returns result (F-misc).
- Regenerate `MASTER_DOCUMENT.md` and `FORMULAS.md` from the code; add a doc-drift check.

**Acceptance:** re-uploading the same file twice produces identical database state (idempotency test). A corrupt cell produces a reported error, not a silent zero.

---

## 8. Open decisions for the owner

These change visible numbers or product scope and cannot be decided from the code.

| ID | Decision | Why it matters |
|---|---|---|
| **D1** | Does **Net Income** include `Reimbursements`? | `data_processor.py` says no; every template and doc says yes. This is a real accounting choice, not a bug to be papered over. |
| **D2** | Is `Other_Amazon_Fees` a P&L line or informational-only? | Currently computed, used by nothing, rendered nowhere, and documented as a Net Income term. |
| **D3** | Which table is the **revenue system of record** — settlements or business reports? | F3. Determines whether monthly P&L is restated when a business report is uploaded. |
| **D4** | Should historical periods restate when COGS changes, or be frozen at month close? | F4. Today they silently restate. This needs a month-close concept, or an explicit "recost" action. |
| **D5** | GST: is `gst_rate` a percentage of sales, and should it appear as a cost or a liability? | Currently a cost netted into Net Income (`:124-137`). Affects every profit number. |
| **D6** | Accept that P3 changes previously-reported numbers? | Required to fix D1-D4. Needs sign-off plus an explanation to the operator. |
| **D7** | Ship `/promotions` (nav link + validation) or delete it? | Currently an orphan route with a working page and no entry point. |
| **D8** | Ship the IQO framework and Kanban (tables exist), or drop the tables? | `MASTER_DOCUMENT.md` advertises IQO as a headline feature; there is no route or template for it. |
| **D9** | Single-user local auth, or no auth + OS-level protection only? | F9 must be closed either way. Affects UX effort. |
| **D10** | Is the tracked `.xlsx` real customer data that must be purged from history? | F29. Needs `git filter-repo`, not just `rm --cached`. |

---

## Appendix A — Formula conflicts

Every row is a place where two or more parts of the system disagree. **All must be resolved before P3.**

| Quantity | Implementation | Conflicting statements |
|---|---|---|
| **Net Income** | `data_processor.py:128-138` — excludes Reimbursements, Other_Amazon_Fees; subtracts GST | `reconciliation.html:143-166`; `docs.html:317-329`; `FINANCIAL_FORMULA_AUDIT.md:78` |
| **Gross Margin** | `data_processor.py:160` — `Sales − COGS − Refunds − FBA − Selling − Promotions` | `index.html:93` tooltip adds Reimbursements and Other Fees |
| **Sales** | `data_processor.py:40` then overwritten at `:107-108` | `get_reconciliation_check:479-482` treats it differently again |
| **Ads cost** | `data_processor.py:85-91` from `AdsMetric` | `data_processor.py:252-265` from `OperatingExpense` |
| **COGS** | `data_processor.py:67-68, 221-222` — active row only | `models.COGS` defines effective dating that is never applied |
| **Reconciliation tolerance** | `data_processor.py:497-501` from config | `reconciliation.html:101,102,105` hardcode `100`; badge at `:36` uses config |
| **Return rate** | `data_processor.py:141-142` | numerator from `FinancialEvent`, denominator from `BusinessMetric` (F3) |
| **Reconciliation threshold display** | `recon.reconciliation_threshold` supplied (`data_processor.py:522`) | never referenced by the template |

## Appendix B — Dead code inventory

| Item | Evidence |
|---|---|
| `auditor.py` (43 L) | `audit_health()` never called |
| `archive/api_connector.py` (220 L) | never imported; only consumer of `.env.example` credentials |
| `iqo_log`, `kanban_cards` tables | models exist; zero routes; zero templates; only listed in `reset_db` |
| `templates/audit_report.html` (274 L) | no route renders it; `missing_keys`, `metrics.gross_sales`, `metrics.ad_spend`, `metrics.net_payout` exist in no `.py` |
| `config.min_net_profit_per_unit` | read by nothing; templates hardcode ₹200 |
| `GET/POST /settings` | no template posts to it |
| `static/` mount (`main.py:46`) | mounted, directory empty |
| `templates.env.globals["datetime"]` (`main.py:48`) | also passed per-render at `:320` |
| `summary['Revenue_Per_Unit']`, `summary['Disbursements']`, `ads['total_units']` | computed, never rendered |

## Appendix C — Schema gaps

Current `models.py` versus what a financial ledger needs:

| Gap | Fix |
|---|---|
| `Float` for all money | `Numeric(14,2)`; `Decimal` in domain |
| No `CHECK` on `event_type` | `CHECK (event_type IN (...))` |
| `posted_date` unindexed despite filtering on it everywhere | index; composite `(is_deferred, posted_date)` |
| No unique natural key on `financial_events` | unique on `(settlement_id, order_id, line_no, event_type)` |
| No FK `financial_events.sku → inventory.sku` | declare FK (deferred delete for history) |
| Nullable financial columns | `NOT NULL DEFAULT 0` |
| `report_month` not validated against file content | derive from content; reject mismatch |
| No `Decimal`/rounding column semantics | documented rounding policy + tests |
| `iqo_log`, `kanban_cards` unused | ship or drop (D8) |
| `PRAGMA foreign_keys=0`, `journal_mode=delete` | enable both via connection event |
| No integrity check on startup | `PRAGMA integrity_check` in `/health` |