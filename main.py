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
from database import create_database_backup, init_db
from scheduler import (
    init_scheduler,
    stop_scheduler,
    recovery_check,
    restore_course_schedules,
    schedule_completion_checks,
    process_course_completions,
)
from handlers.start import router as start_router
from handlers.course import router as course_router
from handlers import admin as admin_handlers  # Адмін-команди
from access import CourseAccessMiddleware

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
    create_database_backup()

    logger.info("Запуск планувальника...")
    init_scheduler()

    logger.info("Запуск бота...")
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    logger.info("🧐 Запуск recovery-перевірки...")
    await recovery_check(bot)
    await restore_course_schedules(bot)
    schedule_completion_checks(bot)
    await process_course_completions(bot)
    dp = Dispatcher()
    dp.message.outer_middleware(CourseAccessMiddleware())
    dp.callback_query.outer_middleware(CourseAccessMiddleware())

    # Реєстрація хендлерів
    # Stateful handlers must be registered before the generic text fallback
    # in start_router. Otherwise every feedback answer is consumed by
    # handle_any_message before FeedbackState.answering gets a chance to run.
    # Admin commands must be registered before start_router's generic text
    # fallback, otherwise the fallback consumes commands such as /grant_access.
    admin_handlers.register_admin_handlers(dp)
    dp.include_router(course_router)
    dp.include_router(start_router)

    # Видаляємо вебхук (якщо був) і запускаємо polling
    try:
        await bot.delete_webhook(drop_pending_updates=False)
    except Exception:
        pass
    logger.info("✅ Бот запущений! Очікування повідомлень...")

    try:
        await dp.start_polling(bot)
    finally:
        stop_scheduler()


if __name__ == "__main__":
    asyncio.run(main())
