"""Хендлер курсу — фідбек, CTA."""

import html
import logging
from pathlib import Path

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    Message,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.fsm.context import FSMContext

from config import ADMIN_ID
from database import mark_feedback_sent
from states import FeedbackState
from content.course import FEEDBACK_QUESTIONS, FEEDBACK_THANKS
from bot_utils.keyboards import feedback_keyboard, cta_keyboard

router = Router()
logger = logging.getLogger(__name__)

FEEDBACK_BONUS_PATH = (
    Path(__file__).resolve().parent.parent / "assets" / "9_fishok_premium_guide.pdf"
)
ONLINE_SUPPORT_BOT_URL = "https://t.me/kolodiifitness_bot?start=healthy_plate"


async def _notify_admin_about_interest(
    callback: CallbackQuery,
    offer_name: str,
) -> bool:
    """Надіслати адміну заявку з кнопки після завершення курсу."""
    if not ADMIN_ID:
        logger.error("ADMIN_ID не налаштовано; заявку '%s' не надіслано", offer_name)
        return False

    user = callback.from_user
    safe_name = html.escape(user.full_name)
    safe_username = html.escape(f"@{user.username}") if user.username else "не вказано"

    try:
        await callback.bot.send_message(
            ADMIN_ID,
            "🔔 <b>Нова заявка після курсу «Здорова Тарілка»</b>\n\n"
            f"Продукт: <b>{html.escape(offer_name)}</b>\n"
            f"Користувач: <a href=\"tg://user?id={user.id}\">{safe_name}</a>\n"
            f"Username: {safe_username}\n"
            f"Telegram ID: <code>{user.id}</code>",
            parse_mode="HTML",
        )
    except Exception:
        logger.exception(
            "Не вдалося повідомити адміна про заявку '%s' від user %s",
            offer_name,
            user.id,
        )
        return False

    return True


async def _confirm_admin_notification(
    callback: CallbackQuery,
    offer_name: str,
) -> None:
    """Підтвердити користувачу результат передавання заявки."""
    notified = await _notify_admin_about_interest(callback, offer_name)
    if notified:
        await callback.message.answer(
            "✅ <b>Заявку передано адміністратору.</b>\n\n"
            "Він напише тобі в Telegram, розповість деталі та допоможе з оформленням.",
            parse_mode="HTML",
        )
    else:
        await callback.message.answer(
            "⚠️ Не вдалося автоматично передати заявку адміністратору. "
            "Скористайся кнопкою «Звернутись в підтримку».",
        )


@router.message(FeedbackState.answering, F.text, ~F.text.startswith("/"))
async def process_feedback_answer(message: Message, state: FSMContext):
    """Обробка текстових відповідей на фідбек-анкету."""
    data = await state.get_data()
    question = data.get("question", 0)
    answers = data.get("answers", [])

    answers.append(message.text)
    question += 1

    if question < len(FEEDBACK_QUESTIONS):
        await state.update_data(question=question, answers=answers)
        await message.answer(
            FEEDBACK_QUESTIONS[question],
            parse_mode="HTML",
        )
    else:
        await message.answer(
            FEEDBACK_THANKS,
            parse_mode="HTML",
        )
        await message.answer_document(
            document=FSInputFile(FEEDBACK_BONUS_PATH),
            caption="🎁 <b>Твій бонус — PDF «9 фішок харчування для схуднення»</b>",
            parse_mode="HTML",
        )
        await mark_feedback_sent(message.from_user.id)
        await state.clear()
        await message.answer(
            "🎯 <b>Що далі?</b>\n\nОбери свій наступний крок 👇",
            reply_markup=cta_keyboard(),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("cta_"))
async def cta_handler(callback: CallbackQuery):
    """Обробка CTA кнопок — з цінами та платними опціями."""
    cta = callback.data.replace("cta_", "")

    if cta == "recipes":
        await callback.answer()
        await callback.message.answer(
            "📖 <b>Набір рецептів «Здорова Тарілка» + бонуси</b>\n\n"
            "У наборі:\n"
            "• 45 збалансованих рецептів із КБЖУ\n"
            "• 15 сніданків, 15 обідів і 15 вечерь\n"
            "• готові порції за методом Здорової Тарілки\n"
            "• трекер харчування\n"
            "• список продуктів для зручних закупівель\n\n"
            "📄 Зручний PDF — можна зберегти в телефоні або роздрукувати.\n\n"
            "💰 <b>Ціна: 299 ₴</b>",
            parse_mode="HTML",
        )
        await _confirm_admin_notification(callback, "Набір рецептів + бонуси")
        return

    if cta == "consultation":
        await callback.answer()
        await callback.message.answer(
            "💬 <b>Консультація з Тарасом</b>\n\n"
            "Персональна консультація з Тарасом Колодієм:\n"
            "• Аналіз поточного харчування\n"
            "• Індивідуальні рекомендації\n"
            "• Відповіді на питання\n\n"
            "💰 <b>Ціна: 1000 ₴</b>",
            parse_mode="HTML",
        )
        await _confirm_admin_notification(callback, "Консультація з Тарасом")
        return

    if cta == "online":
        await callback.answer()
        await callback.message.answer(
            "📱 <b>Онлайн-супровід Kolodii Fitness</b>\n\n"
            "Перейди до бота, щоб переглянути презентацію, формат роботи, "
            "вартість і залишити заявку.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="▶️ Переглянути презентацію",
                            url=ONLINE_SUPPORT_BOT_URL,
                        )
                    ]
                ]
            ),
            parse_mode="HTML",
        )
        return

    if cta == "movement":
        await callback.answer()
        await callback.message.answer(
            "🏃‍♂️ <b>Курс «Рухова активність»</b>\n\n"
            "Практичний курс, який допоможе додати більше руху у повсякденне життя, "
            "підібрати активність під свій рівень і сформувати стабільну звичку.\n\n"
            "✅ <b>Курс уже доступний.</b> Адміністратор розповість про умови та "
            "допоможе отримати доступ.",
            parse_mode="HTML",
        )
        await _confirm_admin_notification(callback, "Курс «Рухова активність»")
        return

    if cta == "contact_support":
        await callback.answer()
        await callback.message.answer(
            "🔙 <b>Підтримка</b>\n\n"
            "Якщо у тебе виникли питання або щось не працює — напиши нам.\n\n"
            "📧 Email: support@kolodii.fitness\n"
            "💬 Telegram: @Taras_Kolodii\n\n"
            "Ми відповідаємо протягом 24 годин.",
            parse_mode="HTML",
        )
        return

    await callback.answer()
    await callback.message.answer(
        "Напиши Тарасу для деталей.",
        parse_mode="HTML",
    )
