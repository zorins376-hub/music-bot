# ТЗ: BLACK ROOM RADIO BOT v3.0 — Полный Product Blueprint

## Контекст

BLACK ROOM RADIO BOT — Telegram музыкальный бот на Python (aiogram 3.15, SQLAlchemy 2.0 async, PostgreSQL, Redis). Уже реализованы: мульти-провайдер поиск (YouTube/Spotify/Yandex/VK/SoundCloud), AI DJ рекомендации (SQL-based collaborative + content-based), Weekly Recap, Daily Mix, плейлисты, избранное, чарты, Shazam-распознавание, Premium через Telegram Stars, реферальная система, i18n (RU/EN/KG), Docker deployment, Prometheus + Sentry мониторинг.

Цель — превратить утилиту-загрузчик в стриминговую платформу внутри Telegram и занять позицию продукта №1 в нише.

---

## ЭТАП 1: Глубокая интеграция с экосистемой Telegram

---

### 1.1 Telegram Mini App (TMA) Player

**Статус:** НЕ реализовано. Нет веб-фронтенда.

**Задача:** Полноценный WebApp-плеер: обложки, синхронизированный текст, плейлисты, seek-ползунок.

**Архитектура:**
- **Backend API** — FastAPI (`webapp/api.py`), endpoints:
  - `GET /api/player/state/{user_id}` — текущий трек, позиция, очередь
  - `POST /api/player/action` — play/pause/seek/next/prev
  - `GET /api/playlists/{user_id}`, `GET /api/playlist/{id}/tracks`
  - `GET /api/lyrics/{track_id}`, `GET /api/search?q=...`
  - Авторизация через Telegram WebApp `initData` (HMAC-SHA256)
- **Frontend** — Preact + Vite + Telegram WebApp JS SDK
  - Компоненты: Player, TrackList, PlaylistView, LyricsView, SearchBar, SeekSlider
  - Audio через HTML5 `<audio>` с URL файлов
  - Состояние в Redis: `player:{user_id}` → JSON
  - Поддержка тёмной/светлой темы Telegram

**Новые файлы:**
- `webapp/api.py` — FastAPI приложение (~300 строк)
- `webapp/auth.py` — верификация initData (~50 строк)
- `webapp/schemas.py` — Pydantic-схемы (~100 строк)
- `webapp/frontend/` — Preact SPA (src/App.tsx, components/Player.tsx, Lyrics.tsx, PlaylistView.tsx)
- `Dockerfile.webapp` — multi-stage build

**Изменения в существующих файлах:**
- `bot/config.py` — `TMA_URL`, `TMA_SECRET`
- `bot/handlers/start.py` — кнопка "Открыть плеер" (WebAppInfo)
- `bot/handlers/search.py` — кнопка "Открыть в плеере"
- `docker-compose.yml` — сервис `webapp`
- `nginx.conf` — location `/tma/`, `/api/`

**Зависимости:** `fastapi`, `uvicorn`, Preact, Vite, `@telegram-apps/sdk`

**Риски:** Лимит 20 MB Bot API getFile → стримить через прямые URL провайдеров. CORS → единый домен через nginx.

**Приоритет:** P1 | **Сложность:** XL | **Оценка:** 120–160 часов

**Критерии приёмки:**
- TMA открывается через WebApp-кнопку в боте
- Обложка + artist + title + seek-ползунок
- Просмотр и переключение плейлистов
- Текст песни с подсветкой текущей строки
- Поиск из TMA
- Тёмная/светлая тема

---

### 1.2 Интеграция с Telegram Stories

**Статус:** НЕ реализовано. Weekly Recap — только текст.

**Задача:** Кнопка "Поделиться в Stories" — генерация карточки 1080×1920 с обложкой, названием, QR-кодом deep-link.

