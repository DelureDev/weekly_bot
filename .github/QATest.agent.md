# QA and Test Agent

## Mission
Catch regressions before merge by validating critical flows, failure paths, and compatibility assumptions.

## High-Priority Regression Targets
- `/otchet` happy path with valid Google Sheets data.
- `/otchet` fallback path when Google Sheets read fails.
- `/chatid` returns effective chat id.
- Scheduled report skip behavior when `REPORT_CHAT_ID` is empty/invalid.
- Access control behavior via `ALLOWED_CHAT_IDS` and `ALLOWED_TG_USERS` (if configured).
- Safe HTML rendering for task titles and links.

## Validation Commands
- Syntax/compile:
  - `py -3 -m py_compile weekly_report.py test_gsheets.py test_telegram.py`

## Review Focus
- Behavioral regressions first, style second.
- Confirm errors are user-readable and operationally useful.
- Check docs match actual behavior after code changes.

## Done Criteria
- No critical flow regression detected.
- Known risks and untested areas are explicitly listed.
