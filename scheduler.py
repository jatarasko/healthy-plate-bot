"""
Планувальник — відправка днів курсу з recovery-логікою.
"""
import asyncio
import html
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import zoneinfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from aiogram import Bot
from aiogram.types import FSInputFile

from database import (
    get_all_active_users, 
    get_users_for_day, 
    update_user_after_send,
    set_sending_status,
    get_users_for_recovery,
    has_course_access,
    update_user_day,
    mark_course_completed,
    mark_completion_notified,
    get_unnotified_completions,
    get_due_completion_followups,
    advance_completion_followup,
    set_course_progress_waiting,
    clear_course_progress_waiting,
    get_due_progress_reminders,
    advance_progress_reminder,
    record_course_event,
    get_unnotified_feedback,
)
from content.course import get_day_blocks, IMAGES
from bot_utils.keyboards import feedback_keyboard, next_button, cta_keyboard
from config import ADMIN_ID
from admin_notifications import send_admin_message

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

PROJECT_ROOT = Path(__file__).resolve().parent


def _resolve_asset_path(relative_path: str) -> Path:
    """Resolve a repository-relative asset path against the project root."""
    return PROJECT_ROOT / relative_path


def init_scheduler():
    """Запустити планувальник."""
    scheduler.start()


def stop_scheduler():
    """Зупинити планувальник."""
    scheduler.shutdown()


def schedule_completion_checks(bot: Bot):
    """Регулярно перевіряти нагадування випускникам і активним учасникам."""
    scheduler.add_job(
        process_course_completions,
        trigger=IntervalTrigger(minutes=15),
        args=[bot],
        id="course_completion_followups",
        replace_existing=True,
        max_instances=1,
    )


async def send_day(bot: Bot, user_id: int, day: int):
    """Відправити перший блок дня курсу користувачу."""
    if not await has_course_access(user_id):
        logger.warning("Відправку дня %s заблоковано: user %s не має доступу", day, user_id)
        return
    await send_block(bot, user_id, day=day, block_idx=0)


async def send_block(bot: Bot, user_id: int, day: int, block_idx: int):
    """
    Відправити один блок курсу і кнопку переходу до наступного блоку.
    Оновлює статус тільки після успішної відправки ВСІХ повідомлень блоку.
    """
    blocks = get_day_blocks(day)
    if not blocks:
        logger.error(f"День {day} не знайдено для user {user_id}")
        return

    if block_idx < 0 or block_idx >= len(blocks):
        logger.error(f"Некоректний блок {block_idx} для дня {day}, user {user_id}")
        return

    # Встановлюємо статус 'sending', щоб інші процеси не дублювали
    await set_sending_status(user_id, 'sending')
    logger.info(f"Користувач {user_id}: початок відправки дня {day}, блок {block_idx}")

    block = blocks[block_idx]
    messages = block.get("messages", [])
    image_key = block.get("image")

    try:
        # Будь-який новий блок означає, що попередню паузу подолано.
        await clear_course_progress_waiting(user_id)
        for msg in messages:
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=msg,
                    parse_mode="HTML",
                )
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Помилка відправки повідомлення user {user_id}: {e}")
                # Якщо впало посеред блоку — статус залишається 'sending' (відновиться при recovery)

        if image_key:
            image_rel_path = IMAGES.get(image_key, "")
            if not image_rel_path:
                logger.error(f"Ключ фото {image_key} не знайдено в IMAGES")
            else:
                image_path = _resolve_asset_path(image_rel_path)
                if not os.path.exists(image_path):
                    logger.error(f"Файл фото не існує: {image_rel_path}")
                else:
                    try:
                        logger.info(f"Відправляю фото: {image_rel_path}")
                        await bot.send_photo(
                            chat_id=user_id,
                            photo=FSInputFile(str(image_path)),
                            caption="📸 Метод долоні — твій орієнтир порцій",
                        )
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        logger.error(f"Помилка відправки фото {image_key} ({image_rel_path}): {e}")

        # Успішно відправили поточний блок
        if block_idx < len(blocks) - 1:
            await bot.send_message(
                chat_id=user_id,
                text="Готовий(-а) продовжити?",
                reply_markup=next_button(day, block_idx + 1),
            )
            await set_course_progress_waiting(user_id, day, block_idx + 1)
            # Скидаємо статус sending, чекаємо на натискання "Далі"
            await set_sending_status(user_id, 'idle')
            return

        # Всі блоки дня відправлено успішно
        await update_user_after_send(user_id, day)
        logger.info(f"Користувач {user_id}: день {day} повністю завершено")

        if day < 5:
            await bot.send_message(
                chat_id=user_id,
                text=f"✅ День {day} завершено!\n\n📅 Продовжимо завтра о 09:00.",
            )
            schedule_next_day(bot, user_id, day + 1)
            return

        # Курс завершено (день 5)
        newly_completed = await mark_course_completed(user_id)
        if newly_completed:
            await record_course_event(user_id, "course_completed")
        await notify_admin_course_completed(bot, user_id)
        try:
            await bot.send_message(
                chat_id=user_id,
                text=(
                    "🎉 <b>Вітаю! Ти завершив(-ла) курс «Здорова Тарілка».</b>\n\n"
                    "Залиш короткий відгук і забери бонус. А наступний крок можна "
                    "обрати вже зараз — незалежно від анкети."
                ),
                parse_mode="HTML",
            )
            await bot.send_message(
                chat_id=user_id,
                text="📝 Залиш відгук про курс — і отримай PDF «9 фішок харчування для схуднення» у подяку!",
                reply_markup=feedback_keyboard(),
            )
            await bot.send_message(
                chat_id=user_id,
                text=(
                    "🎯 <b>Що зараз найбільше заважає рухатись далі?</b>\n\n"
                    "Обери свою ситуацію — бот покаже рішення, результат і наступну дію."
                ),
                reply_markup=cta_keyboard(),
                parse_mode="HTML",
            )
            await record_course_event(user_id, "offer_shown", {"stage": "completion"})
        except Exception as e:
            logger.error(f"Помилка відправки фідбек-кнопки: {e}")

    except Exception as e:
        logger.error(f"Критична помилка при відправці дня {day} для user {user_id}: {e}")
        # Статус 'sending' залишається, але Recovery його скине через 10 хв


