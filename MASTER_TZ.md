# MASTER ТЗ — BLACK ROOM RADIO BOT

> **Версия**: 1.1  
> **Дата консолидации**: Июнь 2025  
> **Статус документа**: Объединенное техническое задание  
> **Последнее обновление**: Июль 2025 — добавлен раздел 11 «Spotify-Killer Audio Engine»

---

## СОДЕРЖАНИЕ

1. [Введение](#1-введение)
2. [Продуктовая стратегия 2026](#2-продуктовая-стратегия-2026)
3. [Roadmap 2026](#3-roadmap-2026)
4. [Функциональные спецификации — EPICs](#4-функциональные-спецификации--epics)
5. [Баги и критические исправления](#5-баги-и-критические-исправления)
6. [Технические улучшения](#6-технические-улучшения)
7. [ML Рекомендации ✅ РЕАЛИЗОВАНО](#7-ml-рекомендации--реализовано)
8. [Mini App улучшения](#8-mini-app-улучшения)
9. [План реализации](#9-план-реализации)
10. [Definition of Done](#10-definition-of-done)
11. [Spotify-Killer Audio Engine](#11-spotify-killer-audio-engine)

---

# 1. ВВЕДЕНИЕ

## 1.1 Цель документа

Единое техническое задание, объединяющее все продуктовые и технические требования для BLACK ROOM RADIO BOT.

## 1.2 О проекте

**BLACK ROOM RADIO BOT** — Telegram-бот для поиска, скачивания и стриминга музыки с интегрированными ML-рекомендациями.

**Стек:**
- Python 3.11+
- aiogram 3.x (Telegram Bot API)
- SQLAlchemy 2.x async (PostgreSQL/SQLite)
- Redis (кеширование)
- FastAPI (webhook)
- implicit + gensim (ML рекомендации)

---

# 2. ПРОДУКТОВАЯ СТРАТЕГИЯ 2026

## 2.1 Видение продукта

### 2.1.1 North Star Metric
**Weekly Active Listeners (WAL)** — пользователи, совершившие ≥3 прослушиваний за неделю.

### 2.1.2 Guardrail Metrics
- **D7 Retention** ≥ 25%
- **Median time-to-first-track** ≤ 8 сек
- **Error rate** ≤ 2%

## 2.2 Пять продуктовых столпов

| # | Столп | Описание | KPI |
|---|-------|----------|-----|
| 1 | **Speed** | Мгновенный доступ к треку | Time-to-track ≤ 5s |
| 2 | **Personalization** | Рекомендации под вкус | ≥30% CTR на Daily Mix |
| 3 | **Virality** | Sharing как growth loop | K-factor ≥ 0.3 |
| 4 | **Premium** | Монетизация через подписку | ARPU $1.5/mo |
| 5 | **AI UX** | Голосовое управление, AI DJ | NPS ≥ 50 |

## 2.3 Сегменты аудитории

| Сегмент | Описание | Приоритет |
|---------|----------|-----------|
| **Casual Listener** | 2-5 треков/неделю, ищет популярное | P0 |
| **Music Enthusiast** | 10+ треков/неделю, создает плейлисты | P0 |
| **DJ/Creator** | Качает для миксов, нужен HQ | P1 |
| **Group Admin** | Использует бота в чатах | P2 |

## 2.4 Feature Backlog TOP-20

| # | Feature | Столп | Effort | Impact | Priority |
|---|---------|-------|--------|--------|----------|
| 1 | Daily Mix | Personalization | M | High | P0 |
| 2 | Share Track deeplink | Virality | S | High | P0 |
| 3 | Release Radar | Personalization | L | Medium | P1 |
| 4 | Favorites (❤️) | Personalization | S | High | P0 |
| 5 | Queue system | Speed | M | Medium | P1 |
| 6 | Lyrics integration | AI UX | M | Medium | P2 |
| 7 | Voice search | AI UX | L | Low | P3 |
| 8 | Group DJ mode | Virality | L | Medium | P2 |
| 9 | Offline cache (PWA) | Speed | L | High | P1 |
| 10 | Premium tiers | Premium | M | High | P0 |
| 11 | Artist pages | Personalization | M | Low | P3 |
| 12 | Charts by region | Speed | S | Medium | P2 |
| 13 | Podcast support | AI UX | L | Low | P3 |
| 14 | Social playlists | Virality | M | Medium | P2 |
| 15 | Listening history export | Speed | S | Low | P3 |
| 16 | AI DJ infinite stream | AI UX | L | High | P1 |
| 17 | Smart notifications | Personalization | M | Medium | P2 |
| 18 | Mini App redesign | Speed | M | High | P1 |
| 19 | Referral program | Virality | M | High | P1 |
| 20 | Family plan | Premium | S | Medium | P2 |

---

# 3. ROADMAP 2026

## 3.1 Roadmap по кварталам

### Q2 2026: Telegram Integration
- Deep linking для share
- Inline mode improvements
- Mini App v2

### Q3 2026: Killer Features
- Daily Mix
- Release Radar
- Queue system
- Lyrics

### Q4 2026: Algorithms & AI
- ✅ ML Recommendations (DONE)
- AI DJ infinite stream
- Voice commands

### Q1 2027: Monetization
- Premium tiers
- Referral program
- Family plan

## 3.2 Фазы реализации

| Фаза | Название | Сроки | Фокус |
|------|----------|-------|-------|
| 1 | TG Integration | Q2 2026 | Deep links, Mini App |
| 2 | Killer Features | Q3 2026 | Daily Mix, Queue, Lyrics |
| 3 | Algorithms | Q4 2026 | ML, AI DJ |
| 4 | Monetization | Q1 2027 | Premium, Referral |
| 5 | Security | Ongoing | Rate limits, anti-abuse |

---

# 4. ФУНКЦИОНАЛЬНЫЕ СПЕЦИФИКАЦИИ — EPICs

## 4.1 EPIC-A: Daily Mix

### Описание
Персонализированный микс из 10-20 треков, обновляемый ежедневно.

### User Stories
1. Пользователь открывает `/mix` → получает 10 треков на основе истории
2. Пользователь может сохранить микс как плейлист
3. Пользователь может поделиться миксом (deeplink)

### Модель данных

```sql
CREATE TABLE daily_mixes (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    mix_date DATE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, mix_date)
);

CREATE TABLE daily_mix_tracks (
    id SERIAL PRIMARY KEY,
    mix_id INT REFERENCES daily_mixes(id) ON DELETE CASCADE,
    track_id INT REFERENCES tracks(id),
    position INT NOT NULL,
    algo VARCHAR(20) DEFAULT 'hybrid',
    score FLOAT
);
```

### Service Contract

```python
async def build_daily_mix(user_id: int, limit: int = 10) -> list[dict]:
    """
    Builds personalized daily mix.
    - Check if today's mix exists → return cached
    - Get ML recommendations (hybrid scorer)
    - Fallback: SQL content-based
    - Save to daily_mixes + daily_mix_tracks
    - Return track dicts with algo info
    """
```

### Handler Contract

```python
@router.message(Command("mix"))
async def cmd_mix(message: Message):
    # 1. Get or create daily mix
    # 2. Format message with tracks
    # 3. Add inline keyboard: [▶ Play All] [💾 Save] [📤 Share]
```

### Acceptance Criteria
- [ ] `/mix` возвращает 10 треков за < 3 сек
- [ ] Микс кешируется на день
- [ ] Кнопка "Save" создает плейлист
- [ ] Кнопка "Share" генерирует deeplink
- [ ] Analytics: `mix_open`, `mix_save`, `mix_share`

---

## 4.2 EPIC-B: Share Track / Share Mix

### Описание
Виральный sharing через Telegram deeplinks.

### Deep Link Format
```
Track: https://t.me/bot?start=tr_{track_id}_{sharer_id}
Mix:   https://t.me/bot?start=mx_{mix_id}_{sharer_id}
```

### Модель данных

```sql
CREATE TABLE share_links (
    id SERIAL PRIMARY KEY,
    owner_id BIGINT REFERENCES users(id),
    entity_type VARCHAR(10) NOT NULL, -- 'track' | 'mix' | 'playlist'
    entity_id INT NOT NULL,
    short_code VARCHAR(16) UNIQUE,
    clicks INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### Service Contract

```python
async def create_share_link(
    owner_id: int,
    entity_type: str,
    entity_id: int
) -> str:
    """
    Creates shareable link for track/mix/playlist.
    Returns: t.me/bot?start={short_code}
    """

async def resolve_share_link(short_code: str) -> dict | None:
    """
    Resolves short_code to entity.
    Increments click counter.
    Returns: {type, id, owner_id}
    """
```

### Handler Contract

```python
@router.message(CommandStart(deep_link=True))
async def start_with_deeplink(message: Message, command: CommandObject):
    # Parse: tr_{id}_{sharer} | mx_{id}_{sharer}
    # Track: show track card + download button
    # Mix: show mix preview + "Clone to My Mixes"
```

### Acceptance Criteria
- [ ] Share button генерирует deeplink
- [ ] Deeplink открывает track/mix preview
- [ ] Счетчик кликов обновляется
- [ ] Analytics: `track_share`, `shared_track_open`

---

## 4.3 EPIC-C: Release Radar

### Описание
Уведомления о новых релизах отслеживаемых артистов.

### User Stories
1. Система автоматически определяет топ-артистов пользователя
2. Scheduler проверяет новые релизы раз в 6 часов
3. При обнаружении — push-уведомление с превью

### Модель данных

```sql
CREATE TABLE artist_watchlist (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    artist_name VARCHAR(255) NOT NULL,
    source VARCHAR(20), -- 'auto' | 'manual'
    last_release_check TIMESTAMP,
    UNIQUE(user_id, artist_name)
);

CREATE TABLE release_notifications (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    track_id INT REFERENCES tracks(id),
    notified_at TIMESTAMP DEFAULT NOW(),
    opened BOOLEAN DEFAULT FALSE
);
```

### Acceptance Criteria
- [ ] Топ-5 артистов автоматически в watchlist
- [ ] Проверка релизов каждые 6 часов
- [ ] Push с превью нового трека
- [ ] Opt-out через `/settings releases off`

---

## 4.4 EPIC-D: Favorites (❤️)

### Описание
Система избранных треков, влияющих на рекомендации.

### UI Flow
1. После скачивания трека — кнопка ❤️ в keyboard
2. `/favorites` — список избранных
3. Favorites влияют на Daily Mix и recommendations

### Модель данных

```sql
CREATE TABLE favorite_tracks (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    track_id INT REFERENCES tracks(id),
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, track_id)
);
```

### Handler Contract

```python
@router.callback_query(F.data.startswith("fav:"))
async def toggle_favorite(callback: CallbackQuery):
    # Parse: fav:{track_id}
    # Toggle favorite status
    # Update keyboard icon

@router.message(Command("favorites"))
async def cmd_favorites(message: Message):
    # Show paginated list of favorites
    # Buttons: [▶ Play] [❌ Remove]
```

### Acceptance Criteria
- [ ] Кнопка ❤️ после скачивания
- [ ] `/favorites` с пагинацией
- [ ] Favorites учитываются в Daily Mix
- [ ] Дубликаты не создаются

---

# 5. БАГИ И КРИТИЧЕСКИЕ ИСПРАВЛЕНИЯ

## 5.1 BUG-001: Race Condition в скачивании [CRITICAL]

**Симптом:** При быстром повторном нажатии на трек — дублирование сообщений.

**Причина:** Отсутствие блокировки на уровне пользователя.

**Решение:**
```python
# bot/middlewares/throttle.py
async def __call__(self, handler, event, data):
    key = f"download:{user_id}:{track_id}"
    if await redis.exists(key):
        return  # Skip duplicate
    await redis.setex(key, 10, "1")  # 10 sec lock
    return await handler(event, data)
```

**Файлы:** `bot/middlewares/throttle.py`, `bot/handlers/search.py`

---

## 5.2 BUG-002: Admin ID Vulnerability [CRITICAL]

**Симптом:** Admin ID проверяется как строка, можно обойти.

**Причина:** `int(settings.ADMIN_IDS.split(","))` без валидации.

**Решение:**
```python
# bot/config.py
ADMIN_IDS: list[int] = Field(default_factory=list)

@field_validator("ADMIN_IDS", mode="before")
def parse_admin_ids(cls, v):
    if isinstance(v, str):
        return [int(x.strip()) for x in v.split(",") if x.strip().isdigit()]
    return v
```

**Файлы:** `bot/config.py`, `bot/handlers/admin.py`

---

## 5.3 BUG-003: Yandex Token Expiry [HIGH]

**Симптом:** После истечения токена — 401 ошибки, молчаливый fallback.

**Решение:**
1. Добавить `token_expires_at` в config
2. Проактивный refresh за 1 час до expiry
3. Alert админу при неудачном refresh

**Файлы:** `bot/services/yandex_provider.py`, `bot/config.py`

---

## 5.4 BUG-004: Playlist Ownership [MEDIUM]

**Симптом:** Можно удалить чужой плейлист зная ID.

**Решение:**
```python
# bot/handlers/playlist.py
async def delete_playlist(user_id: int, playlist_id: int):
    playlist = await get_playlist(playlist_id)
    if playlist.owner_id != user_id:
        raise PermissionError("Not owner")
```

**Файлы:** `bot/handlers/playlist.py`

---

## 5.5 BUG-005: Premium Consistency [MEDIUM]

**Симптом:** Premium status не синхронизируется между сессиями.

**Решение:**
1. Проверять `premium_until` при каждом запросе
2. Инвалидировать Redis кеш при истечении

**Файлы:** `bot/middlewares/`, `bot/db.py`

---

# 6. ТЕХНИЧЕСКИЕ УЛУЧШЕНИЯ

## 6.1 TASK-001: Исправление циклических импортов

**Проблема:** `ValueError: Models are not yet loaded` при запуске.

**Причина:** `bot/db.py` импортирует модели до их определения.

**Решение:**
```python
# bot/models/base.py
from bot.models.user import User
from bot.models.track import Track, ListeningHistory
# ... все модели здесь

# bot/db.py
from bot.models.base import *  # Single import point
```

**Файлы:** `bot/db.py`, `bot/models/base.py`, `bot/models/__init__.py`

---

## 6.2 TASK-002: ThreadPool Sizing

**Проблема:** `THREAD_POOL_SIZE=4` фиксирован, не масштабируется.

**Решение:**
```python
# bot/config.py
THREAD_POOL_SIZE: int = Field(default_factory=lambda: min(32, os.cpu_count() * 2 + 4))
```

---

## 6.3 TASK-003: Redis DDoS Protection

**Проблема:** Нет rate limit на Redis операции.

**Решение:**
```python
# bot/services/cache.py
class RateLimitedRedis:
    async def get(self, key: str):
        if await self._is_rate_limited():
            raise RateLimitExceeded()
        return await self._redis.get(key)
```

---

## 6.4 TASK-004: Fuzzy Search

**Проблема:** Опечатки в запросах не обрабатываются.

**Решение:**
```python
# bot/services/search_engine.py
from rapidfuzz import fuzz

def fuzzy_match(query: str, candidates: list[str], threshold: int = 80) -> list[str]:
    return [c for c in candidates if fuzz.ratio(query.lower(), c.lower()) >= threshold]
```

**Зависимости:** `rapidfuzz>=3.0.0`

---

## 6.5 TASK-005: Parallel Search

**Проблема:** Источники опрашиваются последовательно.

**Решение:**
```python
# bot/services/search_engine.py
async def search_all_providers(query: str) -> list[dict]:
    tasks = [
        asyncio.create_task(yandex.search(query)),
        asyncio.create_task(youtube.search(query)),
        asyncio.create_task(spotify.search(query)),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return merge_and_dedupe(results)
```

---

## 6.6 TASK-006: Audit Log для админов

**Требуется:**
```sql
CREATE TABLE admin_log (
    id SERIAL PRIMARY KEY,
    admin_id BIGINT NOT NULL,
    action VARCHAR(50) NOT NULL,
    target_user_id BIGINT,
    details JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
```

**Логировать:** broadcast, ban/unban, settings change, force premium.

---

## 6.7 TASK-007: Graceful Degradation UX

**Требуется:**
1. Таймаут источника → "Источник временно недоступен"
2. Возрастное ограничение → "Попробуй другую версию"
3. Файл большой → "Уменьшаю качество до 128 kbps"
4. Кнопка "Попробовать ещё раз"

---

## 6.8 TASK-008: Title Cleaning

**Проблема:** Regex'ы не покрывают все кейсы.

**Добавить:**
- `(Remastered)`, `(Remastered 2021)`
- `(Live at ...)`, `(Acoustic Version)`
- `[Explicit]`, `[Clean]`
- Emoji strip
- `(Prod. by ...)`

---

## 6.9 TASK-009: Экспорт плейлистов

**Требуется:**
1. `/playlist export {name}` → TXT файл
2. Формат: `Artist - Title (duration)\n`
3. Кнопка "Экспорт" в плейлисте

---

## 6.10 TASK-010: Queue System

**Требуется:**
1. Кнопка "+ Очередь"
2. `/queue` — показать очередь
3. `/next` — следующий трек
4. Redis storage (TTL 2h)
5. Max 50 треков

---

## 6.11 TASK-011: Lyrics Integration

**Требуется:**
1. Кнопка "📝 Текст" после скачивания
2. API: Genius/Musixmatch
3. Пагинация (4096 char limit)
4. Кеш в Redis (TTL 7d)

---

## 6.12 TASK-012: Multi-language Search

**Требуется:**
1. Определение языка запроса
2. RU → Yandex → VK → YouTube
3. EN → Spotify → YouTube → SoundCloud
4. Транслитерация: "nirvana" ↔ "нирвана"

---

## 6.13 TASK-013: Smart Auto-Quality

**Требуется:**
1. "Авто" режим:
   - >5 мин → 192 kbps
   - Yandex → 320, YouTube → 192
   - При "file too large" → снизить
2. Показывать реальный bitrate

---

## 6.14 TASK-014: Admin Stats Dashboard

**Требуется:**
```
/admin stats:
- DAU/WAU/MAU
- Топ-10 запросов
- Источники: % Yandex/Spotify/YouTube/VK
- Cache hit rate
- Средняя латентность
```

---

# 7. ML РЕКОМЕНДАЦИИ ✅ РЕАЛИЗОВАНО

> **Статус:** Полностью реализовано в июне 2025  
> **Компоненты:** A-H все внедрены

## 7.1 Архитектура системы

### Компоненты

| # | Компонент | Статус | Описание |
|---|-----------|--------|----------|
| H | Config & Feature Flags | ✅ DONE | ML_* настройки в bot/config.py |
| B | Model Store | ✅ DONE | Singleton хранилище моделей |
| A | Training Pipeline | ✅ DONE | ALS + Word2Vec обучение |
| C | Track Embeddings | ✅ DONE | Word2Vec для track similarity |
| D | Hybrid Scorer | ✅ DONE | ALS + Embedding + Popularity scoring |
| E | ai_dj.py Refactor | ✅ DONE | ML path + SQL fallback |
| F | Profile Auto-Update | ✅ DONE | Обновление после 10 plays |
| G | A/B Testing | ✅ DONE | recommendation_log table |

### Новые файлы (созданы)

```
recommender/
├── config.py          # ScorerWeights, MLConfig
├── model_store.py     # Singleton для моделей
├── data_extractor.py  # Извлечение данных для обучения
├── train.py           # Training pipeline
├── embeddings.py      # TrackEmbeddings wrapper
├── scorer.py          # HybridScorer
├── profile_updater.py # Расширенное обновление профиля
├── evaluation.py      # Offline метрики
```

### Модель данных

```sql
CREATE TABLE recommendation_log (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    track_id INT REFERENCES tracks(id),
    algo VARCHAR(20),  -- 'ml' | 'sql' | 'popular'
    position INT,
    score FLOAT,
    clicked BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);
```

## 7.2 Конфигурация

```env
# .env
ML_ENABLED=true
ML_RETRAIN_HOUR=4
ML_MIN_INTERACTIONS=100
ML_SCORER_W_ALS=0.40
ML_SCORER_W_EMB=0.25
ML_SCORER_W_POP=0.15
ML_SCORER_W_FRESH=0.10
ML_SCORER_W_TIME=0.10
```

## 7.3 API

```python
# Рекомендации (ML или SQL fallback)
tracks = await get_recommendations(user_id, limit=10)

# Похожие треки (embeddings)
similar = await get_similar_tracks(track_id, limit=10)

# Запуск обучения
python -m recommender.train
```

## 7.4 Зависимости

```txt
implicit>=0.7.0
gensim>=4.3.0
scipy>=1.11.0
numpy>=1.24.0
```

---

# 8. MINI APP УЛУЧШЕНИЯ

## 8.1 UI/UX Improvements

| # | Feature | Описание | Приоритет |
|---|---------|----------|-----------|
| 1 | Real Thumbnails | Картинки треков, не заглушки | P0 |
| 2 | Glassmorphism | glassmorphism для карточек | P1 |
| 3 | SVG Animations | Анимированные иконки | P2 |
| 4 | Marquee Title | Бегущая строка для длинных названий | P1 |
| 5 | Waveform Visualizer | Визуализация при проигрывании | P2 |
| 6 | Custom Scrollbar | Стилизованный скроллбар | P3 |
| 7 | Custom Range | Кастомный range для слайдеров | P2 |

## 8.2 Media Features

| # | Feature | Описание | Приоритет |
|---|---------|----------|-----------|
| 8 | Media Session API | Управление из уведомлений | P0 |
| 9 | Haptic Feedback | Вибрация при действиях | P1 |
| 10 | Swipe Actions | Свайп для удаления/добавления | P1 |
| 11 | Pull-to-Refresh | Потянуть для обновления | P1 |
| 12 | Skeleton Loading | Скелетоны при загрузке | P0 |
| 13 | Synced Lyrics | Караоке-подсветка текста | P2 |

## 8.3 Killer Features — Level 1

### Dynamic Colors
Извлечение доминирующих цветов из обложки трека для динамической темы интерфейса.

```javascript
// Color extraction from album art
const colors = await extractColors(albumArt);
document.documentElement.style.setProperty('--primary', colors.dominant);
```

### Mini-Player
Постоянный мини-плеер внизу экрана с базовыми контролами.

```html
<div class="mini-player">
  <img src="thumbnail" class="mini-thumb">
  <div class="mini-info">
    <span class="mini-title">Track Name</span>
    <span class="mini-artist">Artist</span>
  </div>
  <button class="mini-play">▶</button>
</div>
```

## 8.4 Killer Features — Level 2

### Gapless Playback
Бесшовное воспроизведение между треками (preload следующего).

### AI Wave Button
Кнопка "Моя Волна" — бесконечный поток AI-рекомендаций.

```javascript
async function startAIWave() {
  const nextTrack = await api.getNextAITrack();
  preloadTrack(nextTrack);
  // Infinite stream
}
```

## 8.5 Killer Features — Level 3

### Viral Share Cards
Красивые карточки для шаринга в Stories/соцсети.

### Offline Cache
PWA кеширование для офлайн-прослушивания.

```javascript
// Service Worker caching
self.addEventListener('fetch', event => {
  if (event.request.url.includes('/audio/')) {
    event.respondWith(caches.match(event.request));
  }
});
```

---

# 9. ПЛАН РЕАЛИЗАЦИИ

## 9.1 Фаза 1: Стабилизация (2 недели)

| # | Задача | Приоритет | Статус |
|---|--------|-----------|--------|
| 1 | BUG-001: Race condition | P0 | ⏳ |
| 2 | BUG-002: Admin ID | P0 | ⏳ |
| 3 | BUG-003: Yandex token | P0 | ⏳ |
| 4 | TASK-001: Circular imports | P0 | ⏳ |

## 9.2 Фаза 2: Favorites + Daily Mix (3 недели)

| # | Задача | Приоритет | Статус |
|---|--------|-----------|--------|
| 1 | EPIC-D: Favorites | P0 | ⏳ |
| 2 | EPIC-A: Daily Mix | P0 | ⏳ |
| 3 | Tests + i18n | P1 | ⏳ |

## 9.3 Фаза 3: Sharing + Virality (2 недели)

| # | Задача | Приоритет | Статус |
|---|--------|-----------|--------|
| 1 | EPIC-B: Share Track | P0 | ⏳ |
| 2 | EPIC-B: Share Mix | P0 | ⏳ |
| 3 | Analytics events | P1 | ⏳ |

## 9.4 Фаза 4: Release Radar (2 недели)

| # | Задача | Приоритет | Статус |
|---|--------|-----------|--------|
| 1 | EPIC-C: Watchlist | P1 | ⏳ |
| 2 | EPIC-C: Scheduler | P1 | ⏳ |
| 3 | EPIC-C: Notifications | P1 | ⏳ |

## 9.5 Фаза 5: Search & UX (2 недели)

| # | Задача | Приоритет | Статус |
|---|--------|-----------|--------|
| 1 | TASK-004: Fuzzy search | P1 | ⏳ |
| 2 | TASK-005: Parallel search | P1 | ⏳ |
| 3 | TASK-007: Graceful UX | P1 | ⏳ |

## 9.6 Фаза 6: Queue & Extras (2 недели)

| # | Задача | Приоритет | Статус |
|---|--------|-----------|--------|
| 1 | TASK-010: Queue system | P1 | ⏳ |
| 2 | TASK-011: Lyrics | P2 | ⏳ |
| 3 | Mini App improvements | P1 | ⏳ |

---

# 10. DEFINITION OF DONE

## 10.1 Для каждой фичи

- [ ] Есть migration (если нужна БД)
- [ ] Есть model/service/handler
- [ ] Есть i18n (ru, en, kg)
- [ ] Есть happy-path тесты
- [ ] Есть edge-case тесты
- [ ] Есть analytics/logging
- [ ] Есть fallback behavior
- [ ] Есть user-facing copy

## 10.2 Для каждого бага

- [ ] Root cause identified
- [ ] Fix implemented
- [ ] Regression test added
- [ ] No other systems broken

## 10.3 Код-стандарты

- Без циклических импортов
- Бизнес-логика в `services/`, не в handlers
- Handlers только orchestration/UI
- Reuse existing cache patterns
- Все callback_data через typed callbacks

## 10.4 Безопасность

- Owner validation обязательна
- Callback data не раскрывает чужие ресурсы
- Никакой чувствительной информации в deeplink

---

# ПРИЛОЖЕНИЯ

## A. Изменения в главном меню

```
Row 1: [▸ TEQUILA LIVE] [◑ FULLMOON LIVE]
Row 2: [✦ DAILY MIX] [◈ По вашему вкусу]
Row 3: [◈ Найти трек] [🎦 Видео]
Row 4: [❤️ Любимое] [🏆 Топ-чарты]
Row 5: [▸ Плейлисты] [🆕 Новые релизы]
Row 6: [◇ Premium] [◉ Профиль]
Row 7: [❓ FAQ]
```

## B. Analytics Events

| Event | Trigger |
|-------|---------|
| `mix_open` | User opens /mix |
| `mix_share` | User shares mix |
| `mix_clone` | User saves mix as playlist |
| `track_share` | User shares track |
| `shared_track_open` | User opens shared track |
| `favorite_add` | User adds to favorites |
| `favorite_remove` | User removes from favorites |
| `release_open` | User opens release notification |
| `release_opt_out` | User disables release notifications |

## C. Dependencies

```txt
# requirements.txt additions
implicit>=0.7.0
gensim>=4.3.0
scipy>=1.11.0
numpy>=1.24.0
rapidfuzz>=3.0.0
```

---

> **Документ создан**: Июнь 2025  
> **Последнее обновление**: Июль 2025  
> **Автор**: BLACK ROOM TEAM

---

# 11. SPOTIFY-KILLER AUDIO ENGINE

> **Цель:** Довести Mini App до уровня native-приложений Spotify / Apple Music / Yandex Music по качеству воспроизведения, UX и «wow»-эффектам.

## 11.1 Аудит текущего состояния

| Фича | Статус | Детали |
|-------|--------|--------|
| MediaSession API | ✅ DONE | play/pause/next/prev/seek/seekforward/seekbackward + artwork + positionState |
| Dynamic Color Extraction | ✅ DONE | Canvas 64×64, pixel bucketing, dominant saturated color |
| Glassmorphism Background | ✅ DONE | Blurred cover image behind player |
| Crossfade | ✅ DONE | 120ms exponential out, 300ms ramp in |
| Preload Next Track | ✅ DONE | 30s before end via `<audio preload>` |
| Prefetch Queue (IndexedDB) | ✅ DONE | Next 2 tracks cached as blobs, 100MB LRU |
| Wake Lock API | ✅ DONE | Screen-on during playback, re-acquire on visibility |
| Service Worker Notifications | ✅ DONE | SHOW/HIDE_NOW_PLAYING persistent notification |
| 10-band Parametric EQ | ✅ DONE | Studio Q values, lowshelf/peaking/highshelf |
| Compressor + Panner + Subsonic HPF | ✅ DONE | Glue compressor, stereo panner, 20Hz HPF |
| Haptic Feedback | ⚠️ PARTIAL | Только в Player.tsx, не на всех кнопках |
| Loudness Normalization | ❌ TODO | Нет нормализации громкости (-14 LUFS) |
| Infinity Autoplay | ❌ TODO | Очередь кончается → тишина |
| True Gapless Playback | ⚠️ PARTIAL | Есть crossfade, но нет zero-gap overlap |
| Animated Mesh Gradient | ❌ TODO | Сейчас один цвет, нужен 3-цветный mesh |
| Global Haptic | ❌ TODO | Нет вибрации на nav, чартах, поиске |

## 11.2 Реализуемые фичи

### SKF-001: Infinity Autoplay (P0)
**Проблема:** Когда очередь заканчивается — тишина. Spotify никогда не останавливается.

**Решение:** В обработчике `audio.ended` — когда `sendAction("next")` возвращает пустой трек или очередь закончилась, автоматически вызываем `fetchSimilar()` или `fetchWave()` для подгрузки новых треков.

**Acceptance Criteria:**
- [ ] При окончании очереди автоматически загружаются 5-10 похожих треков
- [ ] Загрузка происходит бесшовно, без паузы > 1 сек
- [ ] Используется `fetchSimilar(currentTrackId)` → fallback `fetchWave()`
- [ ] Максимум 3 автоподгрузки подряд (защита от бесконечного потока)
- [ ] Можно отключить в настройках

### SKF-002: Loudness Normalization -14 LUFS (P1)
**Проблема:** Треки из разных источников имеют разную громкость. YouTube может быть тише Yandex на 10dB+.

**Решение:** Real-time RMS analysis через AnalyserNode → вычисление gain compensation → применение через inputGain node.

**Acceptance Criteria:**
- [ ] Средняя воспринимаемая громкость одинакова между треками
- [ ] Gain compensation в диапазоне -12dB..+12dB
- [ ] Плавный ramp (300ms) при применении компенсации
- [ ] Не влияет на EQ preset и manual gain

### SKF-003: Animated Mesh Gradient (P1)
**Проблема:** Сейчас извлекается 1 цвет — фон статичный. Spotify/Apple Music имеют анимированный mesh из 3-4 цветов.

**Решение:** Извлечь top-3 цвета из обложки → CSS mesh gradient с анимацией.

**Acceptance Criteria:**
- [ ] Извлекаются 3 доминирующих цвета из обложки
- [ ] CSS background: conic/radial gradient с 3 цветами
- [ ] Плавная CSS анимация (rotate/shift) ~20s loop
- [ ] Не влияет на производительность (GPU-accelerated)

### SKF-004: Global Haptic Feedback (P2)
**Проблема:** Вибрация только в Player, но не на остальных кнопках.

**Решение:** Утилита `haptic()` вызывается на всех интерактивных элементах: навигация, чарты, поиск, плейлисты.

**Acceptance Criteria:**
- [ ] `haptic("light")` на всех навигационных кнопках
- [ ] `haptic("medium")` на play/pause/skip
- [ ] `haptic("heavy")` на wave/shuffle/party mode

### SKF-005: Enhanced Crossfade / True Gapless (P2)
**Проблема:** Текущая реализация имеет паузу ~200ms при смене src. Нет перекрытия аудио.

**Решение:** Dual audio source technique невозможна через один MediaElementSource. Вместо этого — максимально сократить gap через prefetch + instant src swap + crossfade gain.

**Текущее состояние:** Уже реализовано: preload 30s + IndexedDB cache + crossfade gain ramp. Gap минимален (~50-100ms). Дополнительная оптимизация: убрать `audio.pause()` перед сменой src когда трек из кеша.
