"""Хендлер курсу — фідбек, CTA."""

from __future__ import annotations

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

from config import ADMIN_ID, SALES_BOT_USERNAME, SUPPORT_TELEGRAM_USERNAME
from admin_notifications import send_admin_message
from database import (
    complete_feedback_submission,
    get_feedback_submission,
    get_or_create_feedback_submission,
    mark_feedback_admin_notified,
    mark_next_step_selected,
    record_course_event,
    save_feedback_answer,
)
from states import FeedbackState
from content.course import FEEDBACK_QUESTIONS, FEEDBACK_QUESTION_KEYS, FEEDBACK_THANKS
from content.offers import MOVEMENT_OFFER, NEXT_STEP_INTRO
from bot_utils.keyboards import cta_keyboard, feedback_answer_keyboard

router = Router()
logger = logging.getLogger(__name__)

FEEDBACK_BONUS_PATH = (
    Path(__file__).resolve().parent.parent / "assets" / "9_fishok_premium_guide.pdf"
)
SALES_BOT = SALES_BOT_USERNAME or "Kolo_Dii_bot"


def _sales_url(product_code: str) -> str:
    return f"https://t.me/{SALES_BOT}?start={product_code}-after_plate"


async def _ask_feedback_question(target: Message, question_index: int) -> None:
    await target.answer(
        FEEDBACK_QUESTIONS[question_index],
        reply_markup=feedback_answer_keyboard(question_index),
        parse_mode="HTML",
    )


async def _notify_admin_feedback(bot, submission_id: int) -> bool:
    submission = await get_feedback_submission(submission_id)
    if not ADMIN_ID or not submission or submission.get("admin_notified_at"):
        return bool(submission)
    name = html.escape(" ".join(
        part for part in (submission.get("first_name"), submission.get("last_name")) if part
    ) or "Без імені")
    username = html.escape(f"@{submission['username']}") if submission.get("username") else "не вказано"
    lines = [
        "📝 <b>Новий відгук — «Здорова Тарілка»</b>",
        "",
        f"Учасник: <a href=\"tg://user?id={submission['user_id']}\">{name}</a>",
        f"Username: {username}",
        f"Telegram ID: <code>{submission['user_id']}</code>",
        f"Анкета: <code>#{submission_id}</code>",
        "",
    ]
    for answer in submission["answers"]:
        lines.append(f"<b>{answer['question_index'] + 1}.</b> {html.escape(answer['answer'])}")
    try:
        if await send_admin_message("\n".join(lines)):
            await mark_feedback_admin_notified(submission_id)
            return True
        return False
    except Exception:
        logger.exception("Не вдалося надіслати відгук #%s адміну", submission_id)
        return False


async def _finish_feedback(
    message: Message, state: FSMContext, submission_id: int, user_id: int
) -> None:
    await complete_feedback_submission(submission_id, user_id)
    await record_course_event(user_id, "feedback_completed", {"submission_id": submission_id})
    await _notify_admin_feedback(message.bot, submission_id)
    await message.answer(FEEDBACK_THANKS, parse_mode="HTML")
    await message.answer_document(
        document=FSInputFile(FEEDBACK_BONUS_PATH),
        caption="🎁 <b>Твій бонус — PDF «9 фішок харчування для схуднення»</b>",
        parse_mode="HTML",
    )
    await state.clear()
    await message.answer(
        NEXT_STEP_INTRO,
        reply_markup=cta_keyboard(),
        parse_mode="HTML",
    )


