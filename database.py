"""
Робота з базою даних SQLite (з підтримкою змінних середовища та recovery).
"""
from __future__ import annotations

import aiosqlite
import json
import logging
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta, timezone
from config import DATABASE_PATH

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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS feedback_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                survey_version INTEGER NOT NULL DEFAULT 2,
                status TEXT NOT NULL DEFAULT 'started',
                started_at TEXT NOT NULL,
                completed_at TEXT,
                admin_notified_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS feedback_answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                submission_id INTEGER NOT NULL,
                question_index INTEGER NOT NULL,
                question_key TEXT NOT NULL,
                question_text TEXT NOT NULL,
                answer TEXT NOT NULL,
                answered_at TEXT NOT NULL,
                UNIQUE(submission_id, question_index),
                FOREIGN KEY (submission_id) REFERENCES feedback_submissions(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS course_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                details TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_feedback_user ON feedback_submissions(user_id, id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_course_events_type ON course_events(event_type, created_at)"
        )
        await db.commit()
        logger.info(f"✅ База даних ініціалізована. Шлях: {DATABASE_PATH}")


def create_database_backup(retain: int = 7) -> str:
    """Створити консистентну SQLite-копію на Railway Volume і лишити останні N."""
    source_path = Path(DATABASE_PATH)
    backup_dir = source_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    destination = backup_dir / f"healthy-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.sqlite3"
    with sqlite3.connect(source_path) as source, sqlite3.connect(destination) as target:
        source.backup(target)
    backups = sorted(backup_dir.glob("healthy-*.sqlite3"), key=lambda path: path.stat().st_mtime, reverse=True)
    for old in backups[retain:]:
        old.unlink()
    logger.info("Створено резервну копію: %s", destination)
    return str(destination)


async def get_delivery_health() -> dict[str, int]:
    now = datetime.now(timezone.utc)
    stale = (now - timedelta(minutes=10)).isoformat()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        result = {}
        queries = {
            "active": "SELECT COUNT(*) FROM users WHERE is_active = 1 AND course_status = 'active'",
            "scheduled": "SELECT COUNT(*) FROM users WHERE next_send_at IS NOT NULL",
            "overdue": "SELECT COUNT(*) FROM users WHERE next_send_at IS NOT NULL AND next_send_at <= ?",
            "stuck": "SELECT COUNT(*) FROM users WHERE sending_status = 'sending' AND sending_started_at <= ?",
            "waiting": "SELECT COUNT(*) FROM users WHERE progress_waiting_day IS NOT NULL",
        }
        for key, query in queries.items():
            params = (now.isoformat(),) if key == "overdue" else (stale,) if key == "stuck" else ()
            async with db.execute(query, params) as cursor:
                result[key] = (await cursor.fetchone())[0]
    return result


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

async def update_user_after_send(
    user_id: int,
    day: int,
    next_send_at: str | None = None,
):
    """Оновити статус користувача після успішної відправки дня."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        now = datetime.now().isoformat()
        await db.execute("""
            UPDATE users 
            SET current_day = ?,
                last_sent_day = ?,
                last_sent_at = ?,
                next_send_at = ?,
                sending_status = 'idle',
                sending_started_at = NULL
            WHERE user_id = ?
        """, (day, day, now, next_send_at, user_id))
        await db.commit()
        logger.info(f"Користувач {user_id}: оновлено статус після відправки дня {day}")


async def set_next_send_at(user_id: int, next_send_at: str | None) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE users SET next_send_at = ? WHERE user_id = ?",
            (next_send_at, user_id),
        )
        await db.commit()


async def get_scheduled_course_days(*, due_only: bool = False):
    """Повернути заплановані дні; SQLite є джерелом правди для розкладу."""
    params: tuple[str, ...] = ()
    due_filter = ""
    if due_only:
        due_filter = "AND users.next_send_at <= ?"
        params = (datetime.now(timezone.utc).isoformat(),)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"""
            SELECT users.user_id, users.last_sent_day + 1 AS next_day,
                   users.next_send_at
            FROM users
            WHERE users.is_active = 1
              AND users.course_status = 'active'
              AND users.last_sent_day < 5
              AND users.next_send_at IS NOT NULL
              AND users.progress_waiting_day IS NULL
              AND EXISTS (
                  SELECT 1 FROM access_grants
                  WHERE access_grants.user_id = users.user_id
              )
              {due_filter}
            ORDER BY users.next_send_at
            """,
            params,
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]


async def claim_scheduled_course_day(user_id: int, expected_send_at: str) -> bool:
    """Атомарно забрати відправлення, щоб job і safety-check не дублювали день."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE users
            SET next_send_at = NULL
            WHERE user_id = ? AND next_send_at = ?
            """,
            (user_id, expected_send_at),
        )
        await db.commit()
        return cursor.rowcount == 1

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


async def claim_sending_status(user_id: int) -> bool:
    """Не дозволити двом одночасним callback відправити той самий блок двічі."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        now = datetime.now(timezone.utc).isoformat()
        cursor = await db.execute(
            """
            UPDATE users
            SET sending_status = 'sending', sending_started_at = ?
            WHERE user_id = ? AND COALESCE(sending_status, 'idle') != 'sending'
            """,
            (now, user_id),
        )
        await db.commit()
        return cursor.rowcount == 1

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


async def record_course_event(user_id: int, event_type: str, details: dict | None = None) -> None:
    """Append-only funnel event. It never alters course progress."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "INSERT INTO course_events (user_id, event_type, details, created_at) VALUES (?, ?, ?, ?)",
            (
                user_id,
                event_type,
                json.dumps(details, ensure_ascii=False) if details else None,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await db.commit()


async def get_or_create_feedback_submission(user_id: int, survey_version: int = 2):
    """Resume an unfinished survey, or create a new durable submission."""
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM feedback_submissions
               WHERE user_id = ? AND survey_version = ?
               ORDER BY id DESC LIMIT 1""",
            (user_id, survey_version),
        ) as cursor:
            row = await cursor.fetchone()
        if row:
            submission = dict(row)
        else:
            cursor = await db.execute(
                """INSERT INTO feedback_submissions
                   (user_id, survey_version, status, started_at)
                   VALUES (?, ?, 'started', ?)""",
                (user_id, survey_version, now),
            )
            await db.commit()
            submission = {
                "id": cursor.lastrowid,
                "user_id": user_id,
                "survey_version": survey_version,
                "status": "started",
                "started_at": now,
                "completed_at": None,
                "admin_notified_at": None,
            }
        async with db.execute(
            "SELECT question_index FROM feedback_answers WHERE submission_id = ? ORDER BY question_index",
            (submission["id"],),
        ) as cursor:
            submission["answered_indexes"] = [row[0] for row in await cursor.fetchall()]
        return submission


