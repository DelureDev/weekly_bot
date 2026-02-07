import asyncio
import os

from telegram import Bot


async def main() -> None:
    token = os.getenv("BOT_TOKEN")
    chat_id_raw = os.getenv("CHAT_ID")
    if not token or not chat_id_raw:
        raise SystemExit("Set BOT_TOKEN and CHAT_ID before running this smoke script.")

    chat_id = int(chat_id_raw)
    bot = Bot(token=token)
    await bot.send_message(chat_id=chat_id, text="Test: bot is reachable.")


if __name__ == "__main__":
    asyncio.run(main())
