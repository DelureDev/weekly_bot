import asyncio
from telegram import Bot

BOT_TOKEN = "8323649979:AAGrCjN8ZkRzymcKV1S2U_L16cNf9GpAWC4"
CHAT_ID = -5119304406

async def main():
	bot = Bot(token=BOT_TOKEN)
	await bot.send_message(chat_id=CHAT_ID, text="Тест: бот на Python жив 👋")

asyncio.run(main())
