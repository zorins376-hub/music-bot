# BLACK ROOM — dev-ready ТЗ для разработки

## 1. Назначение документа

Этот документ переводит продуктовое ТЗ в **готовый к разработке план**:
- что делать в коде;
- какие таблицы и поля добавить;
- какие handlers/services менять;
- какие события логировать;
- какие тесты написать;
- в каком порядке внедрять.

Документ ориентирован на текущую архитектуру проекта:
- aiogram 3
- SQLAlchemy async
- PostgreSQL / SQLite
- Redis
- `bot/handlers/*`
- `bot/services/*`
- `bot/models/*`

---

## 2. Текущие точки интеграции

## 2.1 Главное меню
Текущая точка входа: [bot/handlers/start.py](bot/handlers/start.py)

Сейчас уже есть кнопки:
- `action:recommend`
- `action:playlist`
- `action:charts`
- `action:premium`
- `action:faq`
- `action:search`
- `action:video`
- radio actions

## 2.2 Рекомендации
Текущая точка: [bot/handlers/recommend.py](bot/handlers/recommend.py)

Есть:
- onboarding;
- `_show_recommendations()`;
- fallback на YouTube;
- integration с `recommender/ai_dj.py`.

## 2.3 Плейлисты и sharing
Текущая точка: [bot/handlers/playlist.py](bot/handlers/playlist.py)

Уже реализовано:
- share playlist через deep-link;
- clone shared playlist;
- import JSON.

## 2.4 История и треки
Текущие модели:
- [bot/models/track.py](bot/models/track.py)
- [bot/models/user.py](bot/models/user.py)

Уже есть:
- `Track`
- `ListeningHistory`
- user profile fields: `fav_genres`, `fav_artists`, `fav_vibe`, `onboarded`

## 2.5 Фоновые задачи
Текущая точка: [bot/services/daily_digest.py](bot/services/daily_digest.py)

Это правильное место/паттерн для новых background jobs:
- Release Radar
- Daily Mix precompute
- Weekly recap

---

## 3. Приоритет на реализацию

Для первой волны разработки берём 4 epic:

1. **EPIC-A: Daily Mix**
2. **EPIC-B: Share Track / Share Mix**
3. **EPIC-C: Release Radar**
4. **EPIC-D: Favorites / Liked Tracks**

Причина:
- дают retention;
- дают viral loop;
- дают хороший фундамент для Premium;
- хорошо ложатся в текущую архитектуру.

---

# 4. EPIC-A — Daily Mix

## 4.1 Цель
Пользователь получает персональный ежедневный микс в 1 клик.

## 4.2 User story
Как пользователь, я хочу открыть `Daily Mix` и получить подборку на сегодня, собранную на основе моих прослушиваний и вкусов.

## 4.3 UX
### Entry points
1. Кнопка в главном меню: `✦ DAILY MIX`
2. Команда `/mix`
3. Кнопка `Сохранить микс`
4. Кнопка `Поделиться миксом`

### User flow
1. Пользователь нажимает `Daily Mix`
2. Бот показывает список 20–30 треков
3. Пользователь:
   - открывает трек;
   - сохраняет микс в плейлист;
   - делится ссылкой;
   - генерирует заново завтра

## 4.4 Правила генерации
Источник кандидатов:
1. локальная БД `Track`
2. история пользователя `ListeningHistory`
3. liked tracks
4. похожие жанры / артисты
5. popular fallback

### Базовый алгоритм v1
Score трека:
- +3 если artist в `fav_artists`
- +2 если genre в `fav_genres`
- +2 если track похож на recently played
- +1 если downloads высокий
- -2 если трек уже был в последних 7 daily mixes
- -3 если трек недавно проигрывался сегодня

### Ограничения
- не более 2 треков подряд от одного артиста;
- не более 30% повторов из последних 7 дней;
- длина микса 20–30 треков;
- один и тот же микс в течение суток.

## 4.5 Данные / БД
### Новые таблицы

#### `daily_mixes`
- `id`
- `user_id`
- `mix_date`
- `title`
- `created_at`
- `source` (`daily_mix`)

#### `daily_mix_tracks`
- `id`
- `mix_id`
- `track_id`
- `position`
- `score`
- `reason` (json/text, why selected)

### Индексы
- `(user_id, mix_date)` unique
- `(mix_id, position)`

## 4.6 Backend changes
### New files
- `bot/models/daily_mix.py`
- `bot/services/daily_mix.py`

### Files to update
- [bot/handlers/start.py](bot/handlers/start.py) — новая кнопка `Daily Mix`
- [bot/handlers/recommend.py](bot/handlers/recommend.py) — reuse UI patterns
- [bot/main.py](bot/main.py) — register command `/mix`
- [bot/models/base.py](bot/models/base.py) — migration SQL
- [bot/i18n/ru.json](bot/i18n/ru.json)
- [bot/i18n/en.json](bot/i18n/en.json)
- [bot/i18n/kg.json](bot/i18n/kg.json)

## 4.7 Handler contract
### Command
- `/mix`

### Callback actions
- `mix:open`
- `mix:save`
- `mix:share`
- `mix:refresh_info`

## 4.8 Service contract
### `get_or_create_daily_mix(user_id: int, date: date) -> DailyMixDTO`
Возвращает существующий микс за день либо генерирует новый.

### `build_daily_mix(user_id: int, limit: int = 25) -> list[TrackDTO]`
Собирает треки и score.

### `share_daily_mix(user_id: int, mix_id: int) -> str`
Возвращает deep-link.

## 4.9 Analytics events
- `daily_mix_opened`
- `daily_mix_track_clicked`
- `daily_mix_saved`
- `daily_mix_shared`
- `daily_mix_cloned`

## 4.10 Acceptance criteria
- при первом открытии за день создаётся микс;
- при втором открытии в тот же день отдаётся тот же набор;
- на следующий день создаётся новый;
- можно сохранить микс в плейлист;
- можно поделиться ссылкой;
- mix generation fallback работает даже при слабой истории.

## 4.11 Tests
### Unit
- ranking logic
- anti-duplicate rules
- same-day cache behavior

### Integration
- `/mix` returns keyboard and tracks
- save mix to playlist
- share mix deep-link opens correctly

---

# 5. EPIC-B — Share Track / Share Mix

## 5.1 Цель
Сделать sharing не только для плейлистов, но и для треков и daily mix.

## 5.2 User stories
- Как пользователь, я хочу поделиться конкретным треком.
- Как пользователь, я хочу поделиться ежедневным миксом.
- Как новый пользователь, я хочу открыть ссылку и сохранить контент себе.

## 5.3 UX
### Track card buttons
Добавить к карточке/сообщению трека:
- `❤️`
- `➕ В плейлист`
- `🔁 Похожее`
- `📤 Поделиться`
- `📝 Текст`

### Share track flow
1. пользователь скачал трек;
2. нажал `📤 Поделиться`;
3. бот отправляет deep-link;
4. другой пользователь открывает;
5. видит карточку трека и кнопку `Скачать себе`.

### Share mix flow
1. пользователь открыл daily mix;
2. нажал `Поделиться миксом`;
3. получатель открывает список;
4. может клонировать в плейлист.

## 5.4 Data / storage
Использовать Redis как и в playlist sharing, но через единый namespace.

### Key format
- `share:track:{share_id}`
- `share:mix:{share_id}`
- `share:playlist:{share_id}`

### TTL
- 30 days default

## 5.5 Backend changes
### New service
- `bot/services/share_links.py`

### Responsibilities
- create share payload
- resolve share payload
- validate owner/resource
- abstract Redis storage

### Files to update
- [bot/handlers/search.py](bot/handlers/search.py)
- [bot/handlers/playlist.py](bot/handlers/playlist.py)
- [bot/handlers/start.py](bot/handlers/start.py)
- [bot/handlers/recommend.py](bot/handlers/recommend.py)

## 5.6 Deep-link formats
- `/start tr_<share_id>` — shared track
- `/start mx_<share_id>` — shared mix
- `/start pl_<share_id>` — existing playlist format

## 5.7 Acceptance criteria
- share track link opens on fresh user;
- shared track can be downloaded;
- shared mix can be cloned to playlist;
- expired links show friendly message;
- share generation unavailable if Redis down -> graceful error.

## 5.8 Tests
- track deep-link open
- mix deep-link open
- expired share
- invalid share id
- unauthorized resource access impossible

---

# 6. EPIC-C — Release Radar

## 6.1 Цель
Присылать пользователю новые релизы артистов, которых он реально слушает.

## 6.2 User story
Как пользователь, я хочу получать уведомления о новых релизах любимых артистов, чтобы не пропускать новую музыку.

## 6.3 Источники данных
V1:
- Spotify API metadata
- Yandex search fallback
- optional YouTube metadata fallback

## 6.4 Формирование favorite artists
Источники сигнала:
- `fav_artists`
- `ListeningHistory` top artists за 30 дней
- liked tracks top artists

## 6.5 Частота
- scheduler 1 раз в сутки
- не больше 1 уведомления на пользователя в день
- только если есть релевантные новые релизы

## 6.6 Data / БД
### Новые таблицы
#### `artist_watchlist`
- `id`
- `user_id`
- `artist_name`
- `normalized_name`
- `source`
- `weight`
- `created_at`

#### `release_notifications`
- `id`
- `user_id`
- `artist_name`
- `release_title`
- `release_id`
- `sent_at`

### Уникальность
- `(user_id, release_id)` unique

## 6.7 Backend changes
### New files
- `bot/models/release_radar.py`
- `bot/services/release_radar.py`

### Files to update
- [bot/main.py](bot/main.py) — старт scheduler
- [bot/services/daily_digest.py](bot/services/daily_digest.py) — reuse loop pattern or split common scheduler base
- [bot/handlers/recommend.py](bot/handlers/recommend.py) — update watchlist from onboarding
- [bot/db.py](bot/db.py) — helpers for top artists

## 6.8 Notification format
Message example:
- артист
- релиз
- 1–3 трека / ссылка на открыть
- кнопка `Найти в боте`
- кнопка `Отключить уведомления`

## 6.9 Acceptance criteria
- уведомление не дублится;
- нерелевантные артисты не спамят;
- пользователь может отключить release radar;
- только новые релизы.

## 6.10 Tests
- dedupe by release_id
- no resend same release
- watchlist builder from history
- opt-out works

---

# 7. EPIC-D — Favorites / Liked Tracks

## 7.1 Цель
Сделать явный позитивный сигнал для рекомендаций, retention и release radar.

## 7.2 User story
Как пользователь, я хочу сохранять любимые треки, чтобы быстро к ним возвращаться и чтобы бот лучше понимал мой вкус.

## 7.3 UX
- кнопка `❤️` на карточке трека;
- команда `/favorites`;
- список любимых треков;
- возможность удалить из favorites.

## 7.4 Data / БД
### Таблица `favorite_tracks`
- `id`
- `user_id`
- `track_id`
- `created_at`

### Уникальность
- `(user_id, track_id)` unique

## 7.5 Backend changes
### New file
- `bot/models/favorite.py`

### Update files
- [bot/handlers/search.py](bot/handlers/search.py)
- [bot/handlers/recommend.py](bot/handlers/recommend.py)
- [bot/main.py](bot/main.py)
- [bot/models/base.py](bot/models/base.py)

## 7.6 Acceptance criteria
- можно добавить трек в favorites;
- можно удалить;
- favorites влияют на Daily Mix и Release Radar;
- дубликаты не создаются.

---

# 8. Изменения в главном меню

## 8.1 Новый layout
Рекомендуемый layout:

Row 1:
- `▸ TEQUILA LIVE`
- `◑ FULLMOON LIVE`

Row 2:
- `✦ DAILY MIX`
- `◈ По вашему вкусу`

