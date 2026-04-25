import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.client.session.aiohttp import AiohttpSession
from dotenv import load_dotenv
import os

load_dotenv()
PROXY_URL = os.getenv('PROXY_URL')
BOT_TOKEN = os.getenv('BOT_TOKEN')

async def main():
    bot = Bot(
        token=BOT_TOKEN,
        session=AiohttpSession(
            proxy=PROXY_URL
        )
    )

    dp = Dispatcher()

    @dp.message(Command("start"))
    async def cmd_start(message: types.Message):
        await message.answer("Hi")

    print("Бот запущен через прокси...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот выключен")