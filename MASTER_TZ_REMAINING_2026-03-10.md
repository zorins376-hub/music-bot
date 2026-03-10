# MASTER_TZ — что осталось

Дата аудита: 2026-03-10
Источник: [MASTER_TZ.md](MASTER_TZ.md)

## Легенда
- ✅ Готово
- ⚠️ Частично
- ❌ Не сделано

---

## 1. Краткий итог

По коду проект уже закрывает большую часть базового функционала: `Daily Mix`, `Favorites`, `Queue`, `Lyrics`, `Premium`, `Admin Stats`, `Release Radar`, TMA/Mini App, fuzzy/translit search, parallel provider search.

По локальной разработческой проверке ключевые требования MASTER_TZ закрыты.

Оставшийся финальный блок:
1. Production execution runbook (применение миграций и smoke-check в боевом окружении)

---

## 2. Что уже готово

### 2.1 Daily Mix
- ✅ Команда `/mix` есть: [bot/handlers/mix.py](bot/handlers/mix.py)
- ✅ Сервис получения/сборки микса есть: [bot/services/daily_mix.py](bot/services/daily_mix.py)
- ✅ Есть `save/share/clone` сценарии на уровне UI/Redis: [bot/handlers/mix.py](bot/handlers/mix.py)
- ✅ Favorites уже влияют на подбор треков: [bot/services/daily_mix.py](bot/services/daily_mix.py)

### 2.2 Favorites
- ✅ Модель есть: [bot/models/favorite.py](bot/models/favorite.py)
- ✅ DB функции есть: [bot/db.py](bot/db.py)
- ✅ `/favorites` и callback toggle есть: [bot/handlers/favorites.py](bot/handlers/favorites.py)
- ✅ Кнопка добавления в favorites после скачивания есть: [bot/handlers/search.py](bot/handlers/search.py)

### 2.3 Sharing / deeplinks
- ✅ Shared track deeplink есть: [bot/handlers/search.py](bot/handlers/search.py)
- ✅ Shared mix deeplink есть: [bot/handlers/mix.py](bot/handlers/mix.py)
- ✅ Shared playlist deeplink есть: [bot/handlers/playlist.py](bot/handlers/playlist.py)
- ✅ `/start` умеет открывать `tr_`, `mx_`, `pl_`: [bot/handlers/start.py](bot/handlers/start.py)

### 2.4 Release Radar
- ✅ Команда и toggle есть: [bot/handlers/release_radar.py](bot/handlers/release_radar.py)
- ✅ Scheduler/рассылка есть: [bot/services/release_radar.py](bot/services/release_radar.py)
- ✅ Модель уведомлений есть: [bot/models/release_notification.py](bot/models/release_notification.py)

### 2.5 Queue / Lyrics / Search / Premium / Admin
- ✅ Queue system: [bot/handlers/queue.py](bot/handlers/queue.py)
- ✅ Queue tests: [tests/test_queue.py](tests/test_queue.py)
- ✅ Lyrics provider: [bot/services/lyrics_provider.py](bot/services/lyrics_provider.py)
- ✅ Lyrics/TMA UI: [webapp/frontend/src/components/LyricsView.tsx](webapp/frontend/src/components/LyricsView.tsx)
- ✅ Fuzzy/translit search: [bot/services/search_engine.py](bot/services/search_engine.py), [bot/db.py](bot/db.py)
- ✅ Search tests: [tests/test_search_engine.py](tests/test_search_engine.py)
- ✅ Parallel provider search: [bot/handlers/search.py](bot/handlers/search.py)
- ✅ Premium/Stars: [bot/handlers/premium.py](bot/handlers/premium.py)
- ✅ Admin stats + audit log: [bot/handlers/admin.py](bot/handlers/admin.py), [bot/models/admin_log.py](bot/models/admin_log.py)

### 2.6 Mini App / WebApp
- ✅ Media Session API: [webapp/frontend/src/App.tsx](webapp/frontend/src/App.tsx)
- ✅ Dynamic colors: [webapp/frontend/src/colorExtractor.ts](webapp/frontend/src/colorExtractor.ts)
- ✅ Mini-player: [webapp/frontend/src/components/MiniPlayer.tsx](webapp/frontend/src/components/MiniPlayer.tsx)
- ✅ Swipe/haptic/marquee/skeletons/offline IndexedDB cache уже есть

---

## 3. Что сделано частично

### 3.1 EPIC-A: Daily Mix
**Статус:** ✅ Закрыто по P0-объему

Сделано:
- `/mix`
- кеширование на день через Redis
- влияние favorites/history на подбор
- save/share/clone в UI

Не хватает до ТЗ:
- ✅ таблицы `daily_mixes` и `daily_mix_tracks`
- ✅ отдельные модели + persistence flow в БД
- ✅ build/persist flow сервиса подтверждён тестами
- ✅ analytics: `mix_open`, `mix_save`, `mix_share` (+ `mix_clone`)
- ✅ happy-path tests добавлены

Файлы:
- [bot/services/daily_mix.py](bot/services/daily_mix.py)
- [bot/handlers/mix.py](bot/handlers/mix.py)
- [bot/models/base.py](bot/models/base.py)

### 3.2 EPIC-B: Share Track / Share Mix
**Статус:** ✅ Закрыто по P0-объему

Сделано:
- deeplink logic есть
- preview/open сценарии есть
- clone/save для микса и плейлиста есть
- ✅ DB-таблица `share_links` добавлена: [bot/models/share_link.py](bot/models/share_link.py)
- ✅ сервисы `create_share_link()` / `resolve_share_link()` добавлены: [bot/services/share_links.py](bot/services/share_links.py)
- ✅ click counter реализован в `resolve_share_link()`
- ✅ `search/mix/playlist` переведены с Redis share-ключей на DB share-links

Не хватает до ТЗ:
- ✅ analytics: `track_share`, `shared_track_open`, `mix_clone`
- ⚠️ исторические Redis-share ссылки (старого формата) не мигрируются автоматически (доп. совместимость, не блокер)

Файлы:
- [bot/handlers/search.py](bot/handlers/search.py)
- [bot/handlers/mix.py](bot/handlers/mix.py)
- [bot/handlers/playlist.py](bot/handlers/playlist.py)

### 3.3 EPIC-C: Release Radar
**Статус:** ✅ Закрыто по P1-объему

Сделано:
- включение/выключение пользователем
- фоновая рассылка релизов
- лог уведомлений

Не хватает до ТЗ:
- ✅ таблица `artist_watchlist`
- ✅ автоматический artist watchlist как отдельная сущность
- ✅ scheduler cadence переведён на шаг 6 часов
- ✅ `opened` tracking по уведомлению (`opened_at`)
- ✅ `release_open`, `release_opt_out` analytics
- ✅ соответствие `/settings releases off|on` из ТЗ

Файлы:
- [bot/services/release_radar.py](bot/services/release_radar.py)
- [bot/models/release_notification.py](bot/models/release_notification.py)
- [bot/handlers/release_radar.py](bot/handlers/release_radar.py)

### 3.4 EPIC-D: Favorites
**Статус:** ✅ Закрыто по P1-объему

Сделано:
- модель и уникальность
- add/remove callbacks
- `/favorites`
- влияние на mix

Не хватает до ТЗ:
- ✅ нормальная пагинация списка
- ✅ analytics `favorite_add`, `favorite_remove`
- ✅ edge-case tests по UX добавлены

Файлы:
- [bot/handlers/favorites.py](bot/handlers/favorites.py)
- [bot/models/favorite.py](bot/models/favorite.py)
- [bot/db.py](bot/db.py)

### 3.5 TASK-004: Fuzzy Search
**Статус:** ✅ Закрыто

Сделано:
- fuzzy/trigram search
- transliteration
- deduplication
- suggestions
- tests

Не хватает до ТЗ:
- ✅ `rapidfuzz` добавлен в зависимости
- ✅ интегрирован как prefered fuzzy scorer (с fallback)

Файлы:
- [bot/services/search_engine.py](bot/services/search_engine.py)
- [bot/db.py](bot/db.py)
- [tests/test_search_engine.py](tests/test_search_engine.py)
- [requirements.txt](requirements.txt)

### 3.6 TASK-014: Admin Stats Dashboard
**Статус:** ✅ Закрыто

Сделано:
- DAU/WAU/MAU
- top queries
- source split
- retention
- top tracks

Не хватает до ТЗ:
- ✅ cache hit rate в dashboard
- ✅ средняя latency в dashboard

Файлы:
- [bot/handlers/admin.py](bot/handlers/admin.py)

---

## 4. Что не сделано

### 4.1 BUG-001: Race Condition в скачивании
**Статус:** ✅ Закрыто

Реализовано:
- ✅ lock-ключ `download:{user_id}:{track_id}`
- ✅ download flow обёрнут acquire/release lock
- ✅ regression test на duplicate-click lock

### 4.2 BUG-003: Yandex Token Expiry
**Статус:** ✅ Закрыто

Сейчас реализовано:
- [bot/services/yandex_provider.py](bot/services/yandex_provider.py)
- [bot/config.py](bot/config.py)
- ✅ `YANDEX_TOKEN_EXPIRES_AT` / `YANDEX_TOKENS_EXPIRES_AT`
- ✅ проверка expiring-soon (<= 1 час)
- ✅ proactive ротация на неистекающий токен
- ✅ admin alert (через Redis alert-key + error log) при fail
- ✅ добавлены тесты expiry/alert: [tests/test_yandex_provider.py](tests/test_yandex_provider.py)

Осталось подтвердить:
- ✅ end-to-end прогон релевантных тестов в текущем окружении
- ✅ добавлен production-канал admin alert (Telegram push по BOT_TOKEN + ADMIN_IDS, с throttling)

### 4.3 TASK-003: Redis DDoS Protection
**Статус:** ✅ Закрыто

Реализована отдельная обертка `RateLimitedRedis` в cache-слое с configurable throttling.

### 4.4 TASK-009: Export playlists
**Статус:** ✅ Закрыто

Реализовано:
- ✅ `/playlist export {name}`
- ✅ TXT export
- ✅ кнопка экспорта в UI плейлиста

### 4.5 TASK-011: Lyrics Pagination
**Статус:** ✅ Закрыто

Реализовано серверное разбиение длинных lyrics/переводов на несколько сообщений с учетом лимита Telegram.

### 4.6 TASK-013: Smart Auto-Quality
**Статус:** ✅ Закрыто

Реализовано/подтверждено:
- ✅ режим `Авто` в `/settings`
- ✅ поведение по длительности и source (`_smart_bitrate`)
- ✅ downgrade при `file too large`
- ✅ отображение реального bitrate в caption

### 4.7 Analytics Events
**Статус:** ✅ Закрыто

Реализовано:
- ✅ `mix_open`, `mix_share`, `mix_save`, `mix_clone`
- ✅ `track_share`, `shared_track_open`
- ✅ `favorite_add`, `favorite_remove`
- ✅ `release_open`, `release_opt_out`
- Файлы: [bot/services/analytics.py](bot/services/analytics.py), [bot/handlers/mix.py](bot/handlers/mix.py), [bot/handlers/search.py](bot/handlers/search.py), [bot/handlers/favorites.py](bot/handlers/favorites.py), [bot/handlers/release_radar.py](bot/handlers/release_radar.py)

Осталось для полного закрытия:
- ✅ добавлен optional внешний HTTP-exporter (env-driven) + сохранён fallback в structured log + Redis buffer

### 4.8 Definition of Done gaps
**Статус:** ✅ Локально закрыто (production rollout отдельно)

Для новых фич подтверждено:
- ✅ миграция/модель/таблица по ТЗ на уровне кода и локальных тестов (production execution pass остаётся отдельным операционным шагом)
- ✅ i18n для новых user-facing веток
- ✅ happy/edge tests для закрытых P0/P1 задач
- ✅ analytics/logging
- ✅ fallback behavior
- ✅ full regression: `575 passed` (локальный прогон `pytest -q`)

---

## 5. Дополнительно: roadmap 2026

### Уже есть за пределами ТЗ-минимума
- referral system: [bot/handlers/referral.py](bot/handlers/referral.py)
- расширенный TMA player
- achievements / leaderboard
- story cards
- AI DJ voice / DJ comments

### Не найдено из roadmap/backlog
- ❌ Family plan
- ✅ формальный `share_links` domain layer
- ✅ `artist_watchlist`
- ❌ полноценный PWA/service worker offline cache
- ⚠️ часть Mini App killer-фич реализована, часть нет

---

## 6. Рекомендуемый порядок продолжения

### P0 — сначала
1. ✅ BUG-001: lock на скачивание одного трека
2. ✅ BUG-003: Yandex token expiry / refresh (ядро)
3. ✅ Daily Mix persistence в БД (`daily_mixes`, `daily_mix_tracks`)
4. ✅ Share Links domain layer + click counter
5. ✅ Analytics events для mix/share/favorites/radar

### P1 — потом
6. ✅ Release Radar через `artist_watchlist`
7. ✅ Favorites pagination + tests
8. ✅ Playlist export
9. ✅ Admin stats: cache hit rate + latency
10. ✅ DoD cleanup по тестам и миграциям (локальный финальный проход)

### P2 — потом
11. ✅ Smart auto-quality
12. ✅ Lyrics pagination polish
13. ✅ Redis DDoS protection abstraction
14. Оставшиеся Mini App / roadmap items

---

## 7. Самый короткий вывод

P0/P1 по ключевым фичам закрыты и локальный DoD pass завершен (включая full regression).
Остались:
- production execution runbook (боевые миграции/smoke);
- roadmap-элементы вне минимального MASTER_TZ.

Подготовлено:
- ✅ production migration runbook: [docs/PROD_MIGRATION_RUNBOOK.md](docs/PROD_MIGRATION_RUNBOOK.md)
