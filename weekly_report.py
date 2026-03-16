import asyncio
import locale
import logging
import os
import socket
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from html import escape as html_escape
from threading import Lock
from typing import Optional
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo

import gspread
import httpx
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from google.oauth2.service_account import Credentials
from telegram import BotCommand, Update
from telegram.constants import ParseMode
from telegram.error import RetryAfter, TimedOut
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- Locale (best effort) ---
try:
    locale.setlocale(locale.LC_TIME, "ru_RU.UTF-8")
except locale.Error:
    try:
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
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# --- Config (ENV) ---
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
CREDS_FILE = os.getenv("CREDS_FILE", "credentials.json")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
SHEET_NAME = os.getenv("SHEET_NAME", f"Список задач ({datetime.now().year})")

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPORT_CHAT_ID = os.getenv("REPORT_CHAT_ID")  # chat id for scheduled report (optional)

INTRO_MENTIONS = os.getenv("INTRO_MENTIONS", "@DelureW @paul47789")
INTRO_TEXT = os.getenv("INTRO_TEXT", "Коллеги, подготовил еженедельный отчет")

REPORT_TIMEZONE = ZoneInfo(os.getenv("REPORT_TIMEZONE", "Europe/Moscow"))
ALLOWED_CHAT_IDS_RAW = os.getenv("ALLOWED_CHAT_IDS", "")
ALLOWED_TG_USERS_RAW = os.getenv("ALLOWED_TG_USERS", "")
REPORT_CHUNK_SIZE = 3900
SEND_RETRY_ATTEMPTS = 3
SEND_RETRY_BASE_DELAY_SEC = 1.0
TG_CONNECT_TIMEOUT_SEC = float(os.getenv("TG_CONNECT_TIMEOUT_SEC", "10"))
TG_READ_TIMEOUT_SEC = float(os.getenv("TG_READ_TIMEOUT_SEC", "60"))
TG_WRITE_TIMEOUT_SEC = float(os.getenv("TG_WRITE_TIMEOUT_SEC", "30"))
TG_POOL_TIMEOUT_SEC = float(os.getenv("TG_POOL_TIMEOUT_SEC", "10"))
TG_SEND_CONNECT_TIMEOUT_SEC = float(os.getenv("TG_SEND_CONNECT_TIMEOUT_SEC", "10"))
TG_SEND_READ_TIMEOUT_SEC = float(os.getenv("TG_SEND_READ_TIMEOUT_SEC", "20"))
TG_SEND_WRITE_TIMEOUT_SEC = float(os.getenv("TG_SEND_WRITE_TIMEOUT_SEC", "20"))
TG_SEND_POOL_TIMEOUT_SEC = float(os.getenv("TG_SEND_POOL_TIMEOUT_SEC", "10"))
TG_GET_UPDATES_READ_TIMEOUT_SEC = float(os.getenv("TG_GET_UPDATES_READ_TIMEOUT_SEC", "60"))
TG_GET_UPDATES_CONNECT_TIMEOUT_SEC = float(os.getenv("TG_GET_UPDATES_CONNECT_TIMEOUT_SEC", "10"))
TG_GET_UPDATES_WRITE_TIMEOUT_SEC = float(os.getenv("TG_GET_UPDATES_WRITE_TIMEOUT_SEC", "30"))
TG_GET_UPDATES_POOL_TIMEOUT_SEC = float(os.getenv("TG_GET_UPDATES_POOL_TIMEOUT_SEC", "10"))
NETDIAG_HOST = os.getenv("NETDIAG_HOST", "api.telegram.org")
try:
    NETDIAG_HTTP_ATTEMPTS = max(1, int(os.getenv("NETDIAG_HTTP_ATTEMPTS", "3")))
except ValueError:
    NETDIAG_HTTP_ATTEMPTS = 3
try:
    NETDIAG_TIMEOUT_SEC = max(1.0, float(os.getenv("NETDIAG_TIMEOUT_SEC", "6")))
except ValueError:
    NETDIAG_TIMEOUT_SEC = 6.0

