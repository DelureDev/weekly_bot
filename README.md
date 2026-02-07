# weekly_bot

Telegram bot that builds a weekly report from Google Sheets and posts it to Telegram.

## Features

- `/otchet` generates a weekly report from Google Sheets
- `/chatid` prints the current chat id
- Scheduled auto-send every Monday at 15:00 in `REPORT_TIMEZONE`
- Optional access restrictions via `ALLOWED_CHAT_IDS` and `ALLOWED_TG_USERS`

## Requirements

- Python 3.11+
- Telegram bot token
- Google service account JSON with read access to the target spreadsheet

## Install

Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows (PowerShell):

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

```bash
python3 weekly_report.py
```

## Validation

```bash
python3 -m py_compile weekly_report.py test_gsheets.py test_telegram.py
```

## Production (systemd)

- `ExecStart` should point to the project venv, for example:

```ini
ExecStart=/home/adminos/weekly_bot/.venv/bin/python /home/adminos/weekly_bot/weekly_report.py
```

- Ensure `CREDS_FILE` points to an existing JSON key file.
- Prefer storing secrets in `EnvironmentFile` (for example `/etc/weekly_bot.env`) with `chmod 600`, instead of inline `Environment="..."` entries in unit files.

## Agent Workflow

1. Start with `Codex.agent.md`.
2. Route to one specialized agent for implementation.
3. Run `QATest.agent.md` and `Security.agent.md` before merge.
4. Finish with `Documentation.agent.md` if behavior/config changed.

## Smoke Scripts

- `test_gsheets.py` - manual check for Google Sheets connectivity (uses env vars)
- `test_telegram.py` - manual check for Telegram send (uses env vars)
