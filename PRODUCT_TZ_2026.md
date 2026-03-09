# BLACK ROOM Music Bot — продуктовое ТЗ и roadmap 2026

## 1. Цель

Сделать BLACK ROOM лучшим Telegram music bot в RU/CIS-сегменте по трём критериям:
- **скорость**: минимальное время от запроса до проигрывания/отправки трека;
- **персонализация**: рекомендации и миксы лучше, чем у обычных music bots;
- **вирусность**: пользователи сами приводят новых пользователей через sharing, deep-links и referrals.

---

## 2. Продуктовая стратегия

### 2.1 Основное позиционирование
BLACK ROOM — это не просто «бот для скачивания треков», а **музыкальный ассистент**:
- ищет музыку по нескольким источникам;
- понимает естественные запросы;
- рекомендует музыку по вкусу;
- позволяет делиться треками, плейлистами и миксами;
- даёт пользователю быстрый способ получить музыку «под момент».

### 2.2 Ключевые differentiators
1. **Самый быстрый поиск и отдача трека**
2. **Умные рекомендации и миксы**
3. **Нативный Telegram UX**
4. **Deep-link sharing всего контента**
5. **Премиум с реальной ценностью, а не только 320 kbps**

---

## 3. Главные продуктовые KPI

### 3.1 North Star Metric
**Successful Plays per Active User / Week**

### 3.2 Core KPI
- Search → Play conversion
- Time to First Track
- D1 / D7 / D30 retention
- Share rate
- Referral conversion
- Premium conversion
- Failed search rate
- Download success rate
- Avg plays per user per day

### 3.3 Целевые ориентиры
- Search → Play conversion: **> 70%**
- Failed search rate: **< 10%**
- Time to First Track: **< 6 сек** для кеша, **< 15 сек** для нового трека
- D7 retention: **> 25%**
- Share rate: **> 8%**
- Premium conversion: **> 2.5%**

---

## 4. Целевая аудитория

### Сегмент A — core users
- слушают музыку ежедневно;
- хотят быстро получить трек в Telegram;
- часто делятся музыкой с друзьями.

### Сегмент B — vibe / playlist users
- хотят подборки под настроение;
- меньше знают конкретные треки;
- ценят рекомендации и готовые миксы.

### Сегмент C — community / groups
- используют бота в чатах;
- шарят музыку в компаниях;
- потенциально приносят органический рост.

---

## 5. Product pillars

## PILLAR 1 — Скорость и надёжность

### Цель
Пользователь должен получать музыку быстрее, чем у конкурентов.

### Требования
1. Приоритет выдачи:
   - локальный кеш/file_id;
   - локальная БД;
   - внешние источники;
   - fallback на альтернативный источник.
2. Предзагрузка популярных треков.
3. Умный retry при ошибке провайдера.
4. Автоматический fallback на другой source.
5. Отдельный мониторинг latency по каждому source.

### Фичи
- Hot cache top-100/500 треков
- Retry matrix по провайдерам
- Fast path для history / queue / favorites
- Health score провайдеров

### Метрика успеха
- Снижение времени до первого трека минимум на 30%

---

## PILLAR 2 — Персонализация

### Цель
Сделать так, чтобы пользователь возвращался не только за конкретными треками, но и за подбором.

### Фичи
1. **Smart onboarding v2**
   - любимые артисты;
   - любимые жанры;
   - настроение;
   - язык музыки.
2. **Daily Mix**
3. **Weekly Mix**
4. **Release Radar**
5. **Continue the vibe**
6. **After-track recommendations**
7. **Taste profile**

### Требования
- рекомендации должны учитывать:
  - историю скачиваний/прослушиваний;
  - лайки/дизлайки;
  - жанры;
  - время суток;
  - день недели;
  - повторяемость артистов.

### Метрика успеха
- +20% к D7 retention
- +15% к plays per user

---

## PILLAR 3 — Вирусность и social mechanics

### Цель
Чтобы пользователи сами приводили новых пользователей.