# --- Proxy (SOCKS5) ---
_PROXY_HOST = os.getenv("PROXY_HOST", "")
_PROXY_PORT = os.getenv("PROXY_PORT", "")
_PROXY_LOGIN = os.getenv("PROXY_LOGIN", "")
_PROXY_PASS = os.getenv("PROXY_PASS", "")
PROXY_URL: Optional[str] = None
if _PROXY_HOST and _PROXY_PORT:
    if _PROXY_LOGIN and _PROXY_PASS:
        PROXY_URL = f"socks5://{quote(_PROXY_LOGIN, safe='')}:{quote(_PROXY_PASS, safe='')}@{_PROXY_HOST}:{_PROXY_PORT}"
    else:
        PROXY_URL = f"socks5://{_PROXY_HOST}:{_PROXY_PORT}"

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
        if status.lower() == "выполнено" and date_closed_dt and done_start <= date_closed_dt <= done_end:
            if link:
                safe_link = _safe_href(link)
                if safe_link:
                    done_tasks.append(f'• <a href="{safe_link}">{_h(task)}</a>')
                else:
                    done_tasks.append(f"• {_h(task)}")
            else:
                done_tasks.append(f"• {_h(task)}")

        # In progress: all tasks with status "В работе"
        elif status.lower() == "в работе":
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
    lines.append(f"<b>{_h(f'✅ Выполнено ({done_week_str})')}</b>")
    if done_tasks:
        lines.extend(done_tasks)
    else:
        lines.append("• —")

    lines.append("")
    lines.append(f"<b>{_h(f'🔄 В работе ({in_progress_week_str})')}</b>")
    if in_progress_tasks:
        lines.extend(in_progress_tasks)
    else:
        lines.append("• —")

    return "\n".join(lines)


def generate_report_threadsafe() -> str:
    with _REPORT_LOCK:
        return generate_report()


def _split_report_chunks(text: str, limit: int = REPORT_CHUNK_SIZE) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""
    for line in text.splitlines():
        candidate = line if not current else f"{current}\n{line}"
        if len(candidate) <= limit:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""

        if len(line) <= limit:
            current = line
            continue

        start = 0
        while start < len(line):
            chunks.append(line[start : start + limit])
            start += limit

    if current:
        chunks.append(current)

    return chunks or [text]


def _split_report_for_delivery(report_text: str, limit: int = REPORT_CHUNK_SIZE) -> list[str]:
    """Split report by sections, preserving section header in each chunk."""
    if len(report_text) <= limit:
        return [report_text]

    sections: list[list[str]] = []
    current_section: list[str] = []
    for line in report_text.splitlines():
        if not line.strip():
            if current_section:
                sections.append(current_section)
                current_section = []
            continue
        current_section.append(line)
    if current_section:
        sections.append(current_section)

    if not sections:
        return _split_report_chunks(report_text, limit)

    chunks: list[str] = []
    for section in sections:
        title = section[0]
        entries = section[1:] or ["• —"]
        current_lines = [title]

        for entry in entries:
            candidate = "\n".join([*current_lines, entry])
            if len(candidate) <= limit:
                current_lines.append(entry)
                continue

            if len(current_lines) > 1:
                chunks.append("\n".join(current_lines))

            titled_entry = f"{title}\n{entry}"
            if len(titled_entry) <= limit:
                current_lines = [title, entry]
                continue

            entry_room = max(1, limit - len(title) - 1)
            start = 0
            while start < len(entry):
                part = entry[start : start + entry_room]
                chunks.append(f"{title}\n{part}")
                start += entry_room
            current_lines = [title]

        if len(current_lines) > 1:
            chunks.append("\n".join(current_lines))

    return chunks or _split_report_chunks(report_text, limit)


def _format_duration_ms(seconds: float) -> str:
    return f"{seconds * 1000:.0f}ms"


async def _resolve_dns(host: str) -> tuple[list[str], list[str]]:
    def _resolve() -> tuple[list[str], list[str]]:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        a_records: set[str] = set()
        aaaa_records: set[str] = set()
        for family, *_rest, sockaddr in infos:
            ip = sockaddr[0]
            if family == socket.AF_INET:
                a_records.add(ip)
            elif family == socket.AF_INET6:
                aaaa_records.add(ip)
        return sorted(a_records), sorted(aaaa_records)

    return await asyncio.to_thread(_resolve)


async def _tcp_probe(host: str, port: int, family: int, timeout_sec: float) -> tuple[bool, str]:
    start = time.perf_counter()
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, family=family),
            timeout=timeout_sec,
        )
        elapsed = time.perf_counter() - start
        writer.close()
        await writer.wait_closed()
        return True, _format_duration_ms(elapsed)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


