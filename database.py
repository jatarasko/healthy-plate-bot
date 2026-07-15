"""
Робота з базою даних SQLite (з підтримкою змінних середовища та recovery).
"""
import aiosqlite
import logging
from pathlib import Path
from datetime import datetime, timedelta
from config import DATABASE_PATH, DAY_DELAY

logger = logging.getLogger(__name__)

# Створюємо директорію, якщо вона не існує (для Railway Volume)
db_dir = Path(DATABASE_PATH).parent
if not db_dir.exists():
    try:
        db_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Створено директорію для бази даних: {db_dir}")
    except Exception as e:
        logger.error(f"Не вдалося створити директорію {db_dir}: {e}")

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
                payment_status INTEGER DEFAULT 0,
                last_sent_day INTEGER DEFAULT 0,
                last_sent_at TEXT,
                next_send_at TEXT,
                course_status TEXT DEFAULT 'active',
                sending_status TEXT DEFAULT 'idle',
                sending_started_at TEXT
            )
        """)
        # Безпечна міграція: додаємо нові поля, якщо їх немає
        migration_fields = [
            ("payment_status", "INTEGER DEFAULT 0"),
            ("last_sent_day", "INTEGER DEFAULT 0"),
            ("last_sent_at", "TEXT"),
            ("next_send_at", "TEXT"),
            ("course_status", "TEXT DEFAULT 'active'"),
            ("sending_status", "TEXT DEFAULT 'idle'"),
            ("sending_started_at", "TEXT")
        ]
        for field, definition in migration_fields:
            try:
                await db.execute(f"ALTER TABLE users ADD COLUMN {field} {definition}")
                logger.info(f"Додано поле {field} до таблиці users")
            except Exception:
                pass  # Поле вже існує
        
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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS access_grants (
                user_id INTEGER PRIMARY KEY,
                token_fingerprint TEXT NOT NULL,
                granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()
        logger.info(f"✅ База даних ініціалізована. Шлях: {DATABASE_PATH}")


async def grant_course_access(user_id: int, token_fingerprint: str) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """
            INSERT INTO access_grants (user_id, token_fingerprint)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                token_fingerprint = excluded.token_fingerprint,
                granted_at = CURRENT_TIMESTAMP
            """,
            (user_id, token_fingerprint),
        )
        await db.execute(
            "UPDATE users SET is_active = 1, course_status = 'active' WHERE user_id = ?",
            (user_id,),
        )
        await db.commit()


async def has_course_access(user_id: int) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM access_grants WHERE user_id = ?", (user_id,)
        ) as cursor:
            return await cursor.fetchone() is not None


async def revoke_course_access(user_id: int) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("DELETE FROM access_grants WHERE user_id = ?", (user_id,))
        await db.execute(
            "UPDATE users SET is_active = 0, course_status = 'revoked' WHERE user_id = ?",
            (user_id,),
        )
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

async def update_user_after_send(user_id: int, day: int):
    """Оновити статус користувача після успішної відправки дня."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        now = datetime.now().isoformat()
        next_time = (datetime.now() + timedelta(seconds=DAY_DELAY)).isoformat()
        await db.execute("""
            UPDATE users 
            SET current_day = ?,
                last_sent_day = ?,
                last_sent_at = ?,
                next_send_at = ?,
                sending_status = 'idle',
                sending_started_at = NULL
            WHERE user_id = ?
        """, (day, day, now, next_time, user_id))
        await db.commit()
        logger.info(f"Користувач {user_id}: оновлено статус після відправки дня {day}")

async def set_sending_status(user_id: int, status: str):
    """Встановити статус відправки (для захисту від дублікатів)."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        now = datetime.now().isoformat() if status == 'sending' else None
        await db.execute("""
            UPDATE users 
            SET sending_status = ?, sending_started_at = ?
            WHERE user_id = ?
        """, (status, now, user_id))
        await db.commit()

async def get_users_for_recovery():
    """Отримати користувачів, яким потрібно надіслати пропущені дні."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        # Шукаємо користувачів, де current_day > last_sent_day + 1 (пропущений день)
        # Або тих, хто має статус 'sending' більше 10 хвилин (завислі)
        async with db.execute("""
            SELECT * FROM users 
            WHERE is_active = 1 
            AND course_status = 'active'
            AND EXISTS (
                SELECT 1 FROM access_grants
                WHERE access_grants.user_id = users.user_id
            )
            AND (
                current_day > last_sent_day + 1 
                OR (sending_status = 'sending' AND sending_started_at < ?)
            )
        """, ((datetime.now() - timedelta(minutes=10)).isoformat(),)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

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
        async with db.execute("""
            SELECT * FROM users
            WHERE is_active = 1
              AND EXISTS (
                  SELECT 1 FROM access_grants
                  WHERE access_grants.user_id = users.user_id
              )
        """) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def get_users_for_day(day: int):
    """Отримати користувачів, яким потрібно відправити конкретний день."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT * FROM users
            WHERE is_active = 1 AND current_day = ?
              AND EXISTS (
                  SELECT 1 FROM access_grants
                  WHERE access_grants.user_id = users.user_id
              )
            """,
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
