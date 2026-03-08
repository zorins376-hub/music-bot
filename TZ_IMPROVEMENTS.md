# BLACK ROOM Music Bot - Полный аудит и ТЗ на улучшения

## ЧАСТЬ 1: РЕЗУЛЬТАТЫ АУДИТА

---

### 1.1 КРИТИЧЕСКИЕ БАГИ

#### BUG-001: Race condition при проверке размера файла
**Файл:** `bot/handlers/search.py:562-574`
**Проблема:** После фоллбэка на 128 kbps файл проверяется на размер, но если и 128 kbps > 45MB — функция вернёт `return`, но `mp3_path` уже был перезаписан. В `_group_auto_play` аналогичная проблема (строки 370-379).
**Риск:** Файл удаляется в `finally`, но пользователь не получает трек и не получает понятного сообщения.

#### BUG-002: Динамическая регистрация админов только в памяти
**Файл:** `bot/db.py:71-72`
```python
if admin and tg_user.id not in settings.ADMIN_IDS:
    settings.ADMIN_IDS.append(tg_user.id)
```
**Проблема:** При username-based авторизации ID добавляется в `ADMIN_IDS` в памяти. При рестарте бота — теряется. Если username сменится — старый ID всё ещё в памяти.
**Риск:** Непредсказуемое поведение админки.

#### BUG-003: Yandex token rotation при ошибке расходует 2 токена
**Файл:** `bot/services/yandex_provider.py`
**Проблема:** `search_yandex()` вызывает `_next_token()` (строка 106), и при ошибке удаляет клиент из кэша (строка 133). Следующий вызов `download_yandex()` вызывает `_next_token()` снова (строка 139) — это уже следующий токен. Один и тот же трек ищется одним токеном, а скачивается другим.
**Риск:** Неравномерная нагрузка на токены, быстрый расход лимитов.

#### BUG-004: Плейлист — отсутствует проверка владельца при удалении трека
**Проблема:** Нет валидации что `track_id` принадлежит плейлисту текущего пользователя.
**Риск:** Потенциальное удаление треков из чужих плейлистов при угадывании ID.

#### BUG-005: Premium status inconsistency
**Файл:** `bot/db.py:45-50`
**Проблема:** Если `is_premium=True` но `premium_until=NULL` — premium никогда не истечёт (кроме админов).
**Риск:** Вечный премиум для пользователей при ручной установке через DB.

---

### 1.2 ПРОБЛЕМЫ ПОИСКА

| # | Проблема | Файл | Влияние |
|---|----------|------|---------|
| S-001 | Нет fuzzy matching — опечатки = 0 результатов | `db.py:204` | Высокое |
| S-002 | ILIKE '%query%' без full-text search — O(n) scan | `db.py:206-224` | Среднее (рост данных) |
| S-003 | Каскадный поиск последовательный — 6 источников один за другим | `search.py:201-267` | Высокое (латентность) |
| S-004 | Нет дедупликации между источниками — один трек может показаться дважды | `search.py` | Среднее |
| S-005 | Title cleaning regex не покрывает emoji, Unicode-символы, "Remastered", "Remix" | `downloader.py:48-75` | Низкое |
| S-006 | Inline query поиск только YouTube, без Yandex/Spotify/VK | `inline.py:22` | Среднее |
| S-007 | Нет query suggestion / "Вы имели в виду...?" | — | Среднее |
| S-008 | Нет кэширования результатов Yandex и Spotify (только YouTube/SoundCloud кэшируются через query cache) | `search.py:237-245` | Среднее |
| S-009 | Результат поиска обрезается по 40 символов без учёта Unicode | `search.py:106` | Низкое |

---

### 1.3 ПРОБЛЕМЫ АРХИТЕКТУРЫ И КОДА

