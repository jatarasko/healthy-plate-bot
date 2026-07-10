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

# Railway Volume path (persistent storage)
# On Railway, use /data/healthy_plate.db if volume is mounted at /data
# Locally, use relative path
if os.getenv("RAILWAY_SERVICE_ID"):
    # Railway environment
    DATABASE_PATH = os.getenv("DATABASE_PATH", "/data/healthy_plate.db")
else:
    # Local environment
    DATABASE_PATH = os.getenv("DATABASE_PATH", "bot_database.db")

# ID адміністратора (Taras) — для сповіщень
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Затримка між днями курсу (в секундах)
# 86400 = 24 години. Для тестування можна поставити 60 (1 хвилина)
DAY_DELAY = int(os.getenv("DAY_DELAY", "86400"))
