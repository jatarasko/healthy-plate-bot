"""Планувальник — відправка днів курсу."""

import asyncio
import logging
import os
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

from aiogram import Bot
from aiogram.types import FSInputFile

from database import update_user_day
from content.course import get_day_blocks, IMAGES
from bot_utils.keyboards import feedback_keyboard, next_button

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def init_scheduler():
    """Запустити планувальник."""
    scheduler.start()


def stop_scheduler():
    """Зупинити планувальник."""
    scheduler.shutdown()


async def send_day(bot: Bot, user_id: int, day: int):
    """Відправити перший блок дня курсу користувачу."""
    await send_block(bot, user_id, day=day, block_idx=0)


async def send_block(bot: Bot, user_id: int, day: int, block_idx: int):
    """Відправити один блок курсу і кнопку переходу до наступного блоку."""
    blocks = get_day_blocks(day)
    if not blocks:
        logger.error(f"День {day} не знайдено для user {user_id}")
        return

    if block_idx < 0 or block_idx >= len(blocks):
        logger.error(f"Некоректний блок {block_idx} для дня {day}, user {user_id}")
        return

    block = blocks[block_idx]
    messages = block.get("messages", [])
    image_key = block.get("image")

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

    if image_key:
        image_path = IMAGES.get(image_key, "")
        if not image_path:
            logger.error(f"Ключ фото {image_key} не знайдено в IMAGES")
        elif not os.path.exists(image_path):
            logger.error(f"Файл фото не існує: {image_path}")
        else:
            try:
                logger.info(f"Відправляю фото: {image_path}")
                await bot.send_photo(
                    chat_id=user_id,
                    photo=FSInputFile(image_path),
                    caption="📸 Метод долоні — твій орієнтир порцій",
                )
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Помилка відправки фото {image_key} ({image_path}): {e}")

    if block_idx < len(blocks) - 1:
        await bot.send_message(
            chat_id=user_id,
            text="Готовий(-а) продовжити?",
            reply_markup=next_button(day, block_idx + 1),
        )
        return

    await update_user_day(user_id, day)

    if day < 5:
        await bot.send_message(
            chat_id=user_id,
            text=f"✅ День {day} завершено!\n\n📅 Продовжимо завтра о 09:00.",
        )
        schedule_next_day(bot, user_id, day + 1)
        return

    try:
        await update_user_day(user_id, 6)
        await bot.send_message(
            chat_id=user_id,
            text="📝 Залиш відгук про курс — і отримай PDF «9 фішок здорового харчування» у подяку!",
            reply_markup=feedback_keyboard(),
        )
    except Exception as e:
        logger.error(f"Помилка відправки фідбек-кнопки: {e}")


async def send_full_course(bot: Bot, user_id: int):
    """Почати курс з першого блоку. Далі користувач рухається кнопками."""
    await send_block(bot, user_id, day=1, block_idx=0)


def schedule_next_day(bot: Bot, user_id: int, next_day: int):
    """Запланувати відправку наступного дня о 9:00."""
    tomorrow = datetime.now() + timedelta(days=1)
    send_time = tomorrow.replace(hour=9, minute=0, second=0, microsecond=0)

    scheduler.add_job(
        send_day,
        trigger=DateTrigger(run_date=send_time),
        args=[bot, user_id, next_day],
        id=f"day_{next_day}_user_{user_id}",
        replace_existing=True,
    )
    logger.info(f"Заплановано День {next_day} для user {user_id} на {send_time}")
