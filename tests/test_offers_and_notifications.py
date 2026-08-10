import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import admin_notifications
from bot_utils.keyboards import cta_keyboard
from content.offers import MOVEMENT_OFFER, NEXT_STEP_INTRO


class AdminNotificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_course_bot_token_is_used_when_admin_bot_token_is_missing(self):
        fake_bot = SimpleNamespace(
            send_message=AsyncMock(),
            session=SimpleNamespace(close=AsyncMock()),
        )
        with (
            patch.object(admin_notifications, "ADMIN_ID", 123),
            patch.object(admin_notifications, "ADMIN_BOT_TOKEN", ""),
            patch.object(admin_notifications, "BOT_TOKEN", "course-bot-token"),
            patch.object(admin_notifications, "Bot", return_value=fake_bot) as bot_class,
        ):
            self.assertTrue(await admin_notifications.send_admin_message("Заявка"))

        bot_class.assert_called_once()
        self.assertEqual(bot_class.call_args.args[0], "course-bot-token")
        fake_bot.send_message.assert_awaited_once_with(123, "Заявка")
        fake_bot.session.close.assert_awaited_once()


class OfferPresentationTests(unittest.TestCase):
    def test_next_step_copy_does_not_diagnose_the_participant(self):
        self.assertNotIn("найбільше заважає", NEXT_STEP_INTRO.lower())
        self.assertNotIn("застряг", NEXT_STEP_INTRO.lower())
        self.assertIn("не обов’язок", NEXT_STEP_INTRO.lower())

    def test_movement_offer_reflects_the_five_day_course(self):
        for topic in ("п’ятиденний", "ходьби", "силових вправ", "рухових пауз", "власну просту систему"):
            self.assertIn(topic, MOVEMENT_OFFER)
        self.assertLessEqual(len(MOVEMENT_OFFER), 4096)

    def test_next_step_buttons_are_result_oriented(self):
        labels = [row[0].text for row in cta_keyboard().inline_keyboard]
        self.assertIn("🏃 Додати більше руху", labels)
        self.assertNotIn("🏃 Хочу більше рухатись", labels)


if __name__ == "__main__":
    unittest.main()
