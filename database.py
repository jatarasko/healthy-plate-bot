"""Робота з базою даних SQLite."""

import aiosqlite
from datetime import datetime, timedelta
from config import DATABASE_PATH, DAY_DELAY


async def init_db():
    """Ініціалізація бази даних — створення таблиць."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                current_day INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                feedback_sent INTEGER DEFAULT 0,
                payment_status INTEGER DEFAULT 0
            )
        """)
        # Безпечна міграція: додаємо payment_status, якщо його немає
        try:
            await db.execute("ALTER TABLE users ADD COLUMN payment_status INTEGER DEFAULT 0")
        except Exception:
            pass  # Стовпець вже існує
        await db.execute("""
            CREATE TABLE IF NOT EXISTS message_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                day_number INTEGER,
                message_number INTEGER,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        await db.commit()


async def register_user(user_id: int, username: str, first_name: str, last_name: str):
    """Реєстрація нового користувача або оновлення існуючого."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            INSERT INTO users (user_id, username, first_name, last_name, current_day, is_active)
            VALUES (?, ?, ?, ?, 1, 1)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                is_active = 1
        """, (user_id, username, first_name, last_name))
        await db.commit()


async def get_user(user_id: int):
    """Отримати дані користувача."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def update_user_day(user_id: int, day: int):
    """Оновити поточний день курсу користувача."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("UPDATE users SET current_day = ? WHERE user_id = ?", (day, user_id))
        await db.commit()


async def log_message(user_id: int, day_number: int, message_number: int):
    """Записати лог відправленого повідомлення."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "INSERT INTO message_log (user_id, day_number, message_number) VALUES (?, ?, ?)",
            (user_id, day_number, message_number)
        )
        await db.commit()


async def mark_feedback_sent(user_id: int):
    """Позначити, що користувач надіслав фідбек."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("UPDATE users SET feedback_sent = 1 WHERE user_id = ?", (user_id,))
        await db.commit()


async def get_all_active_users():
    """Отримати всіх активних користувачів."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE is_active = 1") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def get_users_for_day(day: int):
    """Отримати користувачів, яким потрібно відправити конкретний день."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE is_active = 1 AND current_day = ?",
            (day,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def set_payment_status(user_id: int, status: int = 1):
    """Встановити статус оплати користувача."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE users SET payment_status = ? WHERE user_id = ?",
            (status, user_id)
        )
        await db.commit()


async def get_stats():
    """Отримати статистику бота."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            total = (await cursor.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE is_active = 1") as cursor:
            active = (await cursor.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE current_day >= 5") as cursor:
            completed = (await cursor.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE feedback_sent = 1") as cursor:
            feedback = (await cursor.fetchone())[0]
        return {
            "total_users": total,
            "active_users": active,
            "completed_course": completed,
            "feedback_received": feedback,
        }
