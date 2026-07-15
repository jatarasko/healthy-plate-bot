# Інструкція з деплою на Railway

## Підготовка
1. Переконайтеся, що у вас є акаунт на [Railway](https://railway.app/).
2. Встановіть `railway` CLI: `npm install -g @railway/cli`.
3. Залогіньтеся: `railway login`.

## Крок 1: GitHub
1. Створіть новий репозиторій на GitHub.
2. Завантажте туди проєкт `healthy_plate_bot` (всі файли, крім `.env` та `*.db`).
3. Переконайтеся, що у репо є файли: `Procfile`, `requirements.txt`, `railway.json`.

## Крок 2: Railway Project
1. Зайдіть у Railway Dashboard.
2. Натисніть "New Project".
3. Оберіть "Deploy from GitHub repo".
4. Виберіть ваш репозитарій.

## Крок 3: База даних (PostgreSQL)
1. У Railway Project натисніть "New".
2. Оберіть "Database" -> "PostgreSQL".
3. Після створення перейдіть у "Variables" вкладку.
4. Скопіюйте `DATABASE_URL` (він з'явиться автоматично).
5. **MVP:** Якщо не хочете налаштовувати PostgreSQL зараз, пропустіть цей крок. Бот використовуватиме SQLite (`data/bot.db`).

## Крок 4: Змінні середовища (Environment Variables)
1. Перейдіть у "Variables" вашого проєкту.
2. Додайте змінні згідно з `.env.example`:
   - `BOT_TOKEN` — токен від @BotFather.
   - `ADMIN_ID` — ваш Telegram ID.
   - `ACCESS_TOKEN_SECRET` — той самий секрет щонайменше 32 байти, що й у боті продажів.
   - `SALES_BOT_USERNAME` — username бота продажів без `@`.
   - `DATABASE_URL` — (опціонально) якщо додали PostgreSQL.
   - `TIMEZONE` — `Europe/Kyiv`.
   - `COURSE_START_MODE` — `manual`.
   - `PAYMENT_ENABLED` — `false`.

## Крок 5: Деплой
1. Railway автоматично розпочне деплой після додавання змінних.
2. Перевірте "Deployments" -> "Logs", щоб переконатися, що бот запустився.
3. У логах має бути: `INFO:__main__:Бот запущений! Очікування повідомлень...`

Звичайний `/start` не відкриває курс. Доступ активується персональним підписаним
посиланням після підтвердження оплати. Для перенесення старих покупців
використовуйте `/grant_access TELEGRAM_ID`, для відкликання —
`/revoke_access TELEGRAM_ID`.

## Крок 6: Перевірка
1. Знайдіть вашого бота в Telegram.
2. Натисніть `/start`.
3. Переконайтеся, що бот відповідає.

## Примітки
- Для MVP використовується SQLite. Для продакшну рекомендується PostgreSQL.
- Якщо виникли помилки, перевірте "Logs" у Railway.