| # | Проблема | Файл | Критичность |
|---|----------|------|-------------|
| A-001 | Circular imports: search ↔ playlist, recognize → search | handlers/ | Средняя |
| A-002 | Magic numbers разбросаны по коду (60s cleanup, 10min captcha, 120s cache, etc.) | Везде | Низкая |
| A-003 | Дублирование `_fmt_duration()` в 3 файлах | downloader.py, search.py, yandex_provider.py | Низкая |
| A-004 | `_post_download()` делает inline import моделей и recommender | search.py:631-641 | Средняя |
| A-005 | ThreadPoolExecutor(max_workers=4) для yt-dlp — при 100+ юзерах будет bottleneck | downloader.py:16 | Высокая |
| A-006 | Нет graceful shutdown для ThreadPoolExecutor'ов | downloader.py, spotify_provider.py, vk_provider.py | Средняя |
| A-007 | Все handler'ы используют `async_session()` напрямую вместо через db.py | search.py:633 | Средняя |
| A-008 | Redis fail-open позволяет DDoS при падении Redis | cache.py:114-115 | Высокая |

---

### 1.4 ПРОБЛЕМЫ БЕЗОПАСНОСТИ

| # | Проблема | Критичность |
|---|----------|-------------|
| SEC-001 | CAPTCHA: 39 возможных ответов (1+1=2...20+20=40), brute-force за секунды | Средняя |
| SEC-002 | Нет лимита попыток CAPTCHA — бот может бесконечно пробовать | Средняя |
| SEC-003 | Admin commands без rate limiting и без audit log | Средняя |
| SEC-004 | VK/Yandex/Spotify токены в plain text .env — нет ротации | Низкая (стандартно для ботов) |
| SEC-005 | Нет валидации `video_id` перед подстановкой в URL | Низкая |
| SEC-006 | `tempfile.mktemp()` в recognize.py — race condition (TOCTOU) | Низкая |

---

### 1.5 ПРОБЛЕМЫ ПРОИЗВОДИТЕЛЬНОСТИ

| # | Проблема | Файл | Влияние |
|---|----------|------|---------|
| P-001 | Нет индекса на `listening_history(user_id, action, created_at)` | models/track.py | Высокое при росте |
| P-002 | `get_user_stats()` — 3 отдельных запроса вместо одного | db.py:160-201 | Среднее |
| P-003 | NullPool для PostgreSQL — новое соединение на каждый запрос | models/base.py | Среднее |
| P-004 | `bot_me = await message.bot.me()` на каждое сообщение в группе | search.py:447 | Высокое в группах |
| P-005 | JSON сериализация/десериализация для каждого search session | cache.py:49-64 | Низкое |
| P-006 | `download_vk()` читает весь файл в память (`await resp.read()`) | vk_provider.py:101 | Среднее (большие файлы) |

---

### 1.6 НЕЗАВЕРШЁННЫЕ ФИЧИ

| Фича | Статус | Файл |
|-------|--------|------|
| AI DJ рекомендации | Заглушка, возвращает [] | recommender/ai_dj.py |
| Parser каналов (Pyrogram) | Отключён | parser/ |
| Voice chat streaming | Не реализован | streamer/ |
| Экспорт плейлистов | Отсутствует | — |
| GDPR: экспорт данных пользователя | Отсутствует | — |

---

## ЧАСТЬ 2: ТЕХНИЧЕСКОЕ ЗАДАНИЕ НА УЛУЧШЕНИЯ

---

### ПРИОРИТЕТ 1 — КРИТИЧЕСКИЕ (P0)

---

#### TASK-001: Умный поиск с fuzzy matching и дедупликацией

**Цель:** Пользователь находит трек даже при опечатках, транслитерации, неполном запросе.

**Текущее поведение:**
- `ILIKE '%query%'` — не находит при опечатках
- 6 источников опрашиваются последовательно
- Дубликаты между источниками не фильтруются

**Требуемое поведение:**

1. **Нормализация запроса:**
   - Транслитерация (кириллица ↔ латиница): "дрейк" → "drake", "metallica" → "металлика"
   - Удаление лишних символов: `?!.,;:'"` → strip
   - Нормализация пробелов и регистра
   - Поддержка альтернативных написаний: "The Weeknd" = "Weeknd" = "уикнд"

2. **Fuzzy-поиск по локальной БД:**
   - PostgreSQL: `pg_trgm` расширение + GIN индекс на `title || ' ' || artist`
   - Trigram similarity с порогом 0.3
   - SQLite fallback: Levenshtein distance через Python (для dev-окружения)