**Архитектура:**
- Генерация через Pillow: градиентный фон BLACK ROOM, обложка 400×400, artist/title (Inter Bold), QR-код → `t.me/bot?start=share_{track_id}`
- Для Weekly Recap: топ-5 артистов, статистика, брендинг
- Кеш карточек в Redis (base64 PNG, TTL 24h)

**Новые файлы:**
- `bot/services/story_cards.py` (~200 строк)
- `bot/assets/story_template.png`, `bot/assets/fonts/Inter-Bold.ttf`

**Изменения:**
- `bot/services/weekly_recap.py` — генерация и отправка фото-карточки после текстового рекапа
- `bot/handlers/search.py` — кнопка "Share" в post-download клавиатуре, callback генерации карточки
- `requirements.txt` — `Pillow>=10.0.0`, `qrcode[pil]>=7.0`

**Приоритет:** P2 | **Сложность:** M | **Оценка:** 30–40 часов

**Критерии приёмки:**
- Карточка 1080×1920 с обложкой, названием, QR-кодом за < 3 сек
- Weekly Recap сопровождается визуальной карточкой
- QR-код ведёт на deep-link бота

---

### 1.3 Групповое прослушивание (Voice Chat)

**Статус:** Backend streaming есть (`streamer/voice_chat.py`, Pyrogram + pytgcalls), но нет user-facing UI, нет голосования.

**Задача:** Бот заходит в Voice Chat группы, воспроизводит музыку, пользователи голосуют за skip (like/dislike), управляют очередью.

**Архитектура:**
- `GroupSession` — состояние на группу в Redis: `vc:{group_id}:current/queue/votes`
- Голосование: dislike > 50% слушателей → skip; like > 60% → "Gold Queue"
- Рефакторинг `streamer/voice_chat.py` — поддержка нескольких групп одновременно

**Новые файлы:**
- `streamer/voice_chat_manager.py` — менеджер сессий (~300 строк)
- `bot/handlers/voice_chat.py` — команды `/play`, `/skip`, `/queue`, `/np` (~250 строк)

**Изменения:**
- `streamer/voice_chat.py` — поддержка мульти-групп
- `bot/main.py` — регистрация `voice_chat.router`
- `bot/config.py` — `VC_SKIP_THRESHOLD`, `VC_MAX_QUEUE`, `VC_MAX_SESSIONS`
- `docker-compose.yml` — раскомментировать сервис `streamer`
- `requirements.txt` — `pytgcalls>=1.0.0`, `TgCrypto`

**Риски:** Один Pyrogram session = одно подключение → отдельный userbot-аккаунт. pytgcalls нестабилен → пинить версию.

**Приоритет:** P2 | **Сложность:** L | **Оценка:** 60–80 часов

**Критерии приёмки:**
- `/play query` в группе → трек в очередь VC
- Inline-кнопки [Like] [Skip] под "Now Playing"
- 50%+ Skip → переключение трека
- `/queue` показывает очередь
- Работа в нескольких группах одновременно

---

## ЭТАП 2: Убийственные фичи (Конкурентный ров)

---

### 2.1 Prompt-to-Playlist (Generative AI)

**Статус:** НЕ реализовано (ai_playlist.py не существует в текущем коде).

**Задача:** Пользователь пишет "Собери мне плейлист на 2 часа для ночной поездки под дождём" → бот генерирует 30 треков с mood progression.

**Архитектура:**
- **OpenAI GPT-4o-mini**: промпт → JSON `{"tracks": [{"artist","title"}], "mood_arc": ["chill","building","peak","cooldown"]}`
- Поиск каждого трека: `search_local_tracks()` → multi-provider search, параллельно по 5 треков (`asyncio.gather`)
- **Fallback без OpenAI**: keyword extraction (regex жанры/настроения/артисты) → mood map → multi-source поиск
- Сортировка по BPM для mood progression

**Новые файлы:**
- `bot/services/ai_playlist.py` (~350 строк)
- `bot/handlers/ai_playlist.py` (~200 строк)

**Изменения:**
- `bot/main.py` — регистрация router
- `bot/config.py` — `OPENAI_API_KEY`, `AI_PLAYLIST_MAX_TRACKS: int = 30`
- `bot/callbacks.py` — `AIPlaylistCb`
- `bot/handlers/start.py` — кнопка "AI Плейлист" в меню
- `bot/i18n/*.json` — ключи локализации
- `requirements.txt` — `openai>=1.12.0`

**Приоритет:** P1 | **Сложность:** L | **Оценка:** 50–60 часов

**Критерии приёмки:**
- `/aigen музыка для тренировки` → плейлист 15–30 треков за < 30 сек
- Mood progression от разогрева к пику
- Кнопка "Сохранить как плейлист"
- Работает без OpenAI (fallback на keywords)

---

### 2.2 Импорт с внешних платформ

**Статус:** Spotify и Yandex URL resolve есть в провайдерах, но модуля импорта плейлистов НЕТ (import_playlist.py не существует).

**Задача:** Пользователь кидает URL плейлиста Spotify/Yandex/VK/Apple Music → бот воссоздаёт его за < 60 сек.

**Архитектура:**
- Единый интерфейс `import_playlist(url, user_id) → ImportResult`
- Детектор платформы по URL regex
- Извлечение метаданных через API каждой платформы (spotipy, yandex-music, vk_api)
- Apple Music: парсинг HTML embed-страницы (BeautifulSoup)
- Параллельный поиск батчами по 10: `asyncio.gather()`
- Progress callback: обновление сообщения "Импортирую... 15/30 треков"

**Новые файлы:**
- `bot/services/playlist_import.py` (~400 строк)
- `bot/handlers/import_playlist.py` (~150 строк)

**Изменения:**
- `bot/main.py` — регистрация router
- `bot/handlers/search.py` — детекция URL плейлистов → redirect на import handler
- `bot/models/playlist.py` — новое поле `source_url` в Playlist
- `requirements.txt` — `beautifulsoup4>=4.12.0`, `lxml>=5.0.0`

**Приоритет:** P1 | **Сложность:** M | **Оценка:** 35–45 часов

**Критерии приёмки:**
- Импорт из Spotify, Yandex, VK, Apple Music
- 30 треков за < 60 секунд
- Progress bar в сообщении
- Ненайденные треки пропускаются с уведомлением
- Лимит 100 треков на импорт

---

### 2.3 Voice AI DJ (TTS-комментарии)

**Статус:** НЕ реализовано. Нет TTS-движка.

**Задача:** Между треками в Daily Mix — аудио-вставки: "Привет, {name}! Ты слушал Kendrick на этой неделе, вот свежий релиз. Поехали!"

**Архитектура:**
- **Primary TTS**: `edge-tts` (бесплатный, голос `ru-RU-DmitryNeural`)
- **Fallback**: `gTTS` (Google TTS)
- **Premium**: OpenAI TTS API
- Шаблоны комментариев: JSON с 50+ вариациями, контекстные (user profile, time of day, listening history)
- Кеш: Redis `tts:{hash(text)}` → file_id (TTL 30 дней)
- Интеграция: в Daily Mix после каждого 3-го трека, в Radio/VC каждые 5 треков

**Новые файлы:**
- `bot/services/tts_engine.py` (~200 строк)
- `bot/services/dj_comments.py` (~150 строк)
- `bot/assets/dj_templates.json` (50+ шаблонов)

**Изменения:**
- `bot/handlers/mix.py` — вставка TTS между треками
- `bot/services/daily_mix.py` — поле `dj_comment` в track dict
- `streamer/voice_chat.py` — TTS-файлы между треками
- `bot/config.py` — `TTS_ENGINE: str = "edge"`, `OPENAI_TTS_ENABLED: bool = False`
- `requirements.txt` — `edge-tts>=6.1.0`, `gTTS>=2.3.0`

**Приоритет:** P2 | **Сложность:** M | **Оценка:** 35–45 часов

