import asyncio
import logging
import os
import sys
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from dotenv import load_dotenv

import database as db
import parser

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = os.getenv('ADMIN_ID')
PROXY_URL = os.getenv('PROXY_URL')

# Валидация окружения
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден в .env файле!")
if not ADMIN_ID:
    raise ValueError("❌ ADMIN_ID не найден в .env файле!")
ADMIN_ID = int(ADMIN_ID)

def format_salary(salary_dict: dict | None) -> str:
    if not salary_dict:
        return "Не указана"
    fr = salary_dict.get('from')
    to = salary_dict.get('to')
    curr = salary_dict.get('currency', 'rub')
    if fr and to:
        return f"от {fr} до {to} {curr}"
    elif fr:
        return f"от {fr} {curr}"
    elif to:
        return f"до {to} {curr}"
    return "Не указана"

# Хранилище фоновых задач для корректного завершения
background_tasks = set()

async def parsing_task(bot: Bot):
    """Бесконечный цикл парсинга вакансий."""
    while True:
        try:
            vacancies = await parser.fetch_vacancies()
            new_count = 0

            # Разворачиваем, чтобы сначала шли самые старые из новых (хронологический порядок)
            for vac in reversed(vacancies):
                vac_id = int(vac['id'])
                if not await db.vacancy_exists(vac_id):
                    # Формируем красивую карточку
                    text = (
                        f"🔥 <b><a href='{vac['url']}'>{vac['name']}</a></b>\n"
                        f"💰 <b>{vac['salary']}</b>\n\n"
                        f"🏢 <b>Компания:</b> {vac['employer']}\n"
                        f"📍 <b>Локация:</b> {vac['area']}\n\n"
                        f"💼 <b>Опыт:</b> {vac['experience']}\n"
                        f"🕒 <b>Формат:</b> {vac['work_formats']}\n"
                    )

                    try:
                        # Отправляем сообщение, отключив превью ссылки (чтобы не засорять чат огромными картинками HH)
                        await bot.send_message(
                            chat_id=ADMIN_ID, 
                            text=text, 
                            parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True 
                        )
                        await db.add_vacancy(vac_id)
                        new_count += 1
                        await asyncio.sleep(1.2)  # Защита от флуда Telegram
                    except Exception as send_err:
                        logging.error(f"❌ Ошибка отправки сообщения: {send_err}")

            if new_count > 0:
                logging.info(f"✅ Отправлено {new_count} новых вакансий.")

        except asyncio.CancelledError:
            logging.info("🛑 Задача парсинга отменена.")
            break
        except Exception as e:
            logging.error(f"💥 Критическая ошибка в цикле парсинга: {e}")

        # Пауза между проверками (5 минут = 300 секунд)
        await asyncio.sleep(300)

async def db_cleanup_task():
    """Периодическая очистка старых записей из БД."""
    while True:
        try:
            await db.clear_old_vacancies(days=7)
        except asyncio.CancelledError:
            logging.info("🛑 Задача очистки БД отменена.")
            break
        except Exception as e:
            logging.error(f"❌ Ошибка при очистке БД: {e}")
        await asyncio.sleep(86400)  # Раз в сутки

async def on_startup(bot: Bot):
    """Выполняется при запуске бота."""
    await db.init_db()

    task1 = asyncio.create_task(parsing_task(bot))
    task2 = asyncio.create_task(db_cleanup_task())
    background_tasks.update([task1, task2])

    # Автоматическое удаление завершённых задач из множества
    for t in background_tasks:
        t.add_done_callback(background_tasks.discard)

    logging.info("🚀 Бот успешно запущен. Ожидание новых вакансий...")

async def on_shutdown(bot: Bot):
    """Выполняется при остановке бота."""
    logging.info("🛑 Остановка бота и фоновых задач...")
    for task in background_tasks:
        task.cancel()
    await asyncio.gather(*background_tasks, return_exceptions=True)
    await db.close_db()
    await bot.session.close()
    logging.info("✅ Бот полностью остановлен.")

async def main():
    session = AiohttpSession(proxy=PROXY_URL) if PROXY_URL else None
    bot = Bot(token=BOT_TOKEN, session=session)
    dp = Dispatcher()

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    @dp.message(Command("start"))
    async def cmd_start(message: types.Message):
        if message.from_user.id == ADMIN_ID:
            await message.answer("🤖 Здравствуйте! Я начал мониторинг HH. Как только появится новая вакансия Junior DS/ML, я пришлю её сюда.")
        else:
            await message.answer("🔒 Извините, я работаю только со своим создателем.")

    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("👋 Бот выключен вручную.")
    except Exception as e:
        logging.critical(f"💥 Фатальная ошибка: {e}", exc_info=True)