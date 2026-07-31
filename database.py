"""
Робота з базою даних SQLite (з підтримкою змінних середовища та recovery).
"""
import aiosqlite
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone
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
            ("sending_started_at", "TEXT"),
            ("course_completed_at", "TEXT"),
            ("completion_notified_at", "TEXT"),
            ("next_step", "TEXT"),
            ("next_step_selected_at", "TEXT"),
            ("followup_stage", "INTEGER DEFAULT 0"),
            ("next_followup_at", "TEXT"),
            ("progress_waiting_day", "INTEGER"),
            ("progress_waiting_block", "INTEGER"),
            ("progress_reminder_stage", "INTEGER DEFAULT 0"),
            ("next_progress_reminder_at", "TEXT"),
            ("last_progress_at", "TEXT")
        ]
        for field, definition in migration_fields:
            try:
                await db.execute(f"ALTER TABLE users ADD COLUMN {field} {definition}")
                logger.info(f"Додано поле {field} до таблиці users")
            except Exception:
                pass  # Поле вже існує

        # Старих випускників показуємо в адмін-звіті, але не надсилаємо їм
        # раптові нагадування після деплою нової логіки.
        await db.execute("""
            UPDATE users
            SET course_status = 'completed',
                course_completed_at = COALESCE(last_sent_at, registered_at),
                completion_notified_at = COALESCE(completion_notified_at, CURRENT_TIMESTAMP),
                followup_stage = 2,
                next_followup_at = NULL
            WHERE last_sent_day >= 5 AND course_completed_at IS NULL
        """)
        
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


async def mark_course_completed(user_id: int) -> bool:
    """Зафіксувати завершення курсу. True повертається лише першого разу."""
    now = datetime.now(timezone.utc)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE users
            SET course_status = 'completed', course_completed_at = ?,
                followup_stage = 0, next_followup_at = ?
            WHERE user_id = ? AND course_completed_at IS NULL
            """,
            (now.isoformat(), (now + timedelta(days=1)).isoformat(), user_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def mark_completion_notified(user_id: int) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE users SET completion_notified_at = ? WHERE user_id = ?",
            (datetime.now(timezone.utc).isoformat(), user_id),
        )
        await db.commit()


async def get_unnotified_completions():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM users
               WHERE course_completed_at IS NOT NULL AND completion_notified_at IS NULL
               ORDER BY course_completed_at"""
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]


async def mark_next_step_selected(user_id: int, next_step: str) -> None:
    """Зберегти вибір учасника та вимкнути подальші нагадування."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """UPDATE users
               SET next_step = ?, next_step_selected_at = ?, next_followup_at = NULL
               WHERE user_id = ?""",
            (next_step, datetime.now(timezone.utc).isoformat(), user_id),
        )
        await db.commit()


async def get_due_completion_followups():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM users
               WHERE course_status = 'completed'
                 AND next_step_selected_at IS NULL
                 AND next_followup_at IS NOT NULL
                 AND next_followup_at <= ? AND followup_stage < 3
               ORDER BY next_followup_at""",
            (datetime.now(timezone.utc).isoformat(),),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]


async def advance_completion_followup(user_id: int, completed_stage: int) -> None:
    next_at = None
    if completed_stage in (1, 2):
        next_at = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """UPDATE users SET followup_stage = ?, next_followup_at = ?
               WHERE user_id = ? AND next_step_selected_at IS NULL""",
            (completed_stage, next_at, user_id),
        )
        await db.commit()


async def get_completed_without_next_step(limit: int = 20):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM users
               WHERE course_completed_at IS NOT NULL AND next_step_selected_at IS NULL
               ORDER BY course_completed_at DESC LIMIT ?""",
            (limit,),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]


async def set_course_progress_waiting(user_id: int, day: int, next_block: int) -> None:
    """Зафіксувати кнопку «Далі», на якій очікуємо учасника."""
    now = datetime.now(timezone.utc)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """
            UPDATE users
            SET progress_waiting_day = ?, progress_waiting_block = ?,
                progress_reminder_stage = 0, next_progress_reminder_at = ?,
                last_progress_at = ?
            WHERE user_id = ?
            """,
            (
                day,
                next_block,
                (now + timedelta(days=1)).isoformat(),
                now.isoformat(),
                user_id,
            ),
        )
        await db.commit()


async def clear_course_progress_waiting(user_id: int) -> None:
    """Скасувати нагадування, щойно учасник продовжив або завершив день."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """
            UPDATE users
            SET progress_waiting_day = NULL, progress_waiting_block = NULL,
                progress_reminder_stage = 0, next_progress_reminder_at = NULL,
                last_progress_at = ?
            WHERE user_id = ?
            """,
            (datetime.now(timezone.utc).isoformat(), user_id),
        )
        await db.commit()


async def get_due_progress_reminders():
    """Учасники, які не натиснули очікувану кнопку «Далі» вчасно."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT * FROM users
            WHERE course_status = 'active' AND is_active = 1
              AND progress_waiting_day IS NOT NULL
              AND progress_waiting_block IS NOT NULL
              AND next_progress_reminder_at IS NOT NULL
              AND next_progress_reminder_at <= ?
              AND progress_reminder_stage < 3
            ORDER BY next_progress_reminder_at
            """,
            (datetime.now(timezone.utc).isoformat(),),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]


async def advance_progress_reminder(user_id: int, completed_stage: int) -> None:
    """Наступне нагадування через 2 дні; після ескалації серія завершується."""
    next_at = None
    if completed_stage in (1, 2):
        next_at = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """
            UPDATE users
            SET progress_reminder_stage = ?, next_progress_reminder_at = ?
            WHERE user_id = ? AND progress_waiting_day IS NOT NULL
            """,
            (completed_stage, next_at, user_id),
        )
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
        async with db.execute("""
            SELECT COUNT(*) FROM users
            WHERE course_completed_at IS NOT NULL AND next_step_selected_at IS NULL
        """) as cursor:
            without_next_step = (await cursor.fetchone())[0]
        return {
            "total_users": total,
            "active_users": active,
            "completed_course": completed,
            "feedback_received": feedback,
            "without_next_step": without_next_step,
        }