**Критерии приёмки:**
- TTS-комментарий после каждого 3-го трека в Daily Mix
- Персонализация (имя, контекст из профиля)
- Генерация < 5 сек, кеширование
- Настройка вкл/выкл в `/settings`

---

## ЭТАП 3: Алгоритмы и удержание

---

### 3.1 ML-модели рекомендаций

**Статус:** SQL-based collaborative filtering в `recommender/ai_dj.py` (312 строк). Нет ML.

**Задача:** Заменить SQL на ML: Implicit ALS (matrix factorization) + track embeddings (Word2Vec).

**Архитектура:**
- **ALS** (`implicit` library): матрица user×track (кол-во прослушиваний), обучение ночью
- **Track Embeddings** (`gensim` Word2Vec): последовательности прослушиваний как "предложения"
- **Hybrid Scorer**: ALS×0.5 + Embedding similarity×0.3 + Popularity×0.2
- Diversity filter: ≤3 треков одного артиста
- Training pipeline: cron ночью, модель на диск `data/models/als_model.npz`
- Fallback: текущий SQL при < 50 прослушиваний или отсутствии модели

**Новые файлы:**
- `recommender/train.py` — pipeline обучения (~250 строк)
- `recommender/embeddings.py` — track embeddings (~150 строк)
- `recommender/scorer.py` — hybrid scoring (~100 строк)
- `recommender/model_store.py` — save/load (~50 строк)

**Изменения:**
- `recommender/ai_dj.py` — использовать trained model если доступна, fallback на SQL
- `bot/main.py` — scheduler для ночного обучения
- `bot/config.py` — `ML_MODEL_PATH`, `ML_RETRAIN_HOUR: int = 3`
- `requirements.txt` — `implicit>=0.7.0`, `scipy>=1.11.0`, `gensim>=4.3.0`

**Приоритет:** P1 | **Сложность:** XL | **Оценка:** 80–100 часов

**Критерии приёмки:**
- ML-модель обучается ночью автоматически (< 5 мин для 100K записей)
- Рекомендации через ML для пользователей с 50+ прослушиваний
- Fallback на SQL при отсутствии модели
- Diversity: ≤3 треков одного артиста
- Модель персистится при перезапуске (volume mount)

---

### 3.2 Расширение геймификации

**Статус:** achievements.py и badges.py НЕ существуют в текущем коде. Нужно создавать с нуля.

**Задача:** Система badges (15+), XP/уровни, лидерборды, streaks.

**Архитектура:**
- **Achievement Engine** (`bot/services/achievements.py`): реестр badges с lambda-условиями
  - `first_play` (1+ play), `meloman_10/100/500`, `first_playlist`, `first_like`, `genre_explorer` (5 жанров), `night_owl` (10 ночных plays), `streak_7/30`, `referral_3`, `top_1_percent`, `social_butterfly` (10 shares), `premium_supporter`
  - `check_achievements(user_id)` — вызывается после play/like/share/playlist create
- **Leaderboard** (`bot/services/leaderboard.py`): Redis sorted sets `lb:weekly:{week}`, `lb:alltime`
- **XP система**: play +1, like +2, share +3, playlist create +5

**Новые файлы:**
- `bot/services/achievements.py` (~300 строк)
- `bot/services/leaderboard.py` (~150 строк)
- `bot/handlers/badges.py` (~200 строк)
- `bot/models/achievement.py` — модель earned achievements

**Модели данных:**
- Таблица `achievements`: `id`, `user_id` (FK), `badge_id` (String), `earned_at` — UniqueConstraint(user_id, badge_id)
- Новые поля в `User`: `xp` (int), `level` (int), `streak_days` (int), `last_play_date` (date)

**Изменения:**
- `bot/main.py` — регистрация router
- `bot/handlers/search.py` — `check_achievements()` после play
- `bot/handlers/favorites.py` — `check_achievements()` после like
- `bot/handlers/playlist.py` — `check_achievements()` после create
- `bot/handlers/start.py` — кнопка "Достижения" в меню
- `bot/models/base.py` — импорт Achievement в `init_db()`

