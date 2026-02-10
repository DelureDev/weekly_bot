import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import weekly_report as wr
from telegram.error import TimedOut

COL_TASK = "\u0417\u0430\u0434\u0430\u0447\u0430"
COL_LINK = "\u0421\u0441\u044b\u043b\u043a\u0430"
COL_STATUS = "\u0421\u0442\u0430\u0442\u0443\u0441"
COL_DATE_CLOSED = "\u0414\u0430\u0442\u0430 \u0437\u0430\u043a\u0440\u044b\u0442\u0438\u044f"

STATUS_DONE = "\u0412\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u043e"
STATUS_IN_PROGRESS = "\u0412 \u0440\u0430\u0431\u043e\u0442\u0435"


class ParseAndSanitizeTests(unittest.TestCase):
    def test_parse_int_set_ignores_invalid_entries(self) -> None:
        with patch.object(wr.logger, "warning") as warning:
            parsed = wr._parse_int_set("1, 2, x, , 3, 2, y", "ALLOWED_CHAT_IDS")

        self.assertEqual(parsed, {1, 2, 3})
        self.assertEqual(warning.call_count, 2)

    def test_safe_href_allows_http_https_and_rejects_others(self) -> None:
        self.assertEqual(
            wr._safe_href("https://example.com/path?a=1&b=2"),
            "https://example.com/path?a=1&amp;b=2",
        )
        self.assertIsNone(wr._safe_href("javascript:alert(1)"))
        self.assertIsNone(wr._safe_href("/relative/path"))

    def test_split_report_chunks_respects_limit(self) -> None:
        text = "line1\nline2\nline3"
        chunks = wr._split_report_chunks(text, limit=7)
        self.assertEqual(chunks, ["line1", "line2", "line3"])

    def test_split_report_for_delivery_keeps_section_context(self) -> None:
        report = "\n".join(
            [
                "<b>DONE</b>",
                "• task-1",
                "• task-2",
                "• task-3",
                "",
                "<b>WIP</b>",
                "• task-4",
            ]
        )
        chunks = wr._split_report_for_delivery(report, limit=24)
        self.assertEqual(chunks[0], "<b>DONE</b>\n• task-1")
        self.assertEqual(chunks[1], "<b>DONE</b>\n• task-2")
        self.assertEqual(chunks[2], "<b>DONE</b>\n• task-3")
        self.assertEqual(chunks[3], "<b>WIP</b>\n• task-4")


class ReportGenerationTests(unittest.TestCase):
    def test_generate_report_filters_rows_and_sanitizes_html(self) -> None:
        records = [
            {
                COL_TASK: "<task done>",
                COL_LINK: "https://example.com/done?a=1&b=2",
                COL_STATUS: STATUS_DONE,
                COL_DATE_CLOSED: "06.01.2026",
            },
            {
                COL_TASK: "Unsafe link",
                COL_LINK: "javascript:alert(1)",
                COL_STATUS: STATUS_DONE,
                COL_DATE_CLOSED: "07.01.2026",
            },
            {
                COL_TASK: "In progress",
                COL_LINK: "https://example.com/work",
                COL_STATUS: STATUS_IN_PROGRESS,
                COL_DATE_CLOSED: "",
            },
            {
                COL_TASK: "Invalid date",
                COL_LINK: "https://example.com/bad-date",
                COL_STATUS: STATUS_DONE,
                COL_DATE_CLOSED: "31.02.2026",
            },
            {
                COL_TASK: "Out of done range",
                COL_LINK: "https://example.com/out",
                COL_STATUS: STATUS_DONE,
                COL_DATE_CLOSED: "20.01.2026",
            },
        ]
        sheet = MagicMock()
        sheet.get_all_records.return_value = records

        with (
            patch.object(wr, "get_sheet", return_value=sheet),
            patch.object(wr, "last_week_dates", return_value=(date(2026, 1, 5), date(2026, 1, 11))),
            patch.object(wr, "current_week_dates", return_value=(date(2026, 1, 12), date(2026, 1, 18))),
            patch.object(wr, "format_date_range", side_effect=["done-range", "progress-range"]),
            patch.object(wr.logger, "warning") as warning,
        ):
            report = wr.generate_report()

        self.assertIn("<b>\u2705 \u0412\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u043e (done-range)</b>", report)
        self.assertIn(
            '<a href="https://example.com/done?a=1&amp;b=2">&lt;task done&gt;</a>',
            report,
        )
        self.assertIn("\u2022 Unsafe link", report)
        self.assertNotIn("javascript:alert(1)", report)
        self.assertIn(
            '<a href="https://example.com/work">In progress</a>',
            report,
        )
        self.assertNotIn("Out of done range", report)
        self.assertEqual(warning.call_count, 1)

    def test_generate_report_resets_cached_sheet_when_read_fails(self) -> None:
        with (
            patch.object(wr, "_SHEET", object()),
            patch.object(wr, "get_sheet", side_effect=RuntimeError("boom")),
            patch.object(wr.logger, "exception"),
        ):
            with self.assertRaises(RuntimeError):
                wr.generate_report()
            self.assertIsNone(wr._SHEET)


class AsyncHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_report_sends_intro_in_first_chunk(self) -> None:
        bot = SimpleNamespace(send_message=AsyncMock())
        application = SimpleNamespace(bot=bot)

        with (
            patch.object(wr, "INTRO_MENTIONS", "@u1 @u2"),
            patch.object(wr, "INTRO_TEXT", "intro"),
            patch.object(wr.asyncio, "to_thread", new=AsyncMock(return_value="report text")),
        ):
            await wr.send_report(-100123, application)

        self.assertEqual(bot.send_message.await_count, 1)
        first = bot.send_message.await_args_list[0].kwargs
        self.assertEqual(first["chat_id"], -100123)
        self.assertIn("@u1 @u2 intro", first["text"])
        self.assertIn("report text", first["text"])
        self.assertEqual(first["parse_mode"], wr.ParseMode.HTML)
        self.assertTrue(first["disable_web_page_preview"])

    async def test_send_report_does_not_send_messages_when_generation_fails(self) -> None:
        bot = SimpleNamespace(send_message=AsyncMock())
        application = SimpleNamespace(bot=bot)

        with patch.object(wr.asyncio, "to_thread", new=AsyncMock(side_effect=RuntimeError("boom"))):
            with self.assertRaises(RuntimeError):
                await wr.send_report(-100123, application)

        bot.send_message.assert_not_awaited()

    async def test_send_report_retries_when_timeout_happens(self) -> None:
        bot = SimpleNamespace(send_message=AsyncMock(side_effect=[TimedOut("timeout"), None]))
        application = SimpleNamespace(bot=bot)

        with (
            patch.object(wr, "INTRO_MENTIONS", "@u1"),
            patch.object(wr, "INTRO_TEXT", "intro"),
            patch.object(wr.asyncio, "to_thread", new=AsyncMock(return_value="report text")),
            patch.object(wr.asyncio, "sleep", new=AsyncMock()),
        ):
            await wr.send_report(-100123, application)

        self.assertEqual(bot.send_message.await_count, 2)

    async def test_send_report_continues_when_one_chunk_fails(self) -> None:
        bot = SimpleNamespace(
            send_message=AsyncMock(
                side_effect=[
                    None,  # first chunk ok
                    TimedOut("t1"),
                    TimedOut("t2"),
                    TimedOut("t3"),  # second chunk failed after retries
                    None,  # warning about partial send
                ]
            )
        )
        application = SimpleNamespace(bot=bot)

        with (
            patch.object(wr, "INTRO_MENTIONS", "@u1"),
            patch.object(wr, "INTRO_TEXT", "intro"),
            patch.object(wr.asyncio, "to_thread", new=AsyncMock(return_value="unused")),
            patch.object(wr, "_split_report_for_delivery", return_value=["chunk-1", "chunk-2"]),
            patch.object(wr.asyncio, "sleep", new=AsyncMock()),
        ):
            await wr.send_report(-100123, application)

        self.assertEqual(bot.send_message.await_count, 5)

    async def test_report_denies_unauthorized_chat(self) -> None:
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(
            message=message,
            effective_chat=SimpleNamespace(id=-200),
            effective_user=SimpleNamespace(id=123),
        )
        context = SimpleNamespace(application=SimpleNamespace())

        with (
            patch.object(wr, "_is_allowed_chat", return_value=False),
            patch.object(wr, "_is_allowed_user", return_value=True),
            patch.object(wr, "send_report", new=AsyncMock()),
        ):
            await wr.report(update, context)

        message.reply_text.assert_awaited_once()
        self.assertIn(
            "\u041d\u0435\u0434\u043e\u0441\u0442\u0430\u0442\u043e\u0447\u043d\u043e \u043f\u0440\u0430\u0432",
            message.reply_text.await_args.args[0],
        )

    async def test_scheduled_report_skips_invalid_chat_id(self) -> None:
        app = SimpleNamespace()

        with (
            patch.object(wr, "REPORT_CHAT_ID", "not-a-number"),
            patch.object(wr, "send_report", new=AsyncMock()) as send_report,
            patch.object(wr.logger, "error") as log_error,
        ):
            await wr.scheduled_report(app)

        send_report.assert_not_awaited()
        log_error.assert_called_once()

    async def test_scheduled_report_calls_send_report_when_chat_id_valid(self) -> None:
        app = SimpleNamespace()

        with (
            patch.object(wr, "REPORT_CHAT_ID", "-1003546739323"),
            patch.object(wr, "send_report", new=AsyncMock()) as send_report,
        ):
            await wr.scheduled_report(app)

        send_report.assert_awaited_once_with(-1003546739323, app)


if __name__ == "__main__":
    unittest.main()