async def _https_probe(
    url: str, attempts: int, timeout_sec: float
) -> tuple[int, int, Optional[float], Optional[float], str]:
    ok = 0
    fail = 0
    durations: list[float] = []
    status_codes: list[str] = []

    timeout = httpx.Timeout(timeout_sec)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, proxy=PROXY_URL) as client:
        for _ in range(max(1, attempts)):
            start = time.perf_counter()
            try:
                response = await client.get(url)
                ok += 1
                durations.append(time.perf_counter() - start)
                status_codes.append(str(response.status_code))
            except Exception:
                fail += 1

    avg_duration: Optional[float] = None
    max_duration: Optional[float] = None
    if durations:
        avg_duration = sum(durations) / len(durations)
        max_duration = max(durations)
    codes = ",".join(sorted(set(status_codes))) if status_codes else "-"
    return ok, fail, avg_duration, max_duration, codes


async def build_network_diag_text(application) -> str:
    host = NETDIAG_HOST
    proxy_active = PROXY_URL is not None
    lines: list[str] = [f"🌐 Диагностика сети для {host}"]
    if proxy_active:
        lines.append(f"🔀 Прокси: {_PROXY_HOST}:{_PROXY_PORT}")

    # DNS is always a direct check; label it so when proxy is active
    try:
        a_records, aaaa_records = await _resolve_dns(host)
    except Exception:
        lines.append("❌ DNS: ошибка резолва")
        a_records = []
        aaaa_records = []
    else:
        dns_suffix = " (прямой)" if proxy_active else ""
        lines.append(f"✅ DNS A{dns_suffix}: {', '.join(a_records) if a_records else '-'}")
        aaaa_str = ', '.join(aaaa_records) if aaaa_records else '-'
        lines.append(f"{'✅' if aaaa_records else '⚠️'} DNS AAAA{dns_suffix}: {aaaa_str}")

    # TCP: probe proxy reachability when proxy is active, direct Telegram otherwise
    tcp4_ok = False
    tcp6_ok = False
    proxy_tcp_ok = False
    if proxy_active:
        try:
            proxy_port_int = int(_PROXY_PORT)
        except ValueError:
            proxy_port_int = 0
        proxy_tcp_ok, proxy_tcp_info = await _tcp_probe(
            _PROXY_HOST, proxy_port_int, socket.AF_INET, NETDIAG_TIMEOUT_SEC
        )
        lines.append(
            f"{'✅' if proxy_tcp_ok else '❌'} TCP прокси {_PROXY_HOST}:{_PROXY_PORT}: "
            f"{'OK' if proxy_tcp_ok else 'FAIL'} ({proxy_tcp_info})"
        )
    else:
        tcp4_ok, tcp4_info = await _tcp_probe(host, 443, socket.AF_INET, NETDIAG_TIMEOUT_SEC)
        lines.append(f"{'✅' if tcp4_ok else '❌'} TCP 443 IPv4: {'OK' if tcp4_ok else 'FAIL'} ({tcp4_info})")
        if aaaa_records:
            tcp6_ok, tcp6_info = await _tcp_probe(host, 443, socket.AF_INET6, NETDIAG_TIMEOUT_SEC)
            lines.append(f"{'✅' if tcp6_ok else '⚠️'} TCP 443 IPv6: {'OK' if tcp6_ok else 'FAIL'} ({tcp6_info})")
        else:
            lines.append("⚠️ TCP 443 IPv6: SKIP (нет AAAA)")

    # HTTPS and Bot API probes go through proxy when configured
    ok, fail, https_avg, https_max, https_codes = await _https_probe(
        f"https://{host}",
        NETDIAG_HTTP_ATTEMPTS,
        NETDIAG_TIMEOUT_SEC,
    )
    if https_avg is None:
        lines.append(f"❌ HTTPS {host}: ok={ok} fail={fail} codes={https_codes}")
    else:
        https_mark = "✅" if fail == 0 and https_max < 1.0 else "⚠️"
        lines.append(
            f"{https_mark} HTTPS {host}: ok={ok} fail={fail} "
            f"avg={_format_duration_ms(https_avg)} max={_format_duration_ms(https_max)} codes={https_codes}"
        )

    botapi_start = time.perf_counter()
    botapi_ok = False
    botapi_elapsed: Optional[float] = None
    try:
        await application.bot.get_me(
            connect_timeout=TG_SEND_CONNECT_TIMEOUT_SEC,
            read_timeout=TG_SEND_READ_TIMEOUT_SEC,
            write_timeout=TG_SEND_WRITE_TIMEOUT_SEC,
            pool_timeout=TG_SEND_POOL_TIMEOUT_SEC,
        )
        botapi_elapsed = time.perf_counter() - botapi_start
        botapi_ok = True
        bot_mark = "✅" if botapi_elapsed < 1.0 else "⚠️"
        lines.append(f"{bot_mark} Bot API getMe: OK ({_format_duration_ms(botapi_elapsed)})")
    except Exception as exc:
        lines.append(f"❌ Bot API getMe: FAIL ({type(exc).__name__})")

    # Summary
    tcp_ok_for_summary = proxy_tcp_ok if proxy_active else tcp4_ok
    if not tcp_ok_for_summary or ok == 0 or not botapi_ok:
        lines.append("🚨 Итог: есть критичная проблема с доступом к Telegram API.")
    elif not proxy_active and aaaa_records and not tcp6_ok:
        lines.append("⚠️ Итог: IPv4 работает, IPv6 недоступен. Возможны редкие таймауты.")
    elif fail > 0 or (https_max is not None and https_max >= 1.0) or (
        botapi_elapsed is not None and botapi_elapsed >= 1.0
    ):
        lines.append("⚠️ Итог: доступ есть, но канал нестабилен (скачки задержек).")
    else:
        lines.append("✅ Итог: доступ к Telegram API стабильный.")

    return "\n".join(lines)


async def _send_message_with_retry(bot, **kwargs) -> None:
    kwargs.setdefault("connect_timeout", TG_SEND_CONNECT_TIMEOUT_SEC)
    kwargs.setdefault("read_timeout", TG_SEND_READ_TIMEOUT_SEC)
    kwargs.setdefault("write_timeout", TG_SEND_WRITE_TIMEOUT_SEC)
    kwargs.setdefault("pool_timeout", TG_SEND_POOL_TIMEOUT_SEC)
    last_error: Optional[Exception] = None
    for attempt in range(1, SEND_RETRY_ATTEMPTS + 1):
        try:
            await bot.send_message(**kwargs)
            return
        except RetryAfter as exc:
            last_error = exc
            if attempt >= SEND_RETRY_ATTEMPTS:
                break
            delay = exc.retry_after + 0.5
            logger.warning(
                "Telegram rate limit (attempt %s/%s). Retry in %.1fs",
                attempt,
                SEND_RETRY_ATTEMPTS,
                delay,
            )
            await asyncio.sleep(delay)
        except TimedOut as exc:
            last_error = exc
            if attempt >= SEND_RETRY_ATTEMPTS:
                break
            delay = SEND_RETRY_BASE_DELAY_SEC * attempt
            logger.warning(
                "Telegram send timeout (attempt %s/%s). Retry in %.1fs",
                attempt,
                SEND_RETRY_ATTEMPTS,
                delay,
            )
            await asyncio.sleep(delay)

    if last_error is not None:
        raise last_error