async def _store_feedback_answer(
    message: Message,
    state: FSMContext,
    answer: str,
    expected_question: int | None = None,
    user_id: int | None = None,
) -> None:
    data = await state.get_data()
    question = int(data.get("question", 0))
    submission_id = data.get("submission_id")
    if submission_id is None or (expected_question is not None and expected_question != question):
        await message.answer("Ця відповідь уже збережена. Продовж із останнього запитання.")
        return
    if not answer.strip() or len(answer.strip()) > 400:
        await message.answer("Напиши, будь ласка, коротку відповідь — до 400 символів.")
        return
    await save_feedback_answer(
        int(submission_id),
        question,
        FEEDBACK_QUESTION_KEYS[question],
        FEEDBACK_QUESTIONS[question],
        answer,
    )
    actual_user_id = user_id or message.from_user.id
    await record_course_event(actual_user_id, "feedback_answered", {"question": question})
    question += 1
    if question < len(FEEDBACK_QUESTIONS):
        await state.update_data(question=question)
        await _ask_feedback_question(message, question)
    else:
        await _finish_feedback(message, state, int(submission_id), actual_user_id)


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
        return await send_admin_message(
            "🔔 <b>Нова заявка після курсу «Здорова Тарілка»</b>\n\n"
            f"Продукт: <b>{html.escape(offer_name)}</b>\n"
            f"Користувач: <a href=\"tg://user?id={user.id}\">{safe_name}</a>\n"
            f"Username: {safe_username}\n"
            f"Telegram ID: <code>{user.id}</code>",
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
    await _store_feedback_answer(message, state, message.text)


@router.callback_query(F.data == "start_feedback")
async def start_feedback(callback: CallbackQuery, state: FSMContext):
    """Почати або без втрат продовжити коротку анкету."""
    submission = await get_or_create_feedback_submission(callback.from_user.id)
    if submission["status"] == "completed":
        await callback.answer("Відгук уже збережено ✅", show_alert=True)
        return
    answered = set(submission["answered_indexes"])
    question = next((idx for idx in range(len(FEEDBACK_QUESTIONS)) if idx not in answered), len(FEEDBACK_QUESTIONS))
    await state.set_state(FeedbackState.answering)
    await state.update_data(question=question, submission_id=submission["id"])
    await record_course_event(callback.from_user.id, "feedback_started", {"submission_id": submission["id"]})
    await callback.answer("Починаємо!")
    if question < len(FEEDBACK_QUESTIONS):
        await _ask_feedback_question(callback.message, question)


@router.callback_query(FeedbackState.answering, F.data.startswith("feedback_answer:"))
async def process_feedback_button(callback: CallbackQuery, state: FSMContext):
    _, question_raw, answer_raw = callback.data.split(":", 2)
    answer_labels = {
        "meal_ideas": "Хочу легко розуміти, що готувати",
        "movement": "Хочу більше рухатись",
        "consistency": "Хочу стабільно тримати режим",
        "personal": "Хочу особистий план",
    }
    await callback.answer("Відповідь збережено")
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await _store_feedback_answer(
            callback.message,
            state,
            answer_labels.get(answer_raw, answer_raw),
            int(question_raw),
            callback.from_user.id,
        )


@router.callback_query(F.data.startswith("cta_"))
async def cta_handler(callback: CallbackQuery):
    """Обробка CTA кнопок — з цінами та платними опціями."""
    cta = callback.data.replace("cta_", "")

    offer_names = {
        "recipes": "Набір рецептів + бонуси",
        "consultation": "Консультація з Тарасом",
        "online": "Онлайн-супровід Kolodii Fitness",
        "movement": "Курс «Рухова активність»",
        "contact_support": "Звернення в підтримку",
    }
    if cta in offer_names:
        await mark_next_step_selected(callback.from_user.id, offer_names[cta])
        await record_course_event(callback.from_user.id, "offer_clicked", {"offer": cta})

    if cta == "recipes":
        await callback.answer()
        await callback.message.answer(
            "📖 <b>Щоб щодня не вигадувати, що приготувати</b>\n\n"
            "Книга перетворює принцип тарілки на готові рішення: обираєш страву, "
            "готуєш за рецептом і одразу бачиш збалансовану порцію.\n\n"
            "У комплекті:\n"
            "• 45 збалансованих рецептів із КБЖУ\n"
            "• 15 сніданків, 15 обідів і 15 вечерь\n"
            "• готові порції за методом Здорової Тарілки\n"
            "• трекер харчування\n"
            "• список продуктів для зручних закупівель\n\n"
            "📄 Зручний PDF — можна зберегти в телефоні або роздрукувати.\n\n"
            "Результат — менше хаосу в харчуванні та простіші закупівлі.\n\n"
            "💰 <b>Ціна: 299 ₴</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="Дізнатись деталі й замовити", url=_sales_url("book_tracker"))
            ]]),
            parse_mode="HTML",
        )
        await _confirm_admin_notification(callback, "Набір рецептів + бонуси")
        return

    if cta == "consultation":
        await callback.answer()
        await callback.message.answer(
            "💬 <b>Коли загальні поради не відповідають саме твоїй ситуації</b>\n\n"
            "На консультації ми знайдемо головну причину, що стримує результат, "
            "і складемо реалістичний план дій під твій режим.\n\n"
            "• Аналіз поточного харчування\n"
            "• Індивідуальні рекомендації\n"
            "• Відповіді на питання\n\n"
            "Ти підеш із чітким розумінням, що робити далі й на чому не витрачати сили.\n\n"
            "💰 <b>Ціна: 1000 ₴</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="Записатись на консультацію", url=_sales_url("consultation"))
            ]]),
            parse_mode="HTML",
        )
        await _confirm_admin_notification(callback, "Консультація з Тарасом")
        return

    if cta == "online":
        await callback.answer()
        await callback.message.answer(
            "📱 <b>Коли знань достатньо, але самостійно важко тримати регулярність</b>\n\n"
            "Онлайн-супровід дає план, контроль, зворотний зв’язок і корекцію дій. "
            "Тобі не потрібно щоразу вирішувати все самому(-ій) — ми послідовно "
            "будуємо систему, яку можна втримати в реальному житті.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Переглянути формат і залишити заявку",
                            url=_sales_url("online_support"),
                        )
                    ]
                ]
            ),
            parse_mode="HTML",
        )
        await _notify_admin_about_interest(callback, "Онлайн-супровід Kolodii Fitness")
        return

    if cta == "movement":
        await callback.answer()
        await callback.message.answer(
            MOVEMENT_OFFER,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="Переглянути курс і залишити заявку", url=_sales_url("course_active"))
            ]]),
            parse_mode="HTML",
        )
        await _confirm_admin_notification(callback, "Курс «Рухова активність»")
        return

    if cta == "contact_support":
        await callback.answer()
        await callback.message.answer(
            "🔙 <b>Підтримка</b>\n\n"
            "Якщо виникли питання або щось не працює — напиши Тарасу в Telegram.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="💬 Написати Тарасу",
                    url=f"https://t.me/{SUPPORT_TELEGRAM_USERNAME}",
                )
            ]]),
            parse_mode="HTML",
        )
        return

    await callback.answer()
    await callback.message.answer(
        "Напиши Тарасу для деталей.",
        parse_mode="HTML",
    )
