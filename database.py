import aiosqlite
import logging
from datetime import datetime, timedelta

DB_NAME = 'bot_database.db'
db_conn: aiosqlite.Connection | None = None

async def init_db():
    """Инициализирует БД и создаёт таблицу, если её нет."""
    global db_conn
    try:
        db_conn = await aiosqlite.connect(DB_NAME)
        await db_conn.execute('''
            CREATE TABLE IF NOT EXISTS vacancies (
                id INTEGER PRIMARY KEY,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db_conn.commit()
        logging.info("✅ База данных успешно инициализирована.")
    except Exception as e:
        logging.error(f"❌ Ошибка инициализации БД: {e}")
        raise

async def close_db():
    """Корректно закрывает соединение с БД."""
    global db_conn
    if db_conn:
        await db_conn.close()
        logging.info("🔒 Соединение с БД закрыто.")

async def vacancy_exists(vacancy_id: int) -> bool:
    """Проверяет, есть ли вакансия в базе."""
    if not db_conn:
        raise RuntimeError("БД не инициализирована. Вызовите init_db() сначала.")
    async with db_conn.execute('SELECT 1 FROM vacancies WHERE id = ?', (vacancy_id,)) as cursor:
        return await cursor.fetchone() is not None

async def add_vacancy(vacancy_id: int):
    """Добавляет новую вакансию в базу."""
    if not db_conn:
        raise RuntimeError("БД не инициализирована.")
    await db_conn.execute('INSERT OR IGNORE INTO vacancies (id) VALUES (?)', (vacancy_id,))
    await db_conn.commit()

async def clear_old_vacancies(days: int = 7):
    """Удаляет вакансии старше указанного количества дней."""
    if not db_conn:
        raise RuntimeError("БД не инициализирована.")
    try:
        cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
        cursor = await db_conn.execute('DELETE FROM vacancies WHERE added_at <= ?', (cutoff_date,))
        await db_conn.commit()
        logging.info(f"🧹 Очистка БД завершена. Удалено записей: {cursor.rowcount}")
    except Exception as e:
        logging.error(f"❌ Ошибка при очистке БД: {e}")