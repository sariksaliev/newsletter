# TG Outreach Platform

Автоматизация Telegram-аутрича: покупка аккаунтов → прогрев → парсинг ЦА → рассылка → диалоговый бот → заявка → продажа. Всё в одном серверном пайплайне без TG Master / GramGPT.

---

## Что это и зачем

**Было (AS-IS):** несколько программ, ручной прогрев, ручной ретрай спама, слабый бот, аналитика в Excel.

**Стало (TO-BE):** одна платформа на Windows VPS, которая:

1. Принимает Telegram-аккаунты (`.session` файлы)
2. Сама настраивает профиль, прогревает, парсит лидов, рассылает
3. Ведёт диалог через Claude (свой промпт)
4. Считает воронку и шлёт продажнику уведомление при заявке

---

## Как всё работает (схема)

```
Импорт аккаунта (.session)
        │
        ▼
┌───────────────────┐
│  Блок A           │  прокси → LLM-профиль (имя/био/аватар/сторис)
│  Инфраструктура   │  → N-дневный прогрев (каналы, реакции, переписка)
└─────────┬─────────┘
          │  status: active
          ▼
┌───────────────────┐
│  Блок B           │  парсинг каналов/ключевых слов → база лидов
│  Парсинг +        │  → spintax-рассылка → спам-детект → авто-ретрай
│  рассылка         │
└─────────┬─────────┘
          │  лид ответил
          ▼
┌───────────────────┐
│  Блок C           │  Claude-бот ведёт диалог, разбирает голосовые
│  Диалоговый бот   │  → горячий лид → статус «заявка»
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│  Блок D           │  дашборд воронки, CPL/CAC
│  Аналитика + CRM  │  → push продажнику + SLA 24ч
└───────────────────┘
```

---

## Что нужно перед запуском

| Что | Где взять | Зачем |
|-----|-----------|-------|
| `TELEGRAM_API_ID` + `TELEGRAM_API_HASH` | https://my.telegram.org | Подключение к Telegram через Telethon |
| `ANTHROPIC_API_KEY` | console.anthropic.com | LLM-профили + диалоговый бот |
| `OPENAI_API_KEY` | platform.openai.com | Транскрипция голосовых (опционально) |
| `.session` файлы | Telethon / готовые аккаунты | Авторизация аккаунтов рассылки |
| SOCKS5-прокси (IPv4) | Провайдер прокси | 1 IP на ≤3 аккаунта, страна = стране номера |
| `SALES_TELEGRAM_BOT_TOKEN` + `CHAT_ID` | @BotFather | Уведомления продажнику (опционально) |

---

## Быстрый старт (Windows)

### Вариант 1 — одной командой

```powershell
cd c:\Users\salig\OneDrive\Desktop\tz
.\start.ps1
```

Скрипт сам: создаст `.venv`, поставит зависимости, создаст `.env` (если нет), сделает `seed`, запустит сервер.

### Вариант 2 — вручную

```powershell
cd tz
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# Отредактировать .env — вписать ключи API
python run.py seed
python run.py serve
```

**Важно:** запускать через `.venv\Scripts\python`, а не системный `python` — иначе будет `ModuleNotFoundError: No module named 'fastapi'`.

### Куда заходить после запуска

| URL | Что там |
|-----|---------|
| http://localhost:8000 | Дашборд воронки |
| http://localhost:8000/docs | Swagger — все API-методы с кнопками «Try it out» |
| http://localhost:8000/api/health | Проверка что сервер жив |

### Третий процесс — входящие сообщения

В **отдельном** терминале (пока `serve` работает):

```powershell
.venv\Scripts\activate
python run.py listener
```

Слушает ответы лидов в Telegram и передаёт их диалоговому боту.

---

## Настройка `.env` — что означает каждая переменная

```env
# База данных (SQLite для dev, Postgres для prod)
DATABASE_URL=sqlite+aiosqlite:///./data/outreach.db

# Telegram API — обязательно
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=your_api_hash

# Claude — профили + диалоговый бот
ANTHROPIC_API_KEY=sk-ant-...
DIALOG_MODEL=claude-sonnet-4-20250514

# Whisper — расшифровка голосовых (опционально)
OPENAI_API_KEY=sk-...

# Push продажнику при заявке (опционально)
SALES_TELEGRAM_BOT_TOKEN=
SALES_TELEGRAM_CHAT_ID=

# Прогрев
WARMUP_DAYS=3                    # сколько дней прогревать новый аккаунт
WARMUP_CHANNELS_PER_DAY=5        # подписок на каналы в день
WARMUP_MESSAGES_PER_DAY=6        # сообщений взаимной переписки
WARMUP_REACTIONS_PER_DAY=5       # реакций на посты в день
WARMUP_BROWSE_MESSAGES=15        # сколько постов «листать» в канале

# Рассылка
OUTREACH_DAILY_LIMIT_PER_ACCOUNT=4   # сообщений с одного акка в день
OUTREACH_MIN_DELAY_SEC=45             # пауза между сообщениями (мин)
OUTREACH_MAX_DELAY_SEC=180            # пауза между сообщениями (макс)

# Анти-связность профилей
MAX_PROFILE_EDITS_PER_HOUR=5          # не больше 5 правок профиля в час (глобально)
PROFILE_EDIT_JITTER_MIN_SEC=900       # задержка перед правкой: от 15 мин
PROFILE_EDIT_JITTER_MAX_SEC=7200      # задержка перед правкой: до 120 мин

# Прокси
MAX_ACCOUNTS_PER_PROXY=3              # макс. аккаунтов на один IPv4
```

---

## Пошаговый workflow — что делать руками

### Шаг 0. Запустить платформу

```powershell
.\start.ps1
# или: python run.py serve
```

### Шаг 1. Добавить прокси

Через Swagger (`/docs`) или curl:

```http
POST /api/proxies
Content-Type: application/json

{
  "host": "1.2.3.4",
  "port": 1080,
  "country": "RU",
  "username": "user",
  "password": "pass",
  "proxy_type": "socks5"
}
```

Страна прокси должна совпадать со страной номера телефона аккаунта.

### Шаг 2. Импортировать аккаунт

1. Положить `.session` файл в `data/sessions/` (например `79001234567.session`)
2. Вызвать API:

```http
POST /api/accounts/import

{
  "phone": "+79001234567",
  "session_file_path": "data/sessions/79001234567.session",
  "cost_rub": 280
}
```

**Что произойдёт автоматически (0 ручных действий):**

```
imported → proxy_bound → profile_pending
    ↓ (через 15–120 мин, 1 аккаунт за раз)
  LLM генерирует имя/био/юзернейм/дату рождения
    ↓
  Загружает аватар + публикует сторис
    ↓
  warming (3 дня: каналы, реакции, листание, переписка)
    ↓
  ready → active (готов к рассылке)
```

Проверить статус: `GET /api/accounts`

### Шаг 3. Парсинг целевой аудитории

```http
POST /api/parse/channel   {"channel": "target_channel", "limit": 1000}
POST /api/parse/keyword   {"keyword": "маркетинг", "limit": 200}
```

Лиды попадают в общую базу со статусом `new`. Дубликаты отсекаются автоматически.

Проверить: `GET /api/leads?status=new`

### Шаг 4. Рассылка

Вручную:

```http
POST /api/outreach/send?batch_size=20
```

Или автоматически: планировщик шлёт каждые 30 мин с 9:00 до 18:00.

Что делает рассылка:
- Spintax: `{Привет|Здравствуйте}, {name}!`
- Имитация печати перед отправкой
- Случайные задержки 45–180 сек
- Ротация аккаунтов (≤4 сообщения/день с аккаунта)
- При спам-блоке: аккаунт на паузу, лид уходит в retry с другого аккаунта

### Шаг 5. Диалог с лидами

Запустить listener (отдельный терминал):

