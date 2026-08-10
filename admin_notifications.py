"""Send owner notifications from the single Kolodii Fitness Admin bot."""

import logging
import os

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import ADMIN_ID, BOT_TOKEN

logger = logging.getLogger(__name__)
ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN", "").strip()


async def send_admin_message(text: str) -> bool:
    if not ADMIN_ID:
        logger.error("ADMIN_ID is not configured")
        return False

    # A separate admin bot is optional. Falling back to this course bot keeps
    # leads deliverable when ADMIN_BOT_TOKEN was not added to a deployment.
    notification_token = ADMIN_BOT_TOKEN or BOT_TOKEN
    if not ADMIN_BOT_TOKEN:
        logger.warning("ADMIN_BOT_TOKEN is not configured; using BOT_TOKEN for admin notifications")
    bot = Bot(notification_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        await bot.send_message(ADMIN_ID, text)
        return True
    except Exception:
        logger.exception("Kolodii Fitness Admin notification failed")
        return False
    finally:
        await bot.session.close()