### Фичи
1. Share track
2. Share playlist
3. Share queue
4. Share mix
5. Share top of week
6. Referral system v2
7. Deep-links на конкретный трек / плейлист / микс
8. Совместные плейлисты (collaborative playlists)

### Требования
- каждый shared object должен иметь deep-link;
- recipient должен иметь one-tap action:
  - открыть;
  - сохранить себе;
  - скачать;
  - клонировать;
- после перехода по ссылке — минимальный friction.

### Метрика успеха
- share rate > 8%
- referral activation rate > 20%

---

## PILLAR 4 — Premium monetization

### Цель
Сделать Premium ценным и понятным.

### Текущее ядро
- выше лимиты;
- меньше cooldown;
- 320 kbps.

### Нужно добавить value
1. Fast lane downloads
2. Unlimited smart mixes
3. Advanced recommendations
4. Release radar for favorite artists
5. Lyrics + translation
6. Playlist export pack
7. Priority search queue
8. Extended history / recap

### Монетизация
- Telegram Stars subscription
- gift premium
- temporary boosts
- premium packs

### Метрика успеха
- Premium conversion > 2.5%
- paid retention > 60% monthly

---

## PILLAR 5 — Естественный язык и AI UX

### Цель
Пользователь должен общаться с ботом как с музыкальным помощником.

### Фичи
1. Поиск на естественном языке:
   - «включи что-то как Travis Scott, но спокойнее»
   - «русский рэп для дороги»
   - «поставь ночной вайб»
2. AI playlist generator
3. Mood radio
4. Prompt-based playlist edit:
   - «сделай плейлист мягче»
   - «убери грустные треки»
   - «добавь больше женского вокала»
5. Voice mode

### Метрика успеха
- рост использования рекомендаций;
- рост сессий без точного search query.

---

## 6. Product roadmap

## Sprint 1 — Must Have

### EPIC-001: Daily Mix
**Priority:** P0

**User story:**
Как пользователь, я хочу одним нажатием получить персональный микс на сегодня.

**Функционал:**
- кнопка `Daily Mix` в главном меню;
- 20-30 треков;
- строится из истории + похожих артистов/жанров;
- обновляется раз в 24 часа;
- можно сохранить в плейлист.

**Acceptance criteria:**
- у пользователя всегда есть доступный микс;
- одинаковый микс в течение суток;
- новый микс на следующий день.

---

### EPIC-002: Share Track / Share Mix / Share Playlist v2
**Priority:** P0

**User story:**
Как пользователь, я хочу делиться не только плейлистом, но и конкретным треком/миксом.

**Функционал:**
- кнопка `Поделиться` у трека;
- deep-link на трек;
- deep-link на микс;
- улучшенный shared playlist flow;
- кнопки `Сохранить себе`, `Скачать`, `Открыть плейлист`.

**Acceptance criteria:**
- share link открывается у другого пользователя;
- контент можно клонировать себе в 1 действие.

---

### EPIC-003: Release Radar
**Priority:** P0

**User story:**
Как пользователь, я хочу получать новые релизы любимых артистов.

**Функционал:**
- мониторинг favorite artists;
- уведомление 1 раз в день;
- раздел `Новые релизы`.

**Acceptance criteria:**
- пользователь получает релизы только по релевантным артистам;
- можно отключить уведомления.

---

### EPIC-004: After-track autoplay
**Priority:** P0

**User story:**
Как пользователь, я хочу после трека сразу получать следующий подходящий трек.

**Функционал:**
- кнопка `Ещё похожее`;
- autoplay mode;
- продолжение по жанру / артисту / вайбу.

---

## Sprint 2 — Growth

### EPIC-005: Lyrics + translation
**Priority:** P1

### EPIC-006: Taste Profile
**Priority:** P1

### EPIC-007: Weekly Recap
**Priority:** P1

### EPIC-008: Smart onboarding v2
**Priority:** P1

### EPIC-009: Favorites / liked tracks
**Priority:** P1

---

## Sprint 3 — Moat / WOW

### EPIC-010: AI playlist generator by prompt
**Priority:** P2

