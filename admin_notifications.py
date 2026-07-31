"""Send owner notifications from the single Kolodii Fitness Admin bot."""

import logging
import os

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import ADMIN_ID

logger = logging.getLogger(__name__)
ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN", "").strip()


async def send_admin_message(text: str) -> bool:
    if not ADMIN_ID or not ADMIN_BOT_TOKEN:
        logger.error("ADMIN_ID or ADMIN_BOT_TOKEN is not configured")
        return False
    bot = Bot(ADMIN_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        await bot.send_message(ADMIN_ID, text)
        return True
    except Exception:
        logger.exception("Kolodii Fitness Admin notification failed")
        return False
    finally:
        await bot.session.close()
