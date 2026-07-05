"""Хендлер курсу — фідбек, CTA."""

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from database import mark_feedback_sent
from states import FeedbackState
from content.course import FEEDBACK_QUESTIONS, FEEDBACK_THANKS
from bot_utils.keyboards import feedback_keyboard, cta_keyboard

router = Router()


@router.message(FeedbackState.answering)
async def process_feedback_answer(message: Message, state: FSMContext):
    """Обробка відповідей на фідбек-анкету."""
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
        await state.clear()
        await mark_feedback_sent(message.from_user.id)
        await message.answer(
            FEEDBACK_THANKS,
            parse_mode="HTML",
        )
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
            "📖 <b>Книга рецептів «Здорова Тарілка»</b>\n\n"
            "45 рецептів здорового харчування за методом Здорової Тарілки.\n"
            "PDF-формат, зручне форматування, список продуктів.\n\n"
            "💰 <b>Ціна: 299 ₴</b>\n\n"
            "Для замовлення напишіть Тарасу @Taras_Kolodii",
            parse_mode="HTML",
        )
        return

    if cta == "consultation":
        await callback.answer()
        await callback.message.answer(
            "💬 <b>Консультація з Тарасом</b>\n\n"
            "Персональна консультація з Тарасом Колодієм:\n"
            "• Аналіз поточного харчування\n"
            "• Індивідуальні рекомендації\n"
            "• Відповіді на питання\n\n"
            "💰 <b>Ціна: 1000 ₴</b>\n\n"
            "Для запису напишіть Тарасу @Taras_Kolodii",
            parse_mode="HTML",
        )
        return

    if cta == "online":
        await callback.answer()
        await callback.message.answer(
            "📱 <b>Онлайн-супровід Kolodii Fitness</b>\n\n"
            "Повна програма: харчування + тренування + щоденні чек-іни.\n\n"
            "🥗 <b>Пакет «Харчування»</b> — 2500 ₴/міс\n"
            "   • Індивідуальний план харчування\n"
            "   • Щоденний супровід у Telegram\n"
            "   • Шпаргалки та рецепти\n\n"
            "🏆 <b>Пакет «Наставництво»</b> — 400$ / 3 міс\n"
            "   • Все з пакету «Харчування»\n"
            "   • Персональні тренування\n"
            "   • Тижневі відео-сесії з Тарасом\n"
            "   • Стратегічні сесії раз на місяць\n\n"
            "Для запису напишіть Тарасу @Taras_Kolodii",
            parse_mode="HTML",
        )
        return

    if cta == "movement":
        await callback.answer()
        await callback.message.answer(
            "🏃‍♂️ <b>Курс «Рухова активність»</b>\n\n"
            "Наразі курс у розробці. Ми повідомимо тобі, коли він буде готовий! 💪",
            parse_mode="HTML",
        )
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