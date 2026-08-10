"""Конфігурація бота — завантаження змінних середовища."""

import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не знайдено в .env файлі")

# Database configuration
# For Railway PostgreSQL: set DATABASE_URL
# For local SQLite: set DATABASE_PATH or use default
DATABASE_URL = os.getenv("DATABASE_URL")

# Railway Volume path (persistent storage).
# У production Volume змонтовано як директорію /healthy_plate.db.
if os.getenv("RAILWAY_SERVICE_ID"):
    # Не використовуємо застарілий DATABASE_PATH=/data/...: ця директорія
    # належить контейнеру й очищається під час кожного деплою.
    DATABASE_PATH = "/healthy_plate.db/healthy_plate.db"
else:
    DATABASE_PATH = os.getenv("DATABASE_PATH", "bot_database.db")

# ID адміністратора (Taras) — для сповіщень
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
ACCESS_TOKEN_SECRET = os.getenv("ACCESS_TOKEN_SECRET", "").strip()
if len(ACCESS_TOKEN_SECRET.encode("utf-8")) < 32:
    raise ValueError("ACCESS_TOKEN_SECRET має містити щонайменше 32 байти")
SALES_BOT_USERNAME = os.getenv("SALES_BOT_USERNAME", "").strip().lstrip("@")
SUPPORT_TELEGRAM_USERNAME = os.getenv(
    "SUPPORT_TELEGRAM_USERNAME", "Taras_Kolodii"
).strip().lstrip("@")

# Затримка між днями курсу (в секундах)
# 86400 = 24 години. Для тестування можна поставити 60 (1 хвилина)
DAY_DELAY = int(os.getenv("DAY_DELAY", "86400"))
