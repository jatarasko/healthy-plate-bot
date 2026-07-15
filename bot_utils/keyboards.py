"""Клавіатури та інлайн-кнопки для бота."""

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


def cta_keyboard() -> InlineKeyboardMarkup:
    """Клавіатура CTA після завершення курсу."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🏃‍♂️ Курс «Рухова активність»",
                callback_data="cta_movement"
            )
        ],
        [
            InlineKeyboardButton(
                text="💬 Консультація з Тарасом",
                callback_data="cta_consultation"
            )
        ],
        [
            InlineKeyboardButton(
                text="📱 Онлайн-супровід",
                url="https://t.me/kolodiifitness_bot?start=healthy_plate"
            )
        ],
        [
            InlineKeyboardButton(
                text="📖 Набір рецептів + бонуси",
                callback_data="cta_recipes"
            )
        ],
        [
            InlineKeyboardButton(
                text="🔙 Звернутись в підтримку",
                callback_data="contact_support"
            )
        ],
    ])