**Приоритет:** P2 | **Сложность:** L | **Оценка:** 50–60 часов

**Критерии приёмки:**
- 15+ badges, уведомление при получении
- `/badges` — earned (с датой) и locked (с прогрессом)
- `/leaderboard` — топ-50 за неделю/all-time
- Streak считается корректно (пропуск дня = сброс)

---

## ЭТАП 4: Монетизация и экономика

---

### 4.1 Расширение Telegram Stars

**Статус:** Premium есть (`bot/handlers/premium.py`, 210 строк): 150 Stars/30d, trial 50 Stars/7d, FLAC 5 Stars, no-ads 3 Stars.

**Задача:** Bundle-тарифы, подарочный Premium, промокоды.

**Архитектура:**
- Новые тарифы: Premium 90d (350 Stars, −22%), Premium 365d (1000 Stars, −44%), FLAC bundle 10 (40 Stars, −20%)
- Gift Premium: покупка подписки для другого пользователя по username
- Промокоды: таблица `promo_codes`, команда `/promo CODE`, admin `/admin promo create`
- Авто-напоминание за 3 дня до окончания Premium

**Новые файлы:**
- `bot/models/promo_code.py`

**Модели данных:**
- `promo_codes`: `id`, `code` (unique), `promo_type`, `uses_left`, `max_uses`, `expires_at`, `created_by`, `created_at`
- `promo_activations`: `id`, `promo_id` (FK), `user_id` (FK), `activated_at`

**Изменения:**
- `bot/handlers/premium.py` — bundle тарифы, gift, promo
- `bot/handlers/admin.py` — управление промокодами

**Приоритет:** P2 | **Сложность:** S | **Оценка:** 20–25 часов

---

### 4.2 Premium-экосистема

**Задача:** Cloud history (безлимит vs 30 дней), priority queue при нагрузке, feature flags.

**Новые файлы:**
- `bot/services/feature_flags.py` (~100 строк)

**Изменения:**
- `bot/handlers/history.py` — WHERE `created_at > 30d` для non-premium
- `bot/middlewares/throttle.py` — priority bypass для premium
- `bot/handlers/admin.py` — управление feature flags

**Приоритет:** P3 | **Сложность:** M | **Оценка:** 25–30 часов

---

### 4.3 B2B: Продвижение инди-артистов

**Статус:** НЕ реализовано.

**Задача:** Sponsored tracks в рекомендациях с меткой [Promo], дашборд артиста, оплата Stars.

**Новые файлы:**
- `bot/models/sponsored.py`
- `bot/services/sponsored_engine.py` (~200 строк)
- `bot/handlers/promote.py` (~250 строк)

**Модели данных:**
- `sponsored_campaigns`: `id`, `user_id`, `track_id`, `budget_stars`, `spent_stars`, `impressions_total`, `clicks_total`, `target_genres` (JSON), `status`, `approved_by`, `created_at`
- `sponsored_events`: `id`, `campaign_id`, `user_id`, `event_type` (impression/click), `created_at`

**Изменения:**
- `recommender/ai_dj.py` — вставка sponsored track на позицию 3–5
- `bot/main.py` — регистрация promote router

**Приоритет:** P3 | **Сложность:** L | **Оценка:** 50–60 часов

---

## ЭТАП 5: Безопасность и выживаемость

---

### 5.1 DMCA-устойчивость

**Статус:** blocked_track.py и dmca_filter.py НЕ существуют. Нужно создавать с нуля.

**Задача:** In-memory фильтр заблокированных треков, авто-поиск альтернатив (cover/live), процесс апелляции.

**Архитектура:**
- In-memory Set из `blocked_tracks` для O(1) проверки
- `find_alternative(artist, title)` — YouTube search `"{title}" cover/live`
- Admin: `/admin block`, `/admin unblock`, `/admin dmca list`
- Appeal: кнопка "Оспорить" → тикет admin