3. **Параллельный поиск по внешним источникам:**
   - Если локальная БД дала < 3 результатов → запускать Yandex + Spotify параллельно (`asyncio.gather`)
   - Если и они дали < 3 → запускать SoundCloud + VK + YouTube параллельно
   - Timeout на каждый источник: 8 секунд

4. **Дедупликация результатов:**
   - Нормализовать artist+title (lowercase, strip, убрать feat./ft.)
   - Сравнить Jaccard similarity > 0.7 → считать дубликатом
   - Приоритет: Yandex (320kbps) > Spotify > VK > SoundCloud > YouTube
   - При дедупликации сохранять метаданные из лучшего источника

5. **Ранжирование:**
   - Popularity score: downloads * 0.4 + recency * 0.3 + source_quality * 0.3
   - Персонализация: бустить треки близких жанров к user.fav_genres

**Файлы для изменений:**
- `bot/db.py` — добавить `search_local_tracks_fuzzy()`
- `bot/handlers/search.py` — переписать `_do_search()` с параллелизмом
- `bot/services/search_engine.py` — **новый файл** — логика нормализации, дедупликации, ранжирования
- Миграция БД: добавить trigram index

**Метрики успеха:**
- Процент "no_results" ответов снижается на 40%+
- Средняя латентность поиска не увеличивается (параллелизм компенсирует)
- Дубликаты в результатах = 0

---

#### TASK-002: Исправление всех критических багов

**2.1 File size race condition (BUG-001)**
```
Текущее: if file_size > MAX → download 128 → check again → return если всё ещё большой
Нужно:   if file_size > MAX → download 128 → check → cleanup + error message
         Добавить finally cleanup для ОБОИХ путей.
```

**2.2 Admin ID persistence (BUG-002)**
- Добавить поле `is_admin: bool` в модель User
- Проверку админа делать через DB, а не in-memory list
- При первом входе с username из ADMIN_USERNAMES — ставить is_admin=True в DB
- Убрать `settings.ADMIN_IDS.append()`

**2.3 Yandex token coupling (BUG-003)**
- Ввести `token_for_session()` — возвращает один и тот же токен в рамках одного запроса
- Передавать `token` явно из search → download
- Или: закрепить токен за source_id на время операции

**2.4 Playlist ownership (BUG-004)**
- Все playlist DELETE/UPDATE запросы должны содержать `WHERE user_id = :uid`
- Добавить unit-тест на невозможность удалить чужой трек

**2.5 Premium consistency (BUG-005)**
- При `is_premium=True AND premium_until IS NULL AND NOT is_admin`:
  - Автоматически ставить `premium_until = now + 30 days`
  - Или ставить `is_premium = False`
- Добавить DB constraint или миграцию

**Файлы:** `bot/db.py`, `bot/handlers/search.py`, `bot/services/yandex_provider.py`, `bot/models/user.py`, handlers/playlist.py

---

#### TASK-003: Защита от DDoS при падении Redis

**Текущее:** `except Exception: return True, 0` — при падении Redis все лимиты отключаются.

**Требуемое:**
1. In-memory fallback rate limiter:
   ```python
   from collections import defaultdict
   import time

   _mem_limits: dict[int, list[float]] = defaultdict(list)
   _mem_cooldowns: dict[int, float] = {}
   ```
2. При Redis unavailable — использовать in-memory counters
3. In-memory лимиты чуть строже (8 req/hour вместо 10)
4. Логировать Redis failure в Sentry (один раз, не на каждый запрос)
5. Healthcheck endpoint для мониторинга Redis connectivity

**Файл:** `bot/services/cache.py`

---

### ПРИОРИТЕТ 2 — ВАЖНЫЕ (P1)

---

#### TASK-004: Усиление CAPTCHA

**Текущее:** a+b (1-20), 39 возможных ответов, нет лимита попыток.

**Требуемое:**
1. Усложнить задачу: a × b + c (1-9), ~700+ уникальных ответов
2. Лимит попыток: 3 неправильных → блокировка на 30 минут
3. Хранить в Redis: `captcha:fails:{user_id}` → count
4. После 3 блокировок подряд → бан на 24 часа
5. Добавить альтернативный тип: "выбери цвет" (кнопки) — для мобильных

