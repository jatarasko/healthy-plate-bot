# Telegram Bot — "Здорова Тарілка"

## Опис
5-денний курс з здорового харчування у Telegram. Бот автоматично надсилає повідомлення кожного дня після реєстрації.

## Стек
- Python 3.11+
- aiogram 3.x
- aiosqlite (SQLite)
- APScheduler (розклад повідомлень)

## Структура
```
healthy_plate_bot/
├── main.py              # Точка входу, запуск бота
├── config.py            # Завантаження конфігурації
├── database.py          # Робота з SQLite
├── scheduler.py         # Розклад відправки повідомлень
├── handlers/
│   ├── start.py         # /start — реєстрація, привітання
│   ├── course.py        # Відправка днів курсу
│   └── feedback.py      # Фідбек-анкета
├── content/
│   └── course.py        # Контент курсу (62 повідомлення)
├── utils/
│   └── keyboards.py     # Клавіатури та кнопки
├── requirements.txt
├── .env
└── README.md
```

## Запуск
```bash
pip install -r requirements.txt
python main.py
```

## Команди бота
- `/start` — почати курс
- `/day1` — отримати День 1 (для тестування)
- `/status` — статус користувача