async def save_feedback_answer(
    submission_id: int,
    question_index: int,
    question_key: str,
    question_text: str,
    answer: str,
) -> None:
    """Persist each answer immediately so a restart cannot erase the survey."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """INSERT INTO feedback_answers
               (submission_id, question_index, question_key, question_text, answer, answered_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(submission_id, question_index) DO UPDATE SET
                   answer = excluded.answer, answered_at = excluded.answered_at""",
            (
                submission_id,
                question_index,
                question_key,
                question_text,
                answer.strip(),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await db.commit()


async def complete_feedback_submission(submission_id: int, user_id: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """UPDATE feedback_submissions
               SET status = 'completed', completed_at = COALESCE(completed_at, ?)
               WHERE id = ?""",
            (now, submission_id),
        )
        await db.execute("UPDATE users SET feedback_sent = 1 WHERE user_id = ?", (user_id,))
        await db.commit()


async def get_feedback_submission(submission_id: int):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT s.*, u.username, u.first_name, u.last_name
               FROM feedback_submissions s JOIN users u ON u.user_id = s.user_id
               WHERE s.id = ?""",
            (submission_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            return None
        result = dict(row)
        async with db.execute(
            """SELECT question_index, question_key, question_text, answer, answered_at
               FROM feedback_answers WHERE submission_id = ? ORDER BY question_index""",
            (submission_id,),
        ) as cursor:
            result["answers"] = [dict(answer) for answer in await cursor.fetchall()]
        return result


async def mark_feedback_admin_notified(submission_id: int) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE feedback_submissions SET admin_notified_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), submission_id),
        )
        await db.commit()


async def get_recent_feedback(limit: int = 10):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT s.id, s.user_id, s.status, s.started_at, s.completed_at,
                      u.username, u.first_name, u.last_name,
                      COUNT(a.id) AS answer_count
               FROM feedback_submissions s
               JOIN users u ON u.user_id = s.user_id
               LEFT JOIN feedback_answers a ON a.submission_id = s.id
               GROUP BY s.id ORDER BY s.id DESC LIMIT ?""",
            (limit,),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]


async def get_unnotified_feedback(limit: int = 20):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            """SELECT id FROM feedback_submissions
               WHERE status = 'completed' AND admin_notified_at IS NULL
               ORDER BY completed_at LIMIT ?""",
            (limit,),
        ) as cursor:
            return [row[0] for row in await cursor.fetchall()]


async def get_recent_completions(limit: int = 20):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM users WHERE course_completed_at IS NOT NULL
               ORDER BY course_completed_at DESC LIMIT ?""",
            (limit,),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]


async def get_funnel_stats():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        result = {}
        for key, query in {
            "completed": "SELECT COUNT(*) FROM users WHERE course_completed_at IS NOT NULL",
            "feedback_started": "SELECT COUNT(*) FROM feedback_submissions",
            "feedback_completed": "SELECT COUNT(*) FROM feedback_submissions WHERE status = 'completed'",
            "next_step_selected": "SELECT COUNT(*) FROM users WHERE next_step_selected_at IS NOT NULL",
        }.items():
            async with db.execute(query) as cursor:
                result[key] = (await cursor.fetchone())[0]
        async with db.execute(
            "SELECT event_type, COUNT(*) FROM course_events GROUP BY event_type"
        ) as cursor:
            result["events"] = dict(await cursor.fetchall())
        return result


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