```powershell
python run.py listener
```

Когда лид отвечает → бот (Claude) ведёт диалог → при интересе создаёт заявку → push продажнику.

Тест через API (без Telegram):

```http
POST /api/dialog/message

{"lead_id": 1, "message": "Сколько стоит?", "is_voice": false}
```

### Шаг 6. A/B тесты офферов

```http
POST /api/ab-variants

{
  "name": "variant_a",
  "outreach_template": "{Привет|Hi} {name}! ...",
  "system_prompt": "Ты менеджер... Ссылка: {bot_link}",
  "bot_link": "https://t.me/your_bot",
  "weight": 50
}
```

Статистика: `GET /api/ab-variants/stats`

### Шаг 7. Смотреть аналитику

| Endpoint | Что показывает |
|----------|----------------|
| `GET /api/analytics/funnel?days=30` | Полная воронка + CPL/CAC |
| `GET /api/analytics/daily?days=14` | Помесячная динамика |
| `GET /api/accounts/mortality?days=30` | Смертность аккаунтов (цель <10%) |
| `GET /api/outreach/delivery-rate?days=7` | Доставка (цель >85%) |
| http://localhost:8000 | Визуальный дашборд |

---

## Жизненный цикл аккаунта

| Статус | Значение |
|--------|----------|
| `imported` | Только что загружен |
| `proxy_bound` | Прокси назначен |
| `profile_pending` | Ждёт очереди на LLM-профиль (джиттер 15–120 мин) |
| `warming` | Идёт прогрев (N дней) |
| `ready` | Прогрев завершён |
| `active` | Рассылает сообщения |
| `spam_paused` | Ушёл в спам, на паузе |
| `quarantine` | Ошибка, нужна проверка |
| `dead` | Забанен / мёртв |

## Жизненный цикл лида

| Статус | Значение |
|--------|----------|
| `new` | Спарсен, ещё не писали |
| `written` | Отправили outreach |
| `replied` | Лид ответил |
| `in_bot` | Идёт диалог с ботом |
| `application` | Заявка — продажник уведомлён |
| `call` | Назначен созвон |
| `sale` | Продажа |
| `lost` | Недоступен / отказ |

---

## Фоновые задачи (планировщик)

Работают автоматически при `python run.py serve`:

| Задача | Когда | Что делает |
|--------|-------|------------|
| Онбординг | каждые 15 мин | 1 профиль за раз (имя, аватар, сторис) + активация готовых |
| Прогрев | ежедневно 10:00 | Каналы, реакции, листание, переписка |
| Рассылка | 9:00–18:00, /30 мин | Batch outreach по новым и retry-лидам |
| SLA | каждые 15 мин | Проверка: продажник связался за 24ч? |

Принудительный запуск:

```http
POST /api/accounts/onboarding/run
POST /api/warmup/run
POST /api/outreach/send?batch_size=20
```

---

## Блоки системы (код)

| Блок | Модули | Что решает |
|------|--------|------------|
| **A** | `account_manager`, `warmup`, `proxy_manager`, `profile_generator` | Боль #1, #4, #5 — смертность, VPS, ручной прогрев |
| **B** | `parser`, `outreach` | Боль #2, #3 — спам, два софта |
| **C** | `dialog_bot` | Боль #6 — слабый бот |
| **D** | `analytics`, `notifications` | Боль #7, #8 — аналитика, медленные лиды |

---

## Критерии готовности (из ТЗ)

| KPI | Цель | Как проверить |
|-----|------|---------------|
| Смертность аккаунтов | <10% | `GET /api/accounts/mortality?days=30` |
| Доставка сообщений | >85% | `GET /api/outreach/delivery-rate?days=7` |
| 0 ручных действий | после импорта `.session` | Импорт → ждать → `active` |
| CPL / CAC онлайн | автоматически | Дашборд `/` |
| Качество бота | A/B конверсия | `GET /api/ab-variants/stats` |

> KPI достигаются на **реальных** аккаунтах с прокси и ключами — код даёт инструменты, цифры зависят от качества аккаунтов.

