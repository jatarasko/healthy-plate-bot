"""Сстан машини станів для бота."""

from aiogram.fsm.state import State, StatesGroup


class FeedbackState(StatesGroup):
    """Стан для збору фідбеку."""
    answering = State()


class CourseState(StatesGroup):
    """Стан для проходження блоків курсу."""
    viewing_day = State()
