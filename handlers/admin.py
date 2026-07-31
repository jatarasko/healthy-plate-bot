"""
Адміністративні команди для адміністратора (Taras).
Включає /recover для ручного запуску recovery.
"""
import html
import logging
from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command

from database import (
    get_user,
    get_users_for_recovery,
    grant_course_access,
    revoke_course_access,
    update_user_after_send,
    set_sending_status,
)
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

    @dp.message(Command("grant_access"))
    async def grant_access_command(message: Message):
        if message.from_user.id != ADMIN_ID:
            return
        parts = (message.text or "").split()
        if len(parts) != 2 or not parts[1].isdigit():
            await message.answer("Використання: /grant_access TELEGRAM_ID")
            return
        user_id = int(parts[1])
        await grant_course_access(user_id, "manual-admin-grant")
        await message.answer(f"✅ Доступ надано користувачу {user_id}.")

    @dp.message(Command("revoke_access"))
    async def revoke_access_command(message: Message):
        if message.from_user.id != ADMIN_ID:
            return
        parts = (message.text or "").split()
        if len(parts) != 2 or not parts[1].isdigit():
            await message.answer("Використання: /revoke_access TELEGRAM_ID")
            return
        user_id = int(parts[1])
        await revoke_course_access(user_id)
        await message.answer(f"🔒 Доступ користувача {user_id} відкликано.")

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
            f"Без наступного кроку: {stats['without_next_step']}\n"
        )
        await message.answer(report, parse_mode="HTML")

    @dp.message(Command("followups"))
    async def followups_command(message: Message):
        """Показати випускників, які ще не обрали наступний крок."""
        if message.from_user.id != ADMIN_ID:
            return
        from database import get_completed_without_next_step

        users = await get_completed_without_next_step()
        if not users:
            await message.answer("✅ Усі випускники обрали наступний крок.")
            return
        lines = ["🎓 <b>Завершили курс без наступного кроку</b>\n"]
        for user in users:
            name = html.escape(" ".join(
                part for part in (user.get("first_name"), user.get("last_name")) if part
            ) or "Без імені")
            username = html.escape(f"@{user['username']}") if user.get("username") else "без username"
            lines.append(
                f"• <a href=\"tg://user?id={user['user_id']}\">{name}</a> — "
                f"{username}, ID <code>{user['user_id']}</code>"
            )
        await message.answer("\n".join(lines), parse_mode="HTML")

    @dp.message(Command("feedback"))
    async def feedback_command(message: Message):
        """Останні анкети або повний текст конкретної анкети: /feedback ID."""
        if message.from_user.id != ADMIN_ID:
            return
        from database import get_feedback_submission, get_recent_feedback

        parts = (message.text or "").split()
        if len(parts) == 2 and parts[1].isdigit():
            submission = await get_feedback_submission(int(parts[1]))
            if not submission:
                await message.answer("Анкету не знайдено.")
                return
            name = html.escape(" ".join(
                part for part in (submission.get("first_name"), submission.get("last_name")) if part
            ) or "Без імені")
            lines = [
                f"📝 <b>Анкета #{submission['id']}</b>",
                f"Учасник: <a href=\"tg://user?id={submission['user_id']}\">{name}</a>",
                f"Статус: {html.escape(submission['status'])}",
                "",
            ]
            for answer in submission["answers"]:
                lines.extend([
                    f"<b>{answer['question_index'] + 1}. {html.escape(answer['question_key'])}</b>",
                    html.escape(answer["answer"]),
                    "",
                ])
            await message.answer("\n".join(lines), parse_mode="HTML")
            return

        submissions = await get_recent_feedback()
        if not submissions:
            await message.answer("Відгуків ще немає.")
            return
        lines = ["📝 <b>Останні анкети</b>\n"]
        for item in submissions:
            name = html.escape(" ".join(
                part for part in (item.get("first_name"), item.get("last_name")) if part
            ) or "Без імені")
            marker = "✅" if item["status"] == "completed" else "⏳"
            lines.append(
                f"{marker} <code>#{item['id']}</code> {name} — {item['answer_count']}/6; "
                f"/feedback {item['id']}"
            )
        await message.answer("\n".join(lines), parse_mode="HTML")

    @dp.message(Command("completions"))
    async def completions_command(message: Message):
        if message.from_user.id != ADMIN_ID:
            return
        from database import get_recent_completions

        users = await get_recent_completions()
        if not users:
            await message.answer("Завершень курсу ще немає.")
            return
        lines = ["🎓 <b>Останні завершення</b>\n"]
        for user in users:
            name = html.escape(" ".join(
                part for part in (user.get("first_name"), user.get("last_name")) if part
            ) or "Без імені")
            next_step = html.escape(user.get("next_step") or "ще не обрано")
            lines.append(
                f"• <a href=\"tg://user?id={user['user_id']}\">{name}</a> — {next_step}"
            )
        await message.answer("\n".join(lines), parse_mode="HTML")

    @dp.message(Command("funnel"))
    async def funnel_command(message: Message):
        if message.from_user.id != ADMIN_ID:
            return
        from database import get_funnel_stats

        stats = await get_funnel_stats()
        events = stats["events"]
        await message.answer(
            "📈 <b>Воронка після курсу</b>\n\n"
            f"Завершили: {stats['completed']}\n"
            f"Почали анкету: {stats['feedback_started']}\n"
            f"Завершили анкету: {stats['feedback_completed']}\n"
            f"Побачили пропозицію: {events.get('offer_shown', 0)}\n"
            f"Обрали пропозицію: {events.get('offer_clicked', 0)}\n"
            f"Мають наступний крок: {stats['next_step_selected']}",
            parse_mode="HTML",
        )