Row 3:
- `◈ Найти трек`
- `🎦 Видео`

Row 4:
- `❤️ Любимое`
- `🏆 Топ-чарты`

Row 5:
- `▸ Плейлисты`
- `🆕 Новые релизы`

Row 6:
- `◇ Premium`
- `◉ Профиль`

Row 7:
- `❓ FAQ`

---

# 9. Аналитика и события

Нужно ввести единый helper, например:
- `bot/services/analytics.py`

### API
`track_event(user_id: int, event: str, **props)`

### События первой волны
- `mix_open`
- `mix_share`
- `mix_clone`
- `track_share`
- `shared_track_open`
- `favorite_add`
- `favorite_remove`
- `release_open`
- `release_opt_out`

Если отдельная аналитика не готова — временно писать в structured logs.

---

# 10. Поэтапный план реализации

## Phase 1 — Favorites
Потому что это быстрый фундамент под всё остальное.

### Tickets
1. Создать `favorite_tracks`
2. Добавить model + migration
3. Добавить кнопку `❤️`
4. Добавить `/favorites`
5. Интегрировать в рекомендации
6. Тесты

## Phase 2 — Daily Mix
### Tickets
1. Создать tables `daily_mixes`, `daily_mix_tracks`
2. Реализовать `build_daily_mix()`
3. Реализовать `/mix`
4. Добавить кнопку в menu
5. Добавить `save mix`
6. Добавить `share mix`
7. Тесты

## Phase 3 — Share Track
### Tickets
1. Вынести sharing в `share_links.py`
2. Реализовать track deep-link
3. Реализовать start handler for `tr_`
4. Добавить button `📤 Поделиться`
5. Тесты

## Phase 4 — Release Radar
### Tickets
1. Создать watchlist tables
2. Собрать top artists builder
3. Реализовать release fetch service
4. Реализовать scheduler
5. Реализовать opt-out
6. Тесты

---

# 11. Детальные технические требования

## 11.1 Код-стандарты
- без циклических импортов;
- бизнес-логика в `services/`, не в handlers;
- handlers только orchestration/UI;
- reuse existing cache patterns;
- все новые callback_data — через typed callbacks при возможности.

## 11.2 Ошибки и fallback
- все новые фичи должны работать fail-soft;
- если Redis недоступен — sharing gracefully fails;
- если recommendation engine пустой — fallback на popular/local db;
- если release provider упал — no notification, no spam.

## 11.3 i18n
Все новые тексты сразу в:
- `ru.json`
- `en.json`
- `kg.json`

## 11.4 Безопасность
- owner validation обязательна для всех share payloads;
- callback data не должна позволять доступ к чужим ресурсам;
- никакой чувствительной информации в deep-link payload.

---

# 12. Definition of Done

Каждый epic завершён только если:
1. есть migration;
2. есть model/service/handler;
3. есть i18n;
4. есть happy-path тесты;
5. есть edge-case тесты;
6. есть analytics/logging;
7. есть fallback behavior;
8. есть user-facing copy.

---

# 13. Ready-to-code order

Если начинать прямо сейчас, порядок такой:

## Шаг 1
**Favorites**
- самый быстрый dev cycle;
- нужен для улучшения recommend / mix / radar.

## Шаг 2
**Daily Mix**
- главный retention feature.

## Шаг 3
**Share Track / Share Mix**
- главный viral feature.

## Шаг 4
**Release Radar**
- retention + premium value.

---

# 14. Что можно брать в работу немедленно

## Ready now
- Favorites
- Daily Mix v1
- Share Track v1

## Needs research/API checks
- Release Radar provider quality
- Release dedupe by source ids
- artist normalization quality

---

# 15. Рекомендация по следующему действию

Следующий практический шаг для разработки:

**Начать с EPIC-D Favorites**, затем сразу перейти в **EPIC-A Daily Mix**.

Это даст:
- быстрый visible feature;
- фундамент данных;
- улучшение recommend quality;
- подготовку к Release Radar.
