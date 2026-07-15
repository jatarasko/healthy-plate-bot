"""
Планувальник — відправка днів курсу з recovery-логікою.
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import zoneinfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

from aiogram import Bot
from aiogram.types import FSInputFile

from database import (
    get_all_active_users, 
    get_users_for_day, 
    update_user_after_send,
    set_sending_status,
    get_users_for_recovery,
    has_course_access,
    update_user_day
)
from content.course import get_day_blocks, IMAGES
from bot_utils.keyboards import feedback_keyboard, next_button

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
        try:
            await bot.send_message(
                chat_id=user_id,
                text="📝 Залиш відгук про курс — і отримай PDF «9 фішок харчування для схуднення» у подяку!",
                reply_markup=feedback_keyboard(),
            )
        except Exception as e:
            logger.error(f"Помилка відправки фідбек-кнопки: {e}")

    except Exception as e:
        logger.error(f"Критична помилка при відправці дня {day} для user {user_id}: {e}")
        # Статус 'sending' залишається, але Recovery його скине через 10 хв


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