**Новые файлы:**
- `bot/models/blocked_track.py` (~40 строк)
- `bot/services/dmca_filter.py` (~250 строк)

**Модели данных:**
- `blocked_tracks`: `id`, `source_id` (unique, index), `reason`, `blocked_by`, `alternative_source_id`, `created_at`
- `dmca_appeals`: `id`, `user_id`, `blocked_track_id` (FK), `reason`, `status`, `reviewed_by`, `created_at`

**Изменения:**
- `bot/handlers/search.py` — проверка `is_blocked()` перед отправкой, предложение альтернативы
- `bot/handlers/admin.py` — команды block/unblock
- `bot/main.py` — preload blocked tracks в `on_startup`
- `bot/models/base.py` — импорт BlockedTrack

**Приоритет:** P1 | **Сложность:** M | **Оценка:** 30–40 часов

**Критерии приёмки:**
- Admin блокирует трек → in-memory set обновляется без перезагрузки
- При скачивании заблокированного → предложение альтернативы
- Пользователь может оспорить блокировку
- Admin-лог фиксирует DMCA-действия

---

### 5.2 Bot Fleet / Шардинг

**Статус:** Один инстанс бота. Нет механизма распределения.

**Задача:** Dispatcher-бот → mirror-ботов, общая DB, миграция при бане.

**Архитектура:**
- **Dispatcher Bot** (`bot/dispatcher_bot.py`): `/start` → hash(user_id) % num_nodes → deep-link на node-бот
- **Node Bot**: текущий бот со своим BOT_TOKEN, общая DB/Redis
- Redis: `node:{node_id}:status` (active/banned), healthcheck heartbeat 30 сек
- **Migration**: при бане → рассылка "Бот переехал → @music_node2_bot", обновление маршрутизации

**Новые файлы:**
- `bot/dispatcher_bot.py` (~200 строк)
- `bot/services/node_manager.py` (~250 строк)
- `Dockerfile.dispatcher`

**Изменения:**
- `bot/config.py` — `NODE_ID`, `DISPATCHER_TOKEN`, `NODE_TOKENS`
- `bot/main.py` — регистрация node в Redis при startup
- `docker-compose.yml` — dispatcher + несколько node-сервисов

**Приоритет:** P2 | **Сложность:** XL | **Оценка:** 80–100 часов

**Критерии приёмки:**
- 2+ node-бота с общей DB
- Dispatcher корректно маршрутизирует
- При бане node → миграция за 5 минут
- Данные сохраняются при миграции

---

### 5.3 Инфраструктурная устойчивость

**Статус:** Нет proxy rotation. yt-dlp через прямое подключение.

**Задача:** Proxy pool для yt-dlp/Yandex, детекция IP-бана, auto-failover провайдеров.

**Архитектура:**
- **Proxy Pool** (`bot/services/proxy_pool.py`): env `PROXY_POOL=socks5://ip1:port,...`
- Round-robin с healthcheck каждые 60 сек
- yt-dlp: ротация proxy на каждый запрос
- IP ban detection: 429/403 → переключить proxy, backoff 60 сек
- Auto-disable provider при health < 0.3 (используя существующий `provider_health.py`), автовосстановление

**Новые файлы:**
- `bot/services/proxy_pool.py` (~200 строк)

**Изменения:**
- `bot/services/downloader.py` — proxy в `_base_opts()` из proxy pool
- `bot/services/yandex_provider.py` — proxy для HTTP-запросов
- `bot/services/provider_health.py` — auto-disable при low health
- `bot/config.py` — `PROXY_POOL`, `PROXY_HEALTH_CHECK_INTERVAL`
- `bot/handlers/admin.py` — `/admin proxy status`

**Приоритет:** P1 | **Сложность:** L | **Оценка:** 40–50 часов

