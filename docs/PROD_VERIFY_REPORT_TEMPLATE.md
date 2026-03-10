# Production Verify Report (Template)

Дата/время (UTC):

Окружение:
- DATABASE_URL: `<redacted-host/db>`
- Release tag/commit:
- Исполнитель:

Команды:
- [ ] `make prod-db-backup-and-assert`
- [ ] `make prod-db-smoke`
- [ ] (или) `make prod-db-verify-all`

Результат:
- [ ] PASS
- [ ] FAIL

Ключевые проверки:
- [ ] required tables
- [ ] required columns
- [ ] required constraints/indexes
- [ ] row-count sanity

Backup:
- Файл:

Наблюдаемость:
- [ ] `analytics:events` updated
- [ ] external analytics sink (if enabled)
- [ ] yandex alert path sanity

Итоговое решение:
- [ ] rollout continue
- [ ] rollback

Комментарий: