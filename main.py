"""
Головний файл бота — точка входу.
Оновлено: recovery-перевірка при старті, логування шляху до бази.
"""
import asyncio
import logging
import threading
import os

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from config import BOT_TOKEN, DATABASE_PATH
from database import init_db
from scheduler import init_scheduler, stop_scheduler, recovery_check
from handlers.start import router as start_router
from handlers.course import router as course_router
from handlers import admin as admin_handlers  # Адмін-команди

# Import health server for Railway
from health_server import start_health_server

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def main():
    """Запуск бота."""
    logger.info(f"🚀 Запуск бота...")
    logger.info(f"📂 Шлях до бази даних: {DATABASE_PATH}")
    logger.info(f"📂 Чи існує база: {os.path.exists(DATABASE_PATH)}")

    # Start health server in a separate thread
    logger.info("Запуск health server для Railway...")
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()

    logger.info("Ініціалізація бази даних...")
    await init_db()

    logger.info("Запуск планувальника...")
    init_scheduler()

    logger.info("🧐 Запуск recovery-перевірки...")
    # Створюємо фіктивний bot об'єкт для перевірки (реальний ще не створений)
    # Але нам потрібен токен для API
    temp_bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    
    # Викликаємо recovery перед запуском polling
    await recovery_check(temp_bot)
    await temp_bot.session.close()  # Закриваємо сесію тимчасового бота

    logger.info("Запуск бота...")
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # Реєстрація хендлерів
    dp.include_router(start_router)
    dp.include_router(course_router)
    admin_handlers.register_admin_handlers(dp)  # Підключаємо адмін-команди

    # Видаляємо вебхук (якщо був) і запускаємо polling
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception:
        pass
    logger.info("✅ Бот запущений! Очікування повідомлень...")

    try:
        await dp.start_polling(bot)
    finally:
        stop_scheduler()


if __name__ == "__main__":
    asyncio.run(main())