async def notify_admin_course_completed(bot: Bot, user_id: int) -> bool:
    """Повідомити адміністратора про завершення незалежно від натискання CTA."""
    if not ADMIN_ID:
        logger.error("ADMIN_ID не налаштовано; завершення user %s не надіслано", user_id)
        return False

    from database import get_user

    user = await get_user(user_id)
    if not user or user.get("completion_notified_at"):
        return bool(user)
    full_name = html.escape(" ".join(
        part for part in (user.get("first_name"), user.get("last_name")) if part
    ) or "Без імені")
    username = html.escape(f"@{user['username']}") if user.get("username") else "не вказано"
    try:
        notified = await send_admin_message(
            "🎓 <b>Учасник завершив курс «Здорова Тарілка»</b>\n\n"
            f"Користувач: <a href=\"tg://user?id={user_id}\">{full_name}</a>\n"
            f"Username: {username}\n"
            f"Telegram ID: <code>{user_id}</code>\n\n"
            "Наступний крок ще не обрано. Бот автоматично нагадає учаснику "
            "через 1 і 3 дні.",
        )
        if not notified:
            return False
        await mark_completion_notified(user_id)
        return True
    except Exception:
        logger.exception("Не вдалося повідомити про завершення user %s", user_id)
        return False


async def process_course_completions(bot: Bot):
    """Повторити адмін-сповіщення і надіслати належні follow-up повідомлення."""
    # Якщо Telegram був тимчасово недоступний у момент завершення анкети,
    # повторюємо адмін-сповіщення без втрати вже збережених відповідей.
    from handlers.course import _notify_admin_feedback

    for submission_id in await get_unnotified_feedback():
        await _notify_admin_feedback(bot, submission_id)

    for user in await get_unnotified_completions():
        await notify_admin_course_completed(bot, user["user_id"])

    for user in await get_due_completion_followups():
        user_id = user["user_id"]
        stage = int(user.get("followup_stage") or 0) + 1
        if stage == 3:
            if await notify_admin_no_next_step(bot, user):
                await advance_completion_followup(user_id, stage)
            continue
        if stage == 1:
            text = (
                "🌿 <b>Як твої справи після курсу?</b>\n\n"
                "Щоб знання перетворились на звичку, обери формат, який найкраще "
                "підтримає тебе далі 👇"
            )
        else:
            text = (
                "💛 <b>Невелике нагадування про наступний крок</b>\n\n"
                "Якщо складно визначитись, почни з консультації: розберемо твою "
                "ситуацію та підберемо доречний формат без зайвих зобов’язань 👇"
            )
        try:
            await bot.send_message(
                user_id,
                text,
                reply_markup=cta_keyboard(),
                parse_mode="HTML",
            )
            await record_course_event(user_id, "offer_shown", {"stage": f"followup_{stage}"})
            await advance_completion_followup(user_id, stage)
        except Exception:
            logger.exception("Не вдалося надіслати follow-up %s user %s", stage, user_id)

    await process_progress_reminders(bot)


async def process_progress_reminders(bot: Bot):
    """Нагадати про незавершений блок і ескалювати тривалу паузу адміну."""
    for user in await get_due_progress_reminders():
        user_id = user["user_id"]
        stage = int(user.get("progress_reminder_stage") or 0) + 1
        if stage == 3:
            if await notify_admin_progress_stalled(bot, user):
                await advance_progress_reminder(user_id, stage)
            continue

        if stage == 1:
            text = (
                "👋 <b>Продовжимо курс?</b>\n\n"
                "Твій наступний короткий блок уже чекає. Натисни «Далі» — "
                "це займе лише кілька хвилин."
            )
        else:
            text = (
                "🌿 <b>Не втрачай свій прогрес</b>\n\n"
                "Навіть маленький крок важливий. Повернись до курсу з того місця, "
                "де зупинився(-лась) 👇"
            )
        try:
            await bot.send_message(
                user_id,
                text,
                reply_markup=next_button(
                    int(user["progress_waiting_day"]),
                    int(user["progress_waiting_block"]),
                ),
                parse_mode="HTML",
            )
            await advance_progress_reminder(user_id, stage)
        except Exception:
            logger.exception("Не вдалося нагадати про прогрес user %s", user_id)