**Файлы:** `bot/middlewares/captcha.py`, `bot/services/cache.py`

---

#### TASK-005: Query cache для всех источников

**Текущее:** Кэширование запросов только для YouTube и SoundCloud.

**Требуемое:**
1. Добавить query cache для Yandex и Spotify (TTL 120s)
2. Вынести кэширование из search.py в decorator/wrapper:
   ```python
   @cached_search(source="yandex", ttl=120)
   async def search_yandex(query, limit): ...
   ```
3. Добавить метрику `query_cache_hit_rate` по источникам

**Файлы:** `bot/services/cache.py`, `bot/handlers/search.py`

---

#### TASK-006: Кэширование `bot.me()` для групп

**Текущее:** `await message.bot.me()` вызывается на каждое текстовое сообщение в группе.

**Требуемое:**
1. Кэшировать результат в модуле:
   ```python
   _bot_me: User | None = None
   async def get_bot_me(bot) -> User:
       global _bot_me
       if _bot_me is None:
           _bot_me = await bot.me()
       return _bot_me
   ```
2. Или использовать `bot.me()` — aiogram 3 уже кэширует это внутри (проверить).

**Файл:** `bot/handlers/search.py`

---

#### TASK-007: Streaming download для VK

**Текущее:** `dest.write_bytes(await resp.read())` — весь файл в память.

**Требуемое:**
```python
async with sess.get(url, ...) as resp:
    resp.raise_for_status()
    with open(dest, 'wb') as f:
        async for chunk in resp.content.iter_chunked(64 * 1024):
            f.write(chunk)
```

**Файл:** `bot/services/vk_provider.py`

---

#### TASK-008: Индексы базы данных

**Текущее:** Нет составного индекса на `listening_history`.

**Требуемое:**
1. Добавить индексы:
   ```sql
   CREATE INDEX ix_lh_user_action_created ON listening_history(user_id, action, created_at DESC);
   CREATE INDEX ix_tracks_artist_title ON tracks USING gin ((title || ' ' || artist) gin_trgm_ops);  -- PostgreSQL
   CREATE INDEX ix_tracks_downloads ON tracks(downloads DESC);
   ```
2. Объединить 3 запроса в `get_user_stats()` в один:
   ```sql
   SELECT
     COUNT(*) FILTER (WHERE action = 'play') as total,
     COUNT(*) FILTER (WHERE action = 'play' AND created_at >= :week_ago) as week,
     ...
   FROM listening_history WHERE user_id = :uid
   ```

**Файлы:** `bot/models/track.py`, `bot/db.py`, миграция Alembic

---

#### TASK-009: Dynamic ThreadPool sizing

**Текущее:** `ThreadPoolExecutor(max_workers=4)` — фиксированное число.

**Требуемое:**
1. Размер пула из конфига: `YTDL_WORKERS = int(os.getenv("YTDL_WORKERS", 4))`
2. При >500 юзерах — увеличить до 8-12
3. Добавить метрику: `ytdl_pool_active_threads` — gauge для мониторинга утилизации
4. Graceful shutdown: `_ytdl_pool.shutdown(wait=True, cancel_futures=True)` в `on_shutdown`

**Файлы:** `bot/services/downloader.py`, `bot/config.py`, `bot/main.py`

---

#### TASK-010: Рефакторинг circular imports

**Текущее:** `search.py` импортирует из `playlist.py`, `recognize.py` делает local import из `search.py`.

**Требуемое:**
1. Вынести все клавиатуры в `bot/keyboards.py`
2. Вынести CallbackData классы в `bot/callbacks.py`
3. Убрать все inline/local imports
4. Общие утилиты (`_fmt_duration`, `_clean_title`) в `bot/utils.py`

**Файлы:** Новые файлы `bot/keyboards.py`, `bot/callbacks.py`, `bot/utils.py`; рефакторинг всех handlers/

---

### ПРИОРИТЕТ 3 — УЛУЧШЕНИЯ (P2)

