# Supabase AI — Рекомендательный движок Music Bot

Вынесенный на **Supabase** AI-сервис для рекомендаций, AI-плейлистов и аналитики.
Полностью заменяет локальный `recommender/` модуль, убирая нужду в тяжёлых Python ML-библиотеках на Railway.

## Архитектура

```
┌─────────────────────────────────────────────────────────────────┐
│                        Supabase Cloud                           │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  PostgreSQL   │  │   pgvector   │  │      pg_cron         │  │
│  │  + RLS        │  │  (1536-dim)  │  │  (scheduled jobs)    │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
│         │                 │                      │              │
│  ┌──────┴─────────────────┴──────────────────────┴───────────┐  │
│  │                    Edge Functions                          │  │
│  │                                                            │  │
│  │  /recommend      — гибридные рекомендации (5 компонентов) │  │
│  │  /ai-playlist    — генерация плейлиста по промпту (GPT)   │  │
│  │  /ingest         — приём событий прослушивания             │  │
│  │  /embed-tracks   — генерация эмбеддингов (OpenAI)         │  │
│  │  /similar        — поиск похожих треков                    │  │
│  │  /update-profile — пересчёт вкусового профиля             │  │
│  │  /analytics      — A/B тесты, статистика                  │  │
│  └────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │ HTTPS (REST API)
                              ▼
                    ┌──────────────────┐
                    │   Music Bot      │
                    │   (Railway)      │
                    │                  │
                    │   supabase_ai.py │
                    │   (Python client)│
                    └──────────────────┘
```

## Компоненты скоринга

| # | Компонент | Вес | Описание |
|---|-----------|-----|----------|
| 1 | **Embedding similarity** | 0.35 | Cosine similarity между вкусовым вектором пользователя и эмбеддингом трека (OpenAI text-embedding-3-small, 1536-dim, pgvector HNSW) |
| 2 | **Popularity** | 0.20 | Нормализованное количество скачиваний |
| 3 | **Freshness** | 0.15 | Экспоненциальный бонус для новых треков (затухание 30 дней) |
| 4 | **Genre match** | 0.15 | 1.0 если жанр в топ-5 пользователя, иначе 0.3 |
| 5 | **Time-of-day** | 0.10 | Бонус если текущий час совпадает с preferred_hours |
| 6 | **Diversity** | 0.05 | Не более 2 треков одного артиста |

## Автоматические задачи (pg_cron)

- **Каждые 4 часа**: пересчёт профилей активных пользователей
- **Каждые 10 минут**: генерация эмбеддингов для новых треков
- **Ежедневно в 3:00 UTC**: очистка старых логов рекомендаций

## Деплой

### 1. Создать проект на Supabase

Идём на [supabase.com](https://supabase.com), создаём новый проект.

### 2. Установить Supabase CLI

```bash
npm install -g supabase
```

### 3. Подключить и задеплоить

```bash
cd supabase-ai

# Привязать к проекту
supabase link --project-ref YOUR_PROJECT_REF

# Применить миграции (создаст таблицы, функции, индексы)
supabase db push

# Установить секреты для Edge Functions
supabase secrets set OPENAI_API_KEY=sk-xxx

# Задеплоить все Edge Functions
supabase functions deploy recommend
supabase functions deploy ai-playlist
supabase functions deploy ingest
supabase functions deploy embed-tracks
supabase functions deploy similar
supabase functions deploy update-profile
supabase functions deploy analytics
```

### 4. Настроить бот

В `.env` бота добавить:

```env
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
SUPABASE_AI_ENABLED=true
```

Бот автоматически переключится на Supabase AI вместо локального `recommender/`.

## API Endpoints

### GET `/recommend?user_id=123&limit=10`

Возвращает AI-рекомендации.

```json
{
  "recommendations": [
    {
      "track_id": 1,
      "source_id": "yt_xxx",
      "title": "Track Name",
      "artist": "Artist",
      "score": 0.87,
      "algo": "hybrid",
      "components": {
        "embed": 0.92,
        "pop": 0.75,
        "fresh": 0.60,
        "genre": 1.0,
        "time": 0.5
      }
    }
  ]
}
```

### POST `/ai-playlist`

AI-генерация плейлиста по текстовому описанию.

```json
// Request
{ "user_id": 123, "prompt": "грустный плейлист на вечер", "limit": 10 }

// Response
{ "playlist": [...], "count": 10, "method": "ai" }
```

### POST `/ingest`

Приём событий прослушивания.

```json
{
  "event": "play",
  "user_id": 123,
  "track": { "source_id": "yt_xxx", "title": "...", "artist": "..." },
  "listen_duration": 180,
  "source": "search"
}
```

### GET `/similar?source_id=yt_xxx&limit=10`

Похожие треки через pgvector.

### GET `/analytics?days=7`

A/B тесты, покрытие эмбеддингов, статистика.

## Стоимость

| Tier | БД | Edge Functions | Подходит для |
|------|----|----------------|--------------|
| **Free** | 500 MB, pgvector ✅ | 500K invocations/mo | До ~1,000 пользователей |
| **Pro** ($25/mo) | 8 GB, pg_cron ✅ | 2M invocations/mo | До ~50,000 пользователей |

OpenAI embeddings: ~$0.02 за 1M токенов (text-embedding-3-small) — практически бесплатно.
