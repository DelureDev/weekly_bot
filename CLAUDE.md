# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Run the bot:**
```bash
python3 weekly_report.py
```

**Validate syntax (no runtime deps needed):**
```bash
python3 -m py_compile weekly_report.py test_gsheets.py test_telegram.py
```

**Run unit tests:**
```bash
python3 -m unittest test_weekly_report.py
```

**Run a single test:**
```bash
python3 -m unittest test_weekly_report.ParseAndSanitizeTests.test_safe_href_allows_http_https_and_rejects_others
```

**Smoke-test Google Sheets connection:**
```bash
SPREADSHEET_ID=... CREDS_FILE=credentials.json python3 test_gsheets.py
```

**Smoke-test Telegram send:**
```bash
BOT_TOKEN=... CHAT_ID=... python3 test_telegram.py
```

## Architecture

The entire bot lives in a single file: `weekly_report.py`. There is no package structure.

**Data flow:**
1. `ApplicationBuilder` (python-telegram-bot) creates the bot with all timeout settings from env vars.
2. `BackgroundScheduler` (APScheduler) runs in a separate thread, fires coroutines via `application.create_task()` on a cron schedule: Monday 15:00 (report) and Friday 16:00 (reminder).
3. On `/otchet` or scheduled trigger → `send_report()` → `generate_report_threadsafe()` (thread-safe via `_REPORT_LOCK`) → `generate_report()` reads Google Sheets via `gspread`.
4. The worksheet is cached in `_SHEET` (guarded by `_SHEET_LOCK`); on read failure, the cache is reset to `None` so the next call re-authenticates.
5. Report text is HTML-escaped (`_h`, `_h_attr`, `_safe_href`) and split into ≤3900-char chunks by `_split_report_for_delivery`, which preserves section headers in each chunk. Each chunk is sent with retry logic in `_send_message_with_retry` (handles `RetryAfter` and `TimedOut`).

**Key invariants to preserve:**
- `BOT_TOKEN` and `SPREADSHEET_ID` are mandatory — checked at startup by `_ensure_configured()`.
- All user-facing HTML output must go through `_h()` / `_h_attr()` / `_safe_href()`.
- `/otchet` must reply with a readable error message on failure (never silently fail).
- Scheduled report must not run when `REPORT_CHAT_ID` is missing or non-numeric.
- The worksheet cache (`_SHEET`) must be reset on any read failure so the next call retries auth.

**Access control:**
- `ALLOWED_CHAT_IDS` gates `/otchet` and `/netdiag` by chat.
- `ALLOWED_TG_USERS` gates `/otchet`, `/chatid`, and `/netdiag` by user.
- Empty env var = no restriction for that dimension.

**Network diagnostics (`/netdiag`):**
- `build_network_diag_text()` probes DNS, TCP (IPv4/IPv6 on port 443), HTTPS, and Bot API `getMe` — all using configurable timeouts from env.

## Required env vars

- `BOT_TOKEN` — Telegram bot token
- `SPREADSHEET_ID` — Google Sheets document ID
- `CREDS_FILE` — path to Google service account JSON (default: `credentials.json`)

See README.md for the full list of optional env vars and their defaults.

## Agent workflow

Agent files live in `.github/`. Entry point for any non-trivial change is `Codex.agent.md` → route to a specialized agent. Before merging: `QATest.agent.md` and `Security.agent.md`. After behavior/config changes: `Documentation.agent.md`.
