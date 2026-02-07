# Codex Agent (Orchestrator)

## Mission
Act as the default development agent for this repository. Route work to specialized agents when helpful, and keep changes safe, minimal, and production-ready.

## Repository Context
- Stack: Python 3.11+, `python-telegram-bot`, `gspread`, `google-auth`, `APScheduler`.
- Purpose: Telegram bot that builds a weekly report from Google Sheets and posts it to Telegram.
- Main module: `weekly_report.py`.

## Default Workflow
1. Read the request and identify impacted modules.
2. Choose the right specialized agent instruction file from `.github`.
3. Implement the smallest safe change that solves the request.
4. Validate with `py -3 -m py_compile weekly_report.py test_gsheets.py test_telegram.py`.
5. Update docs when behavior/config/commands change.

## Non-Negotiable Guardrails
- Never commit secrets or `.env` data.
- Keep command behavior stable for `/otchet` and `/chatid`.
- Preserve report sending invariants:
  - `BOT_TOKEN` and `SPREADSHEET_ID` are required,
  - if Google Sheets read fails, user receives a clear error,
  - scheduled send must not run without valid `REPORT_CHAT_ID`.
- Keep HTML output safe for Telegram `ParseMode.HTML`.

## Agent Routing
- Architecture or task decomposition: `TechLead.agent.md`
- Core Python implementation/refactor: `BackendDeveloper.agent.md`
- Telegram dialog/state UX: `TelegramConversation.agent.md`
- Verification and regression checks: `QATest.agent.md`
- Security hardening and secret safety: `Security.agent.md`
- Deploy/runtime/config operations: `DevOpsRelease.agent.md`
- Documentation updates: `Documentation.agent.md`
