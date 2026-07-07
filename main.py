"""Головний файл бота — точка входу."""

import asyncio
import logging
import threading

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from config import BOT_TOKEN
from database import init_db
from scheduler import init_scheduler, stop_scheduler
from handlers.start import router as start_router
from handlers.course import router as course_router

# Import health server for Railway
from health_server import start_health_server

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """Запуск бота."""
    logger.info("Запуск health server для Railway...")
    # Start health server in a separate thread
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()

    logger.info("Ініціалізація бази даних...")
    await init_db()

    logger.info("Запуск планувальника...")
    init_scheduler()

    logger.info("Запуск бота...")
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # Реєстрація хендлерів
    dp.include_router(start_router)
    dp.include_router(course_router)

    # Видаляємо вебхук (якщо був) і запускаємо polling
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception:
        pass
    logger.info("Бот запущений! Очікування повідомлень...")

    try:
        await dp.start_polling(bot)
    finally:
        stop_scheduler()


if __name__ == "__main__":
    asyncio.run(main())
