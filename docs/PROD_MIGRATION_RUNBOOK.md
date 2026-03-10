# Production Migration Runbook

Дата: 2026-03-10
Scope: финальный rollout схемы/фич, закрытых в рамках MASTER_TZ (P0/P1)

## 1) Что выкатываем

Новые/обновлённые сущности и поля, которые должны быть в production DB:

- `daily_mixes`, `daily_mix_tracks`
- `share_links`
- `artist_watchlist`
- `release_notifications.opened_at`
- расширенные поля в `users`, `tracks`, `listening_history` (см. `bot/models/base.py` в `init_db`)

## 2) Preflight (до деплоя)

1. Проверить env:
   - `DATABASE_URL` указывает на production Postgres
   - `BOT_TOKEN`, `ADMIN_IDS` корректны
   - `YANDEX_*` и `ANALYTICS_EXPORT_*` заданы по целевой конфигурации
2. Снять backup БД (обязательно):
   - `pg_dump` для текущей production схемы
3. Убедиться, что в CI/локали зелёный пакет регрессии:
   - целевой комплект тестов P0/P1/DoD

## 3) Deployment sequence

1. Перевести бота в короткое maintenance окно (или rolling deploy с 1 активным writer).
2. Выкатить код.
3. Запустить приложение (`python -m bot.main`) и дождаться выполнения `init_db()`:
   - `create_all` создаст отсутствующие таблицы
   - `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` добавит недостающие поля для Postgres
4. Проверить логи старта:
   - нет ошибок `init_db failed`
   - нет repeated reconnect/fatal ошибок по БД

## 4) Post-deploy verification (обязательно)

### SQL smoke checks

Проверить наличие таблиц:

- `daily_mixes`
- `daily_mix_tracks`
- `share_links`
- `artist_watchlist`
- `release_notifications`

Проверить критичные колонки:

- `release_notifications.opened_at`
- `users.release_radar_enabled`
- `users.fav_artists`
- `users.badges`

### Functional smoke checks

1. `/mix`:
   - открытие микса
   - сохранение/шаринг/клон
2. Shared links:
   - `tr_`, `mx_`, `pl_` deep links
3. `/radar` + `settings releases off|on`
4. `/favorites` pagination
5. `/playlist export <name>`
6. Search flow:
   - duplicate download lock
   - lyrics long-text split
   - auto quality mode
7. Admin:
   - `/admin stats` содержит cache hit rate + latency

### Observability checks

- В Redis появляется `analytics:events`
- Если включён внешний sink, события уходят на `ANALYTICS_EXPORT_URL`
- Yandex token alert:
  - Redis ключ `alert:yandex_token_refresh_fail`
  - Telegram push админам (если `YANDEX_ALERT_TELEGRAM=true`)

## 5) Rollback plan

Если есть критическая деградация:

1. Остановить новый deployment.
2. Откатить приложение на предыдущий стабильный image/commit.
3. При необходимости восстановить БД из backup (только если была необратимая миграция; в текущем наборе изменения в основном additive).

## 6) Known notes

- Текущая стратегия миграций — runtime `init_db` + additive `ALTER ... IF NOT EXISTS`.
- Для enterprise-процесса рекомендуется переход на явные versioned migrations (Alembic).
