# weekly_bot

Telegram-бот, который формирует еженедельный отчет из Google Sheets и отправляет его в Telegram.

## Возможности

- `/otchet` — формирует еженедельный отчет из Google Sheets
- `/chatid` — показывает ID текущего чата
- `/netdiag` — выводит краткую сетевую диагностику до Telegram API (DNS/TCP/HTTPS/getMe)
- Автоотправка по расписанию каждый понедельник в 15:00 в `REPORT_TIMEZONE`
- Опциональные ограничения доступа через `ALLOWED_CHAT_IDS` и `ALLOWED_TG_USERS`

## Требования

- Python 3.11+
- Токен Telegram-бота
- JSON-ключ сервисного аккаунта Google с доступом на чтение нужной таблицы

## Установка

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

## Переменные окружения

Обязательные:

- `BOT_TOKEN` — токен Telegram-бота
- `SPREADSHEET_ID` — ID документа Google Sheets

Опциональные:

- `CREDS_FILE` — путь до JSON-ключа сервисного аккаунта (по умолчанию: `credentials.json`)
- `SHEET_NAME` — имя листа (по умолчанию: `Список задач (2026)`)
- `REPORT_CHAT_ID` — ID чата для отправки отчета по расписанию
- `INTRO_MENTIONS` — префикс перед отчетом
- `INTRO_TEXT` — текст вступительного сообщения
- `REPORT_TIMEZONE` — IANA-таймзона (по умолчанию: `Europe/Moscow`)
- `ALLOWED_CHAT_IDS` — список разрешенных chat ID через запятую для `/otchet`
- `ALLOWED_TG_USERS` — список разрешенных user ID через запятую для `/otchet`, `/chatid` и `/netdiag`
- `NETDIAG_HOST` — хост для `/netdiag` (по умолчанию: `api.telegram.org`)
- `NETDIAG_HTTP_ATTEMPTS` — количество HTTPS-проверок в `/netdiag` (по умолчанию: `3`)
- `NETDIAG_TIMEOUT_SEC` — таймаут проверок `/netdiag` в секундах (по умолчанию: `6`)

Если `ALLOWED_CHAT_IDS` или `ALLOWED_TG_USERS` пусты, соответствующее ограничение отключено.

## Запуск

```bash
python3 weekly_report.py
```

## Валидация

```bash
python3 -m py_compile weekly_report.py test_gsheets.py test_telegram.py
```

## Прод (systemd)

- В `ExecStart` должен быть путь к Python в virtualenv проекта, например:

```ini
ExecStart=/home/adminos/weekly_bot/.venv/bin/python /home/adminos/weekly_bot/weekly_report.py
```

- Убедитесь, что `CREDS_FILE` указывает на существующий JSON-ключ.
- Секреты лучше хранить через `EnvironmentFile` (например, `/etc/weekly_bot.env`) с правами `chmod 600`, а не inline через `Environment="..."` в unit-файле.

## Workflow агентов

1. Начните с `Codex.agent.md`.
2. Передайте реализацию одному специализированному агенту.
3. Перед merge выполните проверки через `QATest.agent.md` и `Security.agent.md`.
4. Завершите проходом `Documentation.agent.md`, если менялось поведение или конфигурация.

## Smoke-скрипты

- `test_gsheets.py` — ручная проверка подключения к Google Sheets (использует env)
- `test_telegram.py` — ручная проверка отправки в Telegram (использует env)

