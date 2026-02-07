import asyncio
import logging
import os
import sys
from datetime import date, datetime, timedelta
from html import escape as html_escape
from threading import Lock
from typing import Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import locale

# --- Locale (best effort) ---
try:
    locale.setlocale(locale.LC_TIME, "ru_RU.UTF-8")
except locale.Error:
    try:
        import subprocess

        subprocess.run(["locale-gen", "ru_RU.UTF-8"], check=False)
        locale.setlocale(locale.LC_TIME, "ru_RU.UTF-8")
    except Exception:
        locale.setlocale(locale.LC_TIME, "C")

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("weekly_report")

# --- Config (ENV) ---
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
CREDS_FILE = os.getenv("CREDS_FILE", "credentials.json")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
SHEET_NAME = os.getenv("SHEET_NAME", "Список задач (2026)")

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPORT_CHAT_ID = os.getenv("REPORT_CHAT_ID")  # chat id for scheduled report (optional)

INTRO_MENTIONS = os.getenv("INTRO_MENTIONS", "@DelureW @paul47789")
INTRO_TEXT = os.getenv("INTRO_TEXT", "Коллеги, подготовил еженедельный отчет")

REPORT_TIMEZONE = ZoneInfo(os.getenv("REPORT_TIMEZONE", "Europe/Moscow"))
ALLOWED_CHAT_IDS_RAW = os.getenv("ALLOWED_CHAT_IDS", "")
ALLOWED_TG_USERS_RAW = os.getenv("ALLOWED_TG_USERS", "")

# Cached worksheet (auth/open happens once; if fails, cache resets)
_SHEET = None
_SHEET_LOCK = Lock()
_REPORT_LOCK = Lock()


def _h(text: str) -> str:
    """Escape text for HTML body."""
    return html_escape(text or "", quote=False)


def _h_attr(text: str) -> str:
    """Escape text for HTML attributes."""
    return html_escape(text or "", quote=True)


def _parse_int_set(raw: str, name: str) -> set[int]:
    values: set[int] = set()
    for chunk in (raw or "").split(","):
        item = chunk.strip()
        if not item:
            continue
        try:
            values.add(int(item))
        except ValueError:
            logger.warning("Invalid %s entry ignored: %r", name, item)
    return values


ALLOWED_CHAT_IDS = _parse_int_set(ALLOWED_CHAT_IDS_RAW, "ALLOWED_CHAT_IDS")
ALLOWED_TG_USERS = _parse_int_set(ALLOWED_TG_USERS_RAW, "ALLOWED_TG_USERS")


def _safe_href(url: str) -> Optional[str]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return None
    if not parsed.netloc:
        return None
    return _h_attr(url)


def _is_allowed_chat(chat_id: int) -> bool:
    if not ALLOWED_CHAT_IDS:
        return True
    return chat_id in ALLOWED_CHAT_IDS


def _is_allowed_user(user_id: Optional[int]) -> bool:
    if not ALLOWED_TG_USERS:
        return True
    if user_id is None:
        return False
    return user_id in ALLOWED_TG_USERS


def _ensure_configured() -> None:
    missing = []
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if not SPREADSHEET_ID:
        missing.append("SPREADSHEET_ID")
    if missing:
        message = f"Missing required env vars: {', '.join(missing)}"
        logger.error(message)
        raise RuntimeError(message)


def get_sheet():
    """Return cached worksheet object."""
    global _SHEET
    if _SHEET is not None:
        return _SHEET

    with _SHEET_LOCK:
        if _SHEET is not None:
            return _SHEET
        creds = Credentials.from_service_account_file(CREDS_FILE, scopes=SCOPES)
        gc = gspread.authorize(creds)
        _SHEET = gc.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
    return _SHEET


def last_week_dates(today: date) -> tuple[date, date]:
    """Previous week: Mon-Sun."""
    last_monday = today - timedelta(days=today.weekday() + 7)
    last_sunday = last_monday + timedelta(days=6)
    return last_monday, last_sunday


def current_week_dates(today: date) -> tuple[date, date]:
    """Current week: Mon-Sun."""
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)
    return start, end


def format_date_range(start: date, end: date) -> str:
    if start.month == end.month:
        return f"{start.day}-{end.day} {start.strftime('%B').lower()}"
    return f"{start.day} {start.strftime('%B').lower()} - {end.day} {end.strftime('%B').lower()}"


