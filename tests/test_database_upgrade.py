import tempfile
import unittest
from pathlib import Path

from database import (
    get_feedback_submission,
    get_or_create_feedback_submission,
    init_db,
    save_feedback_answer,
)
import database


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


if __name__ == "__main__":
    unittest.main()