### EPIC-011: Collaborative playlists
**Priority:** P2

### EPIC-012: Mood radio
**Priority:** P2

### EPIC-013: Voice mode
**Priority:** P2

### EPIC-014: Smart DJ transitions
**Priority:** P2

---

## 7. Полный backlog TOP-20

| # | Feature | Impact | Complexity | Revenue | Priority |
|---|---------|--------|------------|---------|----------|
| 1 | Daily Mix | High | Medium | Medium | P0 |
| 2 | Share Track | High | Medium | Medium | P0 |
| 3 | Share Mix | High | Medium | Medium | P0 |
| 4 | Release Radar | High | Medium | High | P0 |
| 5 | After-track autoplay | High | Low | Medium | P0 |
| 6 | Lyrics + translation | Medium | Medium | Medium | P1 |
| 7 | Taste profile | Medium | Medium | Low | P1 |
| 8 | Weekly recap | Medium | Medium | Medium | P1 |
| 9 | Favorites | High | Low | Low | P1 |
|10 | Smart onboarding v2 | High | Low | Medium | P1 |
|11 | AI playlist generator | High | High | High | P2 |
|12 | Collaborative playlists | High | High | Medium | P2 |
|13 | Mood radio | High | High | High | P2 |
|14 | Voice mode | Medium | High | Medium | P2 |
|15 | Smart DJ transitions | Medium | High | High | P2 |
|16 | Smart queue editor | Medium | Medium | Low | P2 |
|17 | Gift premium | Medium | Low | High | P2 |
|18 | Export playlist pack | Medium | Medium | High | P2 |
|19 | Group social listening | Medium | High | Medium | P3 |
|20 | Concert / merch affiliate | Low | Medium | High | P3 |

---

## 8. UX / интерфейсные улучшения

### Главное меню
Добавить быстрые product-entry points:
- Daily Mix
- Продолжить вайб
- Любимое
- Новые релизы
- Поделиться треком

### Карточка трека
Добавить кнопки:
- ❤️ В любимое
- ➕ В плейлист
- 🔁 Похожее
- 📤 Поделиться
- 📝 Текст

### Профиль
Добавить блоки:
- любимые жанры;
- top artists;
- weekly stats;
- premium status;
- taste profile.

---

## 9. Data / analytics requirements

### Нужно логировать
- source поиска;
- query → result clicked;
- search failure reason;
- share created;
- share opened;
- referral activated;
- premium purchase step;
- recommendation accepted / skipped;
- playlist save / clone.

### Нужно построить дашборды
1. Search funnel
2. Recommendation funnel
3. Premium funnel
4. Referral funnel
5. Retention cohorts

---

## 10. Риски

1. Слишком много фич без retention-ядра
2. Слабая персонализация убьёт Daily Mix
3. Медленная выдача сломает product perception
4. Premium без ценности не будет конвертить
5. Плохой share flow не даст виральности

---

## 11. Порядок реализации

### Фаза 1 — growth foundation
1. Daily Mix
2. Share Track / Share Mix
3. Release Radar
4. After-track autoplay
5. Favorites

### Фаза 2 — retention + premium
6. Lyrics + translation
7. Taste Profile
8. Weekly Recap
9. Smart onboarding v2
10. Premium value expansion

### Фаза 3 — moat
11. AI playlist generator
12. Collaborative playlists
13. Mood radio
14. Voice mode
15. Smart DJ experience

---

## 12. Definition of Done

Фича считается завершённой только если:
- есть backend-логика;
- есть Telegram UX;
- есть аналитика;
- есть обработка ошибок;
- есть rate limits / anti-abuse при необходимости;
- есть тесты на happy path и edge cases;
- есть rollout plan и success metric.

---

## 13. Рекомендуемый следующий шаг

Сразу брать в работу:
1. **Daily Mix**
2. **Share Track / Share Mix**
3. **Release Radar**

Это даст лучший баланс между:
- продуктовой ценностью;
- удержанием;
- виральностью;
- шансом на Premium growth.
