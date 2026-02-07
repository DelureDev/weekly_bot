# weekly_bot

Telegram bot that builds a weekly report from Google Sheets and posts it to Telegram.

## Requirements

- Python 3.11+
- Telegram bot token
- Google service account credentials JSON with read access to the sheet

## Install

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Environment Variables

Required:

- `BOT_TOKEN` - Telegram bot token
- `SPREADSHEET_ID` - Google Sheets document id

Optional:

- `CREDS_FILE` - path to service account JSON (default: `credentials.json`)
- `SHEET_NAME` - worksheet name (default: `Список задач (2026)`)
- `REPORT_CHAT_ID` - chat id for scheduled weekly send
- `INTRO_MENTIONS` - text prefix before report
- `INTRO_TEXT` - intro message text
- `REPORT_TIMEZONE` - IANA timezone (default: `Europe/Moscow`)
- `ALLOWED_CHAT_IDS` - comma-separated chat IDs allowed to run `/otchet`
- `ALLOWED_TG_USERS` - comma-separated user IDs allowed to run `/otchet` and `/chatid`

If `ALLOWED_CHAT_IDS` or `ALLOWED_TG_USERS` is empty, that filter is disabled.

## Run

```powershell
py -3 weekly_report.py
```

## Commands

- `/otchet` - generate and send weekly report to current chat
- `/chatid` - show current chat id

## Smoke Scripts

- `test_gsheets.py` - manual check for Google Sheets connectivity (uses env vars)
- `test_telegram.py` - manual check for Telegram send (uses env vars)

## Validation

```powershell
py -3 -m py_compile weekly_report.py test_gsheets.py test_telegram.py
```
