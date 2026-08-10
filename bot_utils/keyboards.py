"""Клавіатури та інлайн-кнопки для бота."""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)


def next_button(day: int, block_idx: int) -> InlineKeyboardMarkup:
    """Кнопка 'Далі' для переходу до наступного логічного блоку."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➡️ Далі", callback_data=f"next_block:{day}:{block_idx}")]
    ])


def start_course_keyboard() -> InlineKeyboardMarkup:
    """Кнопка після привітання — почати курс."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Почати курс", callback_data="start_course")]
    ])


def next_day_keyboard(day: int) -> InlineKeyboardMarkup:
    """Кнопка переходу до наступного дня з текстом-підказкою."""
    prompts = {
        1: "🌙 Завтра о 9:00 — розберемо наповнення тарілки",
        2: "🌙 Завтра о 9:00 — поговоримо про вуглеводи",
        3: "🌙 Завтра о 9:00 — розберемо жири",
        4: "🌙 Завтра о 9:00 — зберемо все разом",
    }
    text = prompts.get(day, "🌙 Завтра о 9:00 — продовжимо")
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data=f"schedule_day_{day + 1}")]
    ])


def feedback_keyboard() -> InlineKeyboardMarkup:
    """Клавіатура для заповнення фідбек-анкети."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="📝 Залишити відгук і отримати бонус",
                callback_data="start_feedback"
            )
        ]
    ])


def feedback_answer_keyboard(question_index: int) -> InlineKeyboardMarkup | None:
    """Швидкі відповіді там, де шкала зручніша за текст."""
    if question_index == 0:
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=str(value), callback_data=f"feedback_answer:0:{value}")
            for value in range(1, 6)
        ]])
    if question_index == 4:
        options = [
            ("Легше готувати", "meal_ideas"),
            ("Більше рухатись", "movement"),
            ("Тримати режим", "consistency"),
            ("Особистий план", "personal"),
        ]
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=f"feedback_answer:4:{value}")]
            for label, value in options
        ])
    if question_index == 5:
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=str(value), callback_data=f"feedback_answer:5:{value}")
                for value in range(0, 6)
            ],
            [
                InlineKeyboardButton(text=str(value), callback_data=f"feedback_answer:5:{value}")
                for value in range(6, 11)
            ],
        ])
    return None


def cta_keyboard() -> InlineKeyboardMarkup:
    """Варіанти продовження без припущення, що учасник «застряг»."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🍽 Спростити щоденне харчування",
                callback_data="cta_recipes"
            )
        ],
        [
            InlineKeyboardButton(
                text="🏃 Додати більше руху",
                callback_data="cta_movement"
            )
        ],
        [
            InlineKeyboardButton(
                text="🔁 Закріпити результат із підтримкою",
                callback_data="cta_online"
            )
        ],
        [
            InlineKeyboardButton(
                text="🎯 Отримати персональний план",
                callback_data="cta_consultation"
            )
        ],
        [
            InlineKeyboardButton(
                text="🔙 Звернутись в підтримку",
                callback_data="cta_contact_support"
            )
        ],
    ])
