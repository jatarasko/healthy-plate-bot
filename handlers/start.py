"""Хендлер команди /start та початку курсу."""

import logging

from aiogram import Router, F
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from database import register_user, get_user
from bot_utils.keyboards import start_course_keyboard
from states import CourseState, FeedbackState
from content.course import WELCOME_MSG, FEEDBACK_QUESTIONS
from scheduler import schedule_next_day, send_block

router = Router()
logger = logging.getLogger(__name__)


@router.message(CommandStart())
async def cmd_start(message: Message):
    """Обробка команди /start — реєстрація та привітання."""
    user = message.from_user
    await register_user(
        user_id=user.id,
        username=user.username or "",
        first_name=user.first_name or "",
        last_name=user.last_name or "",
    )

    await message.answer(
        WELCOME_MSG,
        reply_markup=start_course_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "start_course")
async def start_course(callback: CallbackQuery, state: FSMContext):
    """Користувач натиснув 'Почати курс' — відправляємо перший блок."""
    user_id = callback.from_user.id
    await callback.answer("Курс розпочато! 🎉")
    await state.set_state(CourseState.viewing_day)
    await state.update_data(day=1, block_idx=0)

    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception as e:
            logger.info(f"Не вдалося прибрати кнопку старту для user {user_id}: {e}")

    try:
        await send_block(callback.bot, user_id, day=1, block_idx=0)
    except Exception as e:
        logger.error(f"Помилка відправки курсу для user {user_id}: {e}")


@router.callback_query(F.data.startswith("next_block:"))
async def next_block_handler(callback: CallbackQuery, state: FSMContext):
    """Обробка кнопки 'Далі' між блоками."""
    user_id = callback.from_user.id

    try:
        _, day_raw, block_idx_raw = callback.data.split(":")
        day = int(day_raw)
        block_idx = int(block_idx_raw)
    except (AttributeError, ValueError) as e:
        logger.error(f"Некоректний callback next_block від user {user_id}: {callback.data}, {e}")
        await callback.answer("❌ Не вдалося перейти далі. Натисни /start")
        return

    await callback.answer("✅ Чудово! Продовжуй далі.")
    await state.set_state(CourseState.viewing_day)
    await state.update_data(day=day, block_idx=block_idx)

    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception as e:
            logger.info(f"Не вдалося прибрати кнопку 'Далі' для user {user_id}: {e}")

    try:
        await send_block(callback.bot, user_id, day=day, block_idx=block_idx)
    except Exception as e:
        logger.error(f"Помилка відправки блоку {block_idx} дня {day} для user {user_id}: {e}")


@router.callback_query(F.data.startswith("schedule_day_"))
async def schedule_day_handler(callback: CallbackQuery):
    """Користувач підтвердив отримання наступного дня — заплануємо на 9:00."""
    user_id = callback.from_user.id
    day = int(callback.data.replace("schedule_day_", ""))

    try:
        schedule_next_day(callback.bot, user_id, day)
        await callback.answer(f"✅ День {day} заплановано на завтра о 9:00!")
    except Exception as e:
        logger.error(f"Помилка планування дня {day} для user {user_id}: {e}")
        await callback.answer("❌ Помилка. Спробуй ще раз або напиши /start")


@router.callback_query(F.data == "start_feedback")
async def start_feedback(callback: CallbackQuery, state: FSMContext):
    """Почати заповнення фідбек-анкети."""
    await state.set_state(FeedbackState.answering)
    await state.update_data(question=0, answers=[])
    await callback.answer("Починаємо!")
    await callback.message.answer(
        FEEDBACK_QUESTIONS[0],
        parse_mode="HTML",
    )


@router.callback_query(F.data == "pause_course")
async def pause_course(callback: CallbackQuery):
    """Користувач поставив курс на паузу."""
    await callback.answer("Курс на паузі. Повертись коли будеш готовий(-а) 💪")
    await callback.message.answer(
        "⏸ Курс призупинено. Коли будеш готовий(-а) продовжити — натисни /start"
    )


@router.message(Command("status"))
async def cmd_status(message: Message):
    """Показати поточний статус користувача."""
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Ти ще не зареєстрований(-а). Натисни /start")
        return

    day = user["current_day"]
    if day == 0:
        status = "Ти зареєстрований(-а), але ще не почав(-ла) курс."
    elif day <= 5:
        status = f"Ти на дні {day} з 5."
    else:
        status = "Ти завершив(-ла) курс! 🎉"

    await message.answer(f"📊 Твій статус:\n{status}")


@router.message(F.text, ~StateFilter(FeedbackState.answering))
async def handle_any_message(message: Message):
    """Заглушка на текстові повідомлення поза фідбек-анкетою."""
    # Ігнорувати команди (вони обробляються іншими хендлерами)
    if message.text.startswith("/"):
        return

    await message.answer(
        "📨 Усі матеріали курсу надсилаються автоматично.\n\n"
        "Ваше повідомлення залишиться непрочитаним.\n\n"
        "Якщо питання термінове — скористайся кнопкою «🔙 Звернутись в підтримку».",
        parse_mode="HTML",
    )