---

#### TASK-011: Inline-режим с полной поддержкой источников

**Текущее:** Inline поиск только через YouTube, не использует кэш запросов.

**Требуемое:**
1. Использовать ту же каскадную логику поиска (упрощённую):
   - Local DB → Yandex → YouTube
2. Для кэшированных треков (file_id) — отдавать `InlineQueryResultCachedAudio`
3. Для остальных — `InlineQueryResultAudio` с direct URL (для Yandex/VK)
4. Или: `switch_pm_text` для перехода в бот (как сейчас, но с better UX)
5. Добавить rate limiting для inline queries (3/сек)

**Файл:** `bot/handlers/inline.py`

---

#### TASK-012: "Вы имели в виду...?" suggestion

**Цель:** При 0 результатах предложить исправленный запрос.

**Реализация:**
1. Собирать корпус из `tracks.title + tracks.artist` (популярные)
2. При 0 результатах — найти ближайший по Levenshtein/trigram
3. Показать кнопку "Искать: {suggestion}?"
4. Хранить корпус в Redis (обновлять раз в час)

**Файлы:** `bot/services/search_engine.py`, `bot/handlers/search.py`

---

#### TASK-013: Прогресс скачивания

**Текущее:** Одно сообщение "Скачиваю..." до конца.

**Требуемое:**
1. Progress callback в yt-dlp:
   ```python
   def progress_hook(d):
       if d['status'] == 'downloading':
           percent = d.get('_percent_str', '?')
   ```
2. Обновлять сообщение каждые 15-20% (не чаще 1 раз в 2 сек — лимит Telegram API)
3. Показывать: `⬇ Скачиваю... 45% | 2.3 MB / 5.1 MB`

**Файлы:** `bot/services/downloader.py`, `bot/handlers/search.py`

---

#### TASK-014: Улучшение title cleaning

**Текущее:** 4 regex'а, не покрывают многие кейсы.

**Добавить в regex:**
- `(Remastered)`, `(Remastered 2021)`, `(Deluxe Edition)`
- `(Live at ...)`, `(Acoustic Version)`
- `[Explicit]`, `[Clean]`
- Emoji: все Unicode emoji → strip
- `(Prod. by ...)`, `(Prod. ...)`
- Множественные тире: `---` → `-`
- Trailing `- YouTube`, `- Topic`

**Покрыть unit-тестами:**
```python
assert clean("Drake - God's Plan (Official Music Video)") == "Drake - God's Plan"
assert clean("Баста — Выпускной (Медлячок) [Official Video] | Клип") == "Баста — Выпускной (Медлячок)"
assert clean("Metallica - Nothing Else Matters (Remastered 2021)") == "Metallica - Nothing Else Matters"
```

**Файлы:** `bot/services/downloader.py`, `tests/test_title_cleaning.py`

---

#### TASK-015: Audit log для админ-действий

**Текущее:** Админы выполняют broadcast, ban, settings без логирования.

**Требуемое:**
1. Новая таблица `admin_log`:
   ```
   id, admin_id, action, target_user_id, details(JSON), created_at
   ```
2. Логировать: broadcast, ban/unban, settings change, force premium
3. Команда `/admin audit` — последние 20 действий
4. Rate limit на admin commands: 10/мин

**Файлы:** `bot/models/admin_log.py` (новый), `bot/handlers/admin.py`, `bot/db.py`

---

#### TASK-016: Graceful degradation UX

**Текущее:** При ошибке — "Что-то пошло не так" без деталей.

**Требуемое:**
1. Различать типы ошибок и показывать разные сообщения:
   - Таймаут источника → "Источник {name} временно недоступен. Попробуем другой..."
   - Возрастное ограничение → "Трек с возрастным ограничением. Попробуй найти другую версию."
   - Файл слишком большой → "Трек длинный ({duration}), уменьшаю качество до 128 kbps..."
   - Redis недоступен → продолжить работу (уже реализовано), но уведомить админа
   - БД недоступна → "Сервис временно недоступен" (уже реализовано)
2. Автоматический retry с следующим источником при timeout
3. Кнопка "Попробовать ещё раз" с тем же запросом