async def send_report(chat_id: int, application) -> None:
    report_text = await asyncio.to_thread(generate_report_threadsafe)
    intro = f"{INTRO_MENTIONS} {INTRO_TEXT}".strip()
    chunks = _split_report_for_delivery(report_text)
    if intro:
        await _send_message_with_retry(application.bot, chat_id=chat_id, text=intro)

    sent_chunks = 0
    failed_chunks = 0

    for idx, chunk in enumerate(chunks, start=1):
        try:
            await _send_message_with_retry(
                application.bot,
                chat_id=chat_id,
                text=chunk,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            sent_chunks += 1
            if idx < len(chunks):
                await asyncio.sleep(0.35)
        except (TimedOut, RetryAfter):
            failed_chunks += 1
            logger.error(
                "Report chunk send failed after retries (%s/%s)",
                idx,
                len(chunks),
            )

    if sent_chunks == 0:
        raise TimedOut("Timed out while sending all report chunks")

    if failed_chunks > 0:
        warning_text = (
            f"⚠️ Из-за нестабильной сети не отправлено {failed_chunks} "
            f"из {len(chunks)} частей отчета."
        )
        try:
            await _send_message_with_retry(application.bot, chat_id=chat_id, text=warning_text)
        except TimedOut:
            logger.warning("Failed to deliver partial-send warning to chat %s", chat_id)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    text = (
        "👋 Привет! Я бот еженедельной отчётности.\n\n"
        "Каждый понедельник в 15:00 я автоматически отправляю отчёт о выполненных "
        "и текущих задачах на основе данных из таблицы.\n\n"
        "<b>Команды:</b>\n"
        "/otchet — сформировать и отправить отчёт прямо сейчас\n"
        "/chatid — узнать ID текущего чата\n"
        "/netdiag — диагностика подключения к Telegram API\n"
        "/help — показать это сообщение"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


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


async def netdiag(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    user_id = update.effective_user.id if update.effective_user else None
    if not _is_allowed_chat(update.effective_chat.id) or not _is_allowed_user(user_id):
        await update.message.reply_text("Недостаточно прав для выполнения команды.")
        return

    await update.message.reply_text("🔎 Запускаю сетевую диагностику...")
    try:
        diag_text = await build_network_diag_text(context.application)
        await update.message.reply_text(diag_text)
    except Exception:
        logger.exception("Network diagnostic failed")
        await update.message.reply_text("Не удалось выполнить сетевую диагностику.")


async def scheduled_reminder(application) -> None:
    if not REPORT_CHAT_ID:
        logger.warning("REPORT_CHAT_ID не задан, напоминание отключено.")
        return

    try:
        chat_id_int = int(REPORT_CHAT_ID)
    except ValueError:
        logger.error("REPORT_CHAT_ID должен быть числом, сейчас: %r", REPORT_CHAT_ID)
        return

    try:
        await _send_message_with_retry(
            application.bot,
            chat_id=chat_id_int,
            text=(
                "📋 Напоминание: обновите статусы задач в таблице до понедельника. "
                "Отчёт будет отправлен в понедельник в 15:00."
            ),
        )
    except Exception as exc:
        logger.exception("Ошибка при отправке напоминания: %s", exc)


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

    def _report_job():
        application.create_task(scheduled_report(application))

    def _reminder_job():
        application.create_task(scheduled_reminder(application))

    scheduler.add_job(
        _report_job,
        CronTrigger(day_of_week="mon", hour=15, minute=0, timezone=REPORT_TIMEZONE),
    )
    scheduler.add_job(
        _reminder_job,
        CronTrigger(day_of_week="fri", hour=16, minute=0, timezone=REPORT_TIMEZONE),
    )
    scheduler.start()
    application.bot_data["scheduler"] = scheduler
    logger.info("Scheduler started (%s, mon 15:00 report / fri 16:00 reminder)", str(REPORT_TIMEZONE))


def shutdown_scheduler(application) -> None:
    scheduler = application.bot_data.get("scheduler")
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


async def _post_init(application) -> None:
    await application.bot.set_my_commands([
        BotCommand("otchet", "Сформировать и отправить отчёт"),
        BotCommand("chatid", "Узнать ID текущего чата"),
        BotCommand("netdiag", "Диагностика подключения к Telegram API"),
        BotCommand("help", "Показать справку"),
    ])
    logger.info("BotFather commands registered")


if __name__ == "__main__":
    _ensure_configured()

    if PROXY_URL:
        # Log proxy without credentials for safety
        _proxy_log = PROXY_URL.split("@")[-1] if "@" in PROXY_URL else PROXY_URL
        logger.info("SOCKS5 proxy enabled: socks5://%s", _proxy_log)

    builder = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .connect_timeout(TG_CONNECT_TIMEOUT_SEC)
        .read_timeout(TG_READ_TIMEOUT_SEC)
        .write_timeout(TG_WRITE_TIMEOUT_SEC)
        .pool_timeout(TG_POOL_TIMEOUT_SEC)
        .get_updates_connect_timeout(TG_GET_UPDATES_CONNECT_TIMEOUT_SEC)
        .get_updates_read_timeout(TG_GET_UPDATES_READ_TIMEOUT_SEC)
        .get_updates_write_timeout(TG_GET_UPDATES_WRITE_TIMEOUT_SEC)
        .get_updates_pool_timeout(TG_GET_UPDATES_POOL_TIMEOUT_SEC)
        .post_init(_post_init)
    )
    if PROXY_URL:
        builder = builder.proxy(PROXY_URL).get_updates_proxy(PROXY_URL)
    app = builder.build()
    setup_scheduler(app)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("otchet", report))
    app.add_handler(CommandHandler("chatid", chat_id))
    app.add_handler(CommandHandler("netdiag", netdiag))

    logger.info("Бот запущен. Ожидание команд.")
    try:
        app.run_polling()
    finally:
        shutdown_scheduler(app)