---

## Docker (PostgreSQL для prod)

```bash
docker-compose up -d
```

В `.env`:

```
DATABASE_URL=postgresql+asyncpg://outreach:outreach@localhost:5432/outreach
```

---

## Структура проекта

```
tz/
├── src/
│   ├── main.py                 # FastAPI + дашборд
│   ├── config.py               # Настройки из .env
│   ├── models/entities.py      # Account, Lead, FunnelEvent, ...
│   ├── services/
│   │   ├── account_manager.py  # Импорт, онбординг, смертность
│   │   ├── profile_generator.py# LLM-профиль, аватар, сторис, джиттер
│   │   ├── warmup.py           # Прогрев: каналы, реакции, переписка
│   │   ├── proxy_manager.py    # Прокси ≤3 акка/IPv4
│   │   ├── parser.py           # Парсинг каналов и ключевых слов
│   │   ├── outreach.py         # Рассылка, spintax, спам-детект
│   │   ├── dialog_bot.py       # Claude-бот, голосовые, A/B
│   │   ├── analytics.py        # Воронка, CPL/CAC
│   │   └── notifications.py    # Push продажнику + SLA
│   ├── api/routes.py           # REST API
│   ├── workers/
│   │   ├── scheduler.py        # Фоновые задачи
│   │   └── inbound_listener.py # Слушатель входящих
│   └── web/templates/          # HTML-дашборд
├── data/
│   ├── outreach.db             # SQLite база (создаётся автоматически)
│   ├── sessions/               # .session файлы аккаунтов
│   └── avatars/                # Сгенерированные аватары и сторис
├── scripts/seed.py             # Начальные A/B и конфиг рассылки
├── run.py                      # CLI: serve | seed | listener
├── start.ps1                   # One-click запуск (Windows)
├── requirements.txt
└── docker-compose.yml
```

---

## Частые проблемы

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `No module named 'fastapi'` | Запуск без venv | `.venv\Scripts\activate` или `.\start.ps1` |
| `Account is not authorized` | Битый/просроченный `.session` | Пересоздать session через Telethon |
| `No active account available for parsing` | Нет аккаунта в статусе `active`/`ready` | Дождаться прогрева или `POST /api/warmup/run` |
| `No available proxy` | Нет прокси нужной страны | `POST /api/proxies` с правильным `country` |
| Sales notification not configured | Пустые токены в `.env` | Заполнить `SALES_TELEGRAM_*` |
| Порт 8000 занят | Другой процесс | Сменить `APP_PORT` в `.env` |

---

## Важно

- Массовый outreach нарушает ToS Telegram — система рассчитана на «расходные» аккаунты.
- Нужны валидные Telethon `.session` файлы для каждого аккаунта.
- `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` — с https://my.telegram.org
- Для prod: Windows VPS 24/7, `serve` + `listener` в двух процессах (или через systemd/Task Scheduler).

---

## Для проверки (фаундер / ревьюер)

**В GitHub только код** — секреты не коммитятся (`.env` в `.gitignore`).

```powershell
git clone https://github.com/sariksaliev/newsletter.git
cd newsletter
copy .env.example .env
# Заполнить .env своими ключами (или получить у автора отдельно, не из Git)
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py seed
python run.py serve
```

Проверка **без** реальных Telegram-аккаунтов:

| Что проверить | Как |
|---------------|-----|
| API жив | http://localhost:8000/api/health |
| Swagger / эндпоинты | http://localhost:8000/docs |
| Дашборд воронки | http://localhost:8000 |
| Smoke-тест | `python run.py test` (нужны `SALES_TELEGRAM_*`) |
| Блоки A–D | `src/services/` + таблица блоков в README |
| KPI из ТЗ | `/api/accounts/mortality`, `/api/outreach/delivery-rate` |

Полный E2E (рассылка, парсинг) — `.session` + прокси + ключи в `.env` (**передаются вне GitHub**).