**Файлы:** `bot/handlers/search.py`, `bot/i18n/`

---

#### TASK-017: Экспорт плейлистов

**Текущее:** Плейлисты только внутри бота.

**Требуемое:**
1. `/playlist export {name}` → TXT файл со списком треков
2. Формат: `Artist - Title (duration)\n`
3. Опционально: JSON для импорта в другого бота
4. Кнопка "Экспорт" в плейлисте

**Файлы:** `bot/handlers/playlist.py`

---

#### TASK-018: Улучшение Shazam recognition

**Текущее:** Распознаёт и ищет. Нет предпрослушивания.

**Требуемое:**
1. После распознавания показать превью:
   ```
   🎵 Распознано:
   Artist — Title
   [▶ Скачать] [🔍 Другие версии]
   ```
2. Кнопка "Другие версии" → поиск с query `Artist - Title`
3. Сохранять распознанные треки в историю с source="shazam"

**Файлы:** `bot/handlers/recognize.py`

---

### ПРИОРИТЕТ 4 — НОВЫЕ ФИЧИ (P3)

---

#### TASK-019: AI DJ — реальные рекомендации

**Текущее:** Заглушка, возвращает пустой список.

**Требуемое:**
1. Collaborative filtering на базе listening_history:
   - Найти пользователей с похожей историей (cosine similarity)
   - Рекомендовать треки которые слушали похожие пользователи, но не текущий
2. Content-based filtering:
   - Кластеризация по жанру/BPM/артисту из user profile
   - Рекомендовать треки из тех же кластеров
3. Hybrid подход: 60% collaborative + 40% content-based
4. Минимум 50 прослушиваний для активации collaborative
5. Fallback: топ-10 самых популярных треков за неделю
6. Обновление рекомендаций раз в час (кэш в Redis, TTL 1h)

**Файлы:** `recommender/ai_dj.py`, `bot/handlers/recommend.py`, `bot/db.py`

---

#### TASK-020: Очередь прослушивания (Queue)

**Цель:** Пользователь может добавлять треки в очередь и слушать последовательно.

**Требования:**
1. Кнопка "+ Очередь" рядом с "+ Плейлист"
2. Команда `/queue` — показать текущую очередь
3. Команда `/next` — следующий трек из очереди
4. Очередь хранится в Redis (TTL 2h)
5. Максимум 50 треков в очереди
6. Кнопки: [⏭ Далее] [🔀 Перемешать] [❌ Очистить]

**Файлы:** `bot/handlers/queue.py` (новый), `bot/services/cache.py`

---

#### TASK-021: Lyrics (тексты песен)

**Цель:** Показать текст песни после скачивания.

**Требования:**
1. Кнопка "📝 Текст" в feedback keyboard
2. API: Genius API (или musixmatch)
3. Показывать текст постранично (Telegram limit 4096 chars)
4. Кнопки пагинации: [← Назад] [→ Далее]
5. Кэшировать тексты в Redis (TTL 7d)
6. Не показывать полный текст — только первые 10 строк + ссылка на источник (copyright)

**Файлы:** `bot/services/lyrics_provider.py` (новый), `bot/handlers/search.py`

---

#### TASK-022: Статистика и аналитика для админов

**Текущее:** Базовая статистика пользователей.

**Требуемое:**
1. `/admin stats` — расширенная статистика:
   - DAU/WAU/MAU
   - Количество поисков по часам (heatmap data)
   - Топ-10 запросов за сегодня/неделю
   - Источники: % из Yandex / Spotify / YouTube / VK / local
   - Cache hit rate
   - Средняя латентность поиска
2. Экспорт в CSV: `/admin export stats`
3. Ежедневный дайджест в Telegram (отправка админу в 23:00)

**Файлы:** `bot/handlers/admin.py`, `bot/db.py`

---

#### TASK-023: Multi-language search optimization

**Текущее:** Один запрос отправляется во все источники as-is.

**Требуемое:**
1. Определение языка запроса (простая эвристика по Unicode ranges)
2. Для русских запросов: приоритет Yandex → VK → YouTube
3. Для английских: приоритет Spotify → YouTube → SoundCloud
4. Для смешанных: все источники параллельно
5. Транслитерация: "nirvana" → дополнительный поиск "нирвана" (и наоборот)

