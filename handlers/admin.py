"""
Адміністративні команди для адміністратора (Taras).
Включає /recover для ручного запуску recovery.
"""
import logging
from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command

from database import get_user, get_users_for_recovery, update_user_after_send, set_sending_status
from config import ADMIN_ID
from scheduler import send_day  # Імпортуємо функцію відправки

logger = logging.getLogger(__name__)

def register_admin_handlers(dp: Dispatcher):
    """Реєстрація адмін-хендлерів."""

    @dp.message(Command("recover"))
    async def recover_command(message: Message, bot: Bot):
        """Ручний запуск recovery для конкретного користувача."""
        # Перевірка прав: тільки ADMIN_ID може використовувати
        if message.from_user.id != ADMIN_ID:
            await message.answer("❌ У вас немає прав для цієї команди.")
            return

        # Парсинг аргументів: /recover <telegram_id>
        args = message.text.split()
        if len(args) < 2:
            await message.answer("ℹ️ Використання: /recover <telegram_id>")
            return

        try:
            target_user_id = int(args[1])
        except ValueError:
            await message.answer("❌ Некоректний Telegram ID. Має бути число.")
            return

        # Отримуємо дані користувача
        user = await get_user(target_user_id)
        if not user:
            await message.answer(f"❌ Користувача з ID {target_user_id} не знайдено.")
            return

        current_day = user.get('current_day', 0)
        last_sent = user.get('last_sent_day', 0)
        sending_status = user.get('sending_status', 'idle')

        # Формуємо звіт
        report = (
            f"🔍 <b>Recovery звіт для {target_user_id}</b>\n\n"
            f"Поточний день: {current_day}\n"
            f"Останній надісланий день: {last_sent}\n"
            f"Статус відправки: {sending_status}\n\n"
        )

        # Знаходимо пропущений день
        missed_day = last_sent + 1
        if missed_day > current_day:
            report += f"✅ Пропущених днів немає. Користувач на дні {current_day}."
            await message.answer(report, parse_mode="HTML")
            return

        report += f"🔄 Знайдено пропущений день: <b>{missed_day}</b>\n"
        report += f"🚀 Починаю відправку..."

        await message.answer(report, parse_mode="HTML")
        logger.info(f"Admin recovery: спроба надіслати день {missed_day} користувачу {target_user_id}")

        try:
            # Скидаємо статус, якщо завис
            if sending_status == 'sending':
                await set_sending_status(target_user_id, 'idle')

            # Відправляємо перший блок пропущеного дня
            await send_day(bot, target_user_id, missed_day)
            
            # Після успішної відправки оновлюємо статус
            # (Це робить update_user_after_send всередині send_block)
            
            await message.answer(
                f"✅ День {missed_day} успішно надіслано користувачу {target_user_id}."
            )
        except Exception as e:
            error_msg = f"❌ Помилка при відправці дня {missed_day}: {e}"
            logger.error(error_msg)
            await message.answer(error_msg)

    @dp.message(Command("stats"))
    async def stats_command(message: Message):
        """Показати статистику бота."""
        if message.from_user.id != ADMIN_ID:
            await message.answer("❌ У вас немає прав для цієї команди.")
            return

        from database import get_stats
        stats = await get_stats()
        
        report = (
            f"📊 <b>Статистика бота</b>\n\n"
            f"Всього користувачів: {stats['total_users']}\n"
            f"Активні: {stats['active_users']}\n"
            f"Завершили курс: {stats['completed_course']}\n"
            f"Фідбек отримано: {stats['feedback_received']}\n"
        )
        await message.answer(report, parse_mode="HTML")
