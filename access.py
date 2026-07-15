from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, TelegramObject

from config import ADMIN_ID, SALES_BOT_USERNAME
from database import has_course_access


def sales_keyboard() -> InlineKeyboardMarkup | None:
    if not SALES_BOT_USERNAME:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Придбати доступ",
                    url=f"https://t.me/{SALES_BOT_USERNAME}?start=course_healthy_plate",
                )
            ]
        ]
    )


class CourseAccessMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if not user or user.id == ADMIN_ID:
            return await handler(event, data)
        if isinstance(event, Message) and (event.text or "").startswith("/start"):
            return await handler(event, data)
        if await has_course_access(user.id):
            return await handler(event, data)
        if isinstance(event, CallbackQuery):
            await event.answer("Доступ до курсу не активовано.", show_alert=True)
        elif isinstance(event, Message):
            await event.answer(
                "🔒 Доступ до курсу відкривається після підтвердження оплати.",
                reply_markup=sales_keyboard(),
            )
        return None