**Файлы:** `bot/services/search_engine.py`, `bot/handlers/search.py`

---

#### TASK-024: Smart auto-quality

**Текущее:** Фиксированный bitrate из настроек пользователя.

**Требуемое:**
1. "Авто" режим — выбирает качество на основе:
   - Длительность трека (>5 мин → 192 для экономии трафика)
   - Источник (Yandex → 320, YouTube → 192)
   - История: если пользователь часто получает "file too large" → автоматически снизить
2. Показывать реальный bitrate в caption (не запрошенный, а фактический)

**Файлы:** `bot/handlers/search.py`, `bot/config.py`

---

## ЧАСТЬ 3: ПЛАН РЕАЛИЗАЦИИ

---

### Фаза 1: Стабилизация (1-2 недели)
- [ ] TASK-002: Исправление критических багов
- [ ] TASK-003: Защита от DDoS при падении Redis
- [ ] TASK-004: Усиление CAPTCHA
- [ ] TASK-008: Индексы базы данных
- [ ] TASK-010: Рефакторинг circular imports

### Фаза 2: Поиск (2-3 недели)
- [ ] TASK-001: Умный поиск с fuzzy matching и дедупликацией
- [ ] TASK-005: Query cache для всех источников
- [ ] TASK-014: Улучшение title cleaning
- [ ] TASK-023: Multi-language search optimization
- [ ] TASK-012: "Вы имели в виду...?" suggestion

### Фаза 3: UX (1-2 недели)
- [ ] TASK-006: Кэширование bot.me()
- [ ] TASK-007: Streaming download для VK
- [ ] TASK-013: Прогресс скачивания
- [ ] TASK-016: Graceful degradation UX
- [ ] TASK-018: Улучшение Shazam recognition

### Фаза 4: Новые фичи (3-4 недели)
- [ ] TASK-009: Dynamic ThreadPool sizing
- [ ] TASK-011: Inline-режим с полной поддержкой
- [ ] TASK-015: Audit log для админов
- [ ] TASK-017: Экспорт плейлистов
- [ ] TASK-019: AI DJ — рекомендации
- [ ] TASK-020: Очередь прослушивания
- [ ] TASK-024: Smart auto-quality

### Фаза 5: Advanced (2-3 недели)
- [ ] TASK-021: Lyrics
- [ ] TASK-022: Расширенная аналитика
- [ ] Миграция Alembic для всех изменений схемы
- [ ] Нагрузочное тестирование (locust/k6)
- [ ] Документация API и deployment guide

---

## ЧАСТЬ 4: СРАВНЕНИЕ С ЛУЧШИМИ ПРАКТИКАМИ

---

### Что уже хорошо (лучше многих ботов):
1. **6-source cascade** — большинство ботов используют только YouTube
2. **Redis caching** на 3 уровнях — правильная архитектура
3. **Rate limiting** с разделением regular/premium
4. **Sentry + Prometheus** — мониторинг на уровне продакшена
5. **Docker-compose** — готово к деплою
6. **i18n** — 3 языка, большинство ботов только 1
7. **Shazam recognition** — редкая фича
8. **Telegram Stars payments** — монетизация из коробки

### Что делают лучшие боты, а у вас нет:
| Фича | Лучшие боты | BLACK ROOM |
|-------|------------|------------|
| Fuzzy search | Да (trigram/Elasticsearch) | ILIKE only |
| Параллельный поиск | Да (gather) | Последовательный |
| Дедупликация | Да (fingerprint) | Нет |
| Прогресс скачивания | Да (progress bar) | Просто "Скачиваю..." |
| Lyrics | Да (Genius/Musixmatch) | Нет |
| Queue/очередь | Да | Нет |
| Smart suggestions | Да ("Вы имели в виду?") | Нет |
| Inline с аудио | Да (все источники) | Только YouTube |
| Collaborative filtering | Да (ML) | Заглушка |
| Playlist export/import | Да | Нет |
| Admin audit trail | Да | Нет |