async def notify_admin_progress_stalled(bot: Bot, user: dict) -> bool:
    """Повідомити адміністратора після двох невдалих нагадувань."""
    if not ADMIN_ID:
        return False
    user_id = user["user_id"]
    full_name = html.escape(" ".join(
        part for part in (user.get("first_name"), user.get("last_name")) if part
    ) or "Без імені")
    username = html.escape(f"@{user['username']}") if user.get("username") else "не вказано"
    try:
        return await send_admin_message(
            "⏸ <b>Учасник зупинив проходження курсу</b>\n\n"
            f"Користувач: <a href=\"tg://user?id={user_id}\">{full_name}</a>\n"
            f"Username: {username}\n"
            f"Telegram ID: <code>{user_id}</code>\n"
            f"Зупинився на дні {user['progress_waiting_day']}.\n\n"
            "Бот уже надіслав два нагадування. За потреби можна написати "
            "учаснику особисто.",
        )
    except Exception:
        logger.exception("Не вдалося повідомити про зупинку user %s", user_id)
        return False


async def notify_admin_no_next_step(bot: Bot, user: dict) -> bool:
    """Повідомити, що після серії нагадувань випускник нічого не обрав."""
    if not ADMIN_ID:
        return False
    user_id = user["user_id"]
    full_name = html.escape(" ".join(
        part for part in (user.get("first_name"), user.get("last_name")) if part
    ) or "Без імені")
    username = html.escape(f"@{user['username']}") if user.get("username") else "не вказано"
    try:
        return await send_admin_message(
            "⚠️ <b>Випускник не обрав наступний крок</b>\n\n"
            f"Користувач: <a href=\"tg://user?id={user_id}\">{full_name}</a>\n"
            f"Username: {username}\n"
            f"Telegram ID: <code>{user_id}</code>\n\n"
            "Бот уже надіслав два нагадування. Можна написати учаснику особисто "
            "та запропонувати консультацію або відповідний продукт.",
        )
    except Exception:
        logger.exception("Не вдалося повідомити про відсутність next step user %s", user_id)
        return False


def schedule_next_day(bot: Bot, user_id: int, next_day: int):
    """Запланувати відправку наступного дня о 9:00 за київським часом."""
    KYIV = zoneinfo.ZoneInfo("Europe/Kyiv")

    now_kyiv = datetime.now(KYIV)
    tomorrow_kyiv = (now_kyiv + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    send_time_utc = tomorrow_kyiv.astimezone(timezone.utc)

    scheduler.add_job(
        send_day,
        trigger=DateTrigger(run_date=send_time_utc),
        args=[bot, user_id, next_day],
        id=f"day_{next_day}_user_{user_id}",
        replace_existing=True,
    )
    logger.info(f"Заплановано День {next_day} для user {user_id} на {tomorrow_kyiv} (Kyiv)")


async def recovery_check(bot: Bot):
    """
    Recovery-функція: викликається при старті бота.
    Перевіряє кожного користувача, знаходить пропущені дні.
    Надсилає максимум 1 пропущений день за раз.
    """
    logger.info("🔄 Запуск recovery-перевірки...")
    users = await get_users_for_recovery()
    
    if not users:
        logger.info("✅ Пропущених днів не знайдено. Всі користувачі в актуальному стані.")
        return

    for user in users:
        user_id = user['user_id']
        current_day = user['current_day']
        last_sent = user.get('last_sent_day', 0)
        sending_status = user.get('sending_status', 'idle')

        # Скидаємо завислий статус 'sending' (якщо бот впав під час відправки)
        if sending_status == 'sending':
            logger.warning(f"🔄 Користувач {user_id}: скидання завислого статусу 'sending'")
            await set_sending_status(user_id, 'idle')

        # Знаходимо перший невидправлений день
        missed_day = last_sent + 1
        
        if missed_day > current_day:
            logger.warning(f"Користувач {user_id}: last_sent > current_day. Оновлюємо current_day.")
            await update_user_day(user_id, last_sent)
            continue

        logger.info(f"🔄 Recovery: Користувач {user_id}, пропущено день {missed_day}. Надсилаємо зараз...")
        await send_day(bot, user_id, missed_day)
        
        # Важливо: виходимо після відправки ОДНОГО пропущеного дня,
        # щоб не спамити користувача кількома днями одразу.
        break

    logger.info("✅ Recovery-перевірка завершена.")