**Критерии приёмки:**
- Proxy rotation для yt-dlp и Yandex
- Автопереключение при IP-бане за 1 запрос
- `/admin proxy status` — статус прокси
- Provider auto-disable при health < 0.3, автовосстановление

---

## Сводная таблица

| # | Задача | Этап | Приоритет | Сложность | Часы | Зависимости |
|---|--------|------|-----------|-----------|------|-------------|
| 5.1 | DMCA-устойчивость | 5 | **P1** | M | 30–40 | — |
| 5.3 | Proxy rotation & infra | 5 | **P1** | L | 40–50 | Proxy-провайдеры |
| 2.2 | Импорт плейлистов | 2 | **P1** | M | 35–45 | beautifulsoup4, lxml |
| 2.1 | AI Prompt-to-Playlist | 2 | **P1** | L | 50–60 | OpenAI API |
| 3.1 | ML-рекомендации | 3 | **P1** | XL | 80–100 | implicit, gensim, scipy |
| 1.1 | TMA Player | 1 | **P1** | XL | 120–160 | FastAPI, Preact, nginx |
| 1.2 | Stories Integration | 1 | P2 | M | 30–40 | Pillow, qrcode |
| 1.3 | Group Listening VC | 1 | P2 | L | 60–80 | pytgcalls, Pyrogram |
| 2.3 | Voice AI DJ (TTS) | 2 | P2 | M | 35–45 | edge-tts |
| 3.2 | Геймификация/Badges | 3 | P2 | L | 50–60 | — |
| 4.1 | Stars Enhancement | 4 | P2 | S | 20–25 | — |
| 5.2 | Bot Fleet/Sharding | 5 | P2 | XL | 80–100 | Multi-bot tokens |
| 4.2 | Premium-экосистема | 4 | P3 | M | 25–30 | — |
| 4.3 | B2B Artist Promo | 4 | P3 | L | 50–60 | — |
| | **ИТОГО** | | | | **705–895** | |

## Рекомендуемый порядок реализации

**Фаза 1 (Фундамент, P1):**
1. 5.1 DMCA-устойчивость → базовая правовая защита
2. 5.3 Proxy rotation → стабильность скачивания
3. 2.2 Импорт плейлистов → снижение порога входа

**Фаза 2 (Killer Features, P1):**
4. 2.1 AI Prompt-to-Playlist → WOW-фактор
5. 3.1 ML-рекомендации → долгосрочное удержание

**Фаза 3 (UX-прорыв, P1-P2):**
6. 1.1 TMA Player → стриминговая платформа
7. 1.2 Stories → виральный охват
8. 2.3 Voice AI DJ → эмоциональная привязанность

**Фаза 4 (Рост и монетизация, P2-P3):**
9. 3.2 Геймификация → engagement loop
10. 4.1 Stars Enhancement → revenue
11. 1.3 Group Listening → социальное вовлечение
12. 5.2 Bot Fleet → масштабирование

**Фаза 5 (Зрелость, P3):**
13. 4.2 Premium-экосистема
14. 4.3 B2B Artist Promo

## Верификация

Для каждой задачи:
1. Юнит-тесты для сервисов (pytest + pytest-asyncio)
2. Ручное тестирование через бота в dev-среде
3. Мониторинг через Prometheus metrics и Sentry
4. Нагрузочное тестирование для критичных компонентов (proxy pool, ML training, TMA API)

## Критические файлы проекта

- `bot/main.py` — точка входа, регистрация всех router'ов (строки 310–328)
- `bot/models/base.py` — init_db(), все модели должны быть импортированы здесь
- `bot/config.py` — все env vars через Pydantic BaseSettings
- `bot/handlers/search.py` — центральный pipeline доставки треков (~600 строк)
- `recommender/ai_dj.py` — рекомендательный движок (312 строк)
- `bot/services/cache.py` — Redis cache wrapper
- `bot/callbacks.py` — все CallbackData классы
- `docker-compose.yml` — оркестрация сервисов
