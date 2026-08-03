import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from database import (
    claim_scheduled_course_day,
    claim_sending_status,
    get_scheduled_course_days,
    get_feedback_submission,
    get_or_create_feedback_submission,
    init_db,
    save_feedback_answer,
    set_course_progress_waiting,
    update_user_after_send,
)
import database
from scheduler import _next_day_run_time, recovery_check, send_block


class FailingBot:
    async def send_message(self, **kwargs):
        raise RuntimeError("Telegram unavailable")


class HealthyPlateDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        database.DATABASE_PATH = str(Path(self.tempdir.name) / "healthy.db")
        await init_db()
        async with database.aiosqlite.connect(database.DATABASE_PATH) as conn:
            await conn.execute(
                "INSERT INTO users (user_id, username, first_name) VALUES (301, 'test', 'Тест')"
            )
            await conn.commit()

    async def asyncTearDown(self):
        self.tempdir.cleanup()

    async def test_feedback_answer_is_persisted_immediately_and_resumable(self):
        submission = await get_or_create_feedback_submission(301)
        await save_feedback_answer(submission["id"], 0, "clarity", "Question", "5")

        resumed = await get_or_create_feedback_submission(301)
        details = await get_feedback_submission(submission["id"])
        self.assertEqual(resumed["answered_indexes"], [0])
        self.assertEqual(details["answers"][0]["answer"], "5")

    async def test_scheduled_day_is_persisted_and_claimed_once(self):
        due_at = "2000-01-01T09:00:00+00:00"
        async with database.aiosqlite.connect(database.DATABASE_PATH) as conn:
            await conn.execute(
                "INSERT INTO access_grants (user_id, token_fingerprint) VALUES (301, 'test')"
            )
            await conn.commit()
        await update_user_after_send(301, 1, next_send_at=due_at)

        due = await get_scheduled_course_days(due_only=True)
        self.assertEqual(due[0]["next_day"], 2)
        self.assertTrue(await claim_scheduled_course_day(301, due_at))
        self.assertFalse(await claim_scheduled_course_day(301, due_at))

    async def test_only_one_delivery_can_be_claimed(self):
        self.assertTrue(await claim_sending_status(301))
        self.assertFalse(await claim_sending_status(301))

    async def test_failed_block_keeps_exact_resume_position(self):
        await set_course_progress_waiting(301, 1, 1)
        await send_block(FailingBot(), 301, day=1, block_idx=1)

        user = await database.get_user(301)
        self.assertEqual(user["last_sent_day"], 0)
        self.assertEqual(user["progress_waiting_day"], 1)
        self.assertEqual(user["progress_waiting_block"], 1)
        self.assertEqual(user["sending_status"], "sending")

    def test_next_day_is_nine_oclock_in_kyiv(self):
        kyiv = ZoneInfo("Europe/Kyiv")
        run_at = _next_day_run_time(datetime(2026, 8, 3, 20, 0, tzinfo=kyiv))
        self.assertEqual(run_at.astimezone(kyiv).isoformat(), "2026-08-04T09:00:00+03:00")

    async def test_recovery_retries_failed_scheduled_day(self):
        async with database.aiosqlite.connect(database.DATABASE_PATH) as conn:
            await conn.execute(
                "INSERT INTO access_grants (user_id, token_fingerprint) VALUES (301, 'test')"
            )
            await conn.execute(
                """
                UPDATE users
                SET current_day = 1, last_sent_day = 1,
                    sending_status = 'sending', sending_started_at = '2000-01-01T00:00:00+00:00'
                WHERE user_id = 301
                """
            )
            await conn.commit()

        retry = AsyncMock()
        with patch("scheduler.send_day", retry):
            await recovery_check(FailingBot())
        retry.assert_awaited_once_with(unittest.mock.ANY, 301, 2)


if __name__ == "__main__":
    unittest.main()