def generate_report() -> str:
    """Build report text. Reads Google Sheets each time (/otchet & scheduled)."""
    done_tasks: list[str] = []
    in_progress_tasks: list[str] = []

    today = datetime.now(REPORT_TIMEZONE).date()
    done_start, done_end = last_week_dates(today)
    in_progress_start, in_progress_end = current_week_dates(today)

    global _SHEET
    try:
        sheet = get_sheet()
        records = sheet.get_all_records()
    except Exception as exc:
        with _SHEET_LOCK:
            _SHEET = None
        logger.exception("Google Sheets read failed: %s", exc)
        raise

    for row in records:
        task = str(row.get("Задача", "")).strip()
        link = str(row.get("Ссылка", "")).strip()
        status = str(row.get("Статус", "")).strip()
        date_closed = str(row.get("Дата закрытия", "")).strip()

        if not task:
            continue

        date_closed_dt: date | None = None
        if date_closed:
            try:
                date_closed_dt = datetime.strptime(date_closed, "%d.%m.%Y").date()
            except ValueError:
                logger.warning("Некорректная дата закрытия: %s", date_closed)

        # Done: previous week
        if status == "Выполнено" and date_closed_dt and done_start <= date_closed_dt <= done_end:
            if link:
                safe_link = _safe_href(link)
                if safe_link:
                    done_tasks.append(f'• <a href="{safe_link}">{_h(task)}</a>')
                else:
                    done_tasks.append(f"• {_h(task)}")
            else:
                done_tasks.append(f"• {_h(task)}")

        # In progress: all tasks with status "В работе"
        elif status == "В работе":
            if link:
                safe_link = _safe_href(link)
                if safe_link:
                    in_progress_tasks.append(f'• <a href="{safe_link}">{_h(task)}</a>')
                else:
                    in_progress_tasks.append(f"• {_h(task)}")
            else:
                in_progress_tasks.append(f"• {_h(task)}")

    done_week_str = format_date_range(done_start, done_end)
    in_progress_week_str = format_date_range(in_progress_start, in_progress_end)

    lines: list[str] = []
    lines.append(f"<b>{_h('Выполнено за ' + done_week_str)}</b>")
    lines.append("")

    if done_tasks:
        lines.extend(done_tasks)
    else:
        lines.append(_h("Нет выполненных задач."))

    lines.append("")
    lines.append(f"<b>{_h('В работе ' + in_progress_week_str + ':')}</b>")

    if in_progress_tasks:
        lines.extend(in_progress_tasks)
    else:
        lines.append(_h("Нет задач в работе."))

    return "\n".join(lines)


def generate_report_threadsafe() -> str:
    with _REPORT_LOCK:
        return generate_report()


async def send_report(chat_id: int, application) -> None:
    report_text = await asyncio.to_thread(generate_report_threadsafe)
    intro = f"{INTRO_MENTIONS} {INTRO_TEXT}".strip()
    await application.bot.send_message(chat_id=chat_id, text=intro)

    await application.bot.send_message(
        chat_id=chat_id,
        text=report_text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    user_id = update.effective_user.id if update.effective_user else None
    if not _is_allowed_chat(update.effective_chat.id) or not _is_allowed_user(user_id):
        await update.message.reply_text("Недостаточно прав для выполнения команды.")
        return
    try:
        await send_report(update.effective_chat.id, context.application)
    except Exception:
        logger.exception("Ошибка при формировании отчета")
        await update.message.reply_text("Не удалось сформировать отчет. Проверьте логи сервиса.")


async def chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        user_id = update.effective_user.id if update.effective_user else None
        if not _is_allowed_user(user_id):
            await update.message.reply_text("Недостаточно прав для выполнения команды.")
            return
        await update.message.reply_text(f"Chat ID: {update.effective_chat.id}")


async def scheduled_report(application) -> None:
    if not REPORT_CHAT_ID:
        logger.warning("REPORT_CHAT_ID не задан, авто-отправка отключена.")
        return

    try:
        chat_id_int = int(REPORT_CHAT_ID)
    except ValueError:
        logger.error("REPORT_CHAT_ID должен быть числом (например -100...), сейчас: %r", REPORT_CHAT_ID)
        return

    try:
        await send_report(chat_id_int, application)
    except Exception as exc:
        logger.exception("Ошибка при авто-отправке отчета: %s", exc)


def setup_scheduler(application) -> None:
    """
    BackgroundScheduler не требует asyncio event loop.
    Он работает в отдельном потоке и запускает coroutine через application.create_task().
    """
    scheduler = BackgroundScheduler(timezone=REPORT_TIMEZONE)

    def _job():
        application.create_task(scheduled_report(application))

    scheduler.add_job(
        _job,
        CronTrigger(day_of_week="mon", hour=15, minute=0, timezone=REPORT_TIMEZONE),
    )
    scheduler.start()
    application.bot_data["scheduler"] = scheduler
    logger.info("Scheduler started (%s, mon 15:00)", str(REPORT_TIMEZONE))


def shutdown_scheduler(application) -> None:
    scheduler = application.bot_data.get("scheduler")
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    _ensure_configured()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    setup_scheduler(app)

    app.add_handler(CommandHandler("otchet", report))
    app.add_handler(CommandHandler("chatid", chat_id))

    logger.info("Бот запущен. Ожидание команды /otchet")
    try:
        app.run_polling()
    finally:
        shutdown_scheduler(app)
