# Production Deploy Checklist (Quick)

Дата: 2026-03-10  
Подробный runbook: [PROD_MIGRATION_RUNBOOK.md](PROD_MIGRATION_RUNBOOK.md)

## 0) Preflight

- [ ] Проверить env в production:
  - `DATABASE_URL`
  - `BOT_TOKEN`
  - `ADMIN_IDS`
  - `YANDEX_*` (если используется)
  - `ANALYTICS_EXPORT_*` (если используется)
- [ ] Снять backup БД:

```bash
pg_dump "$DATABASE_URL" > backup_pre_deploy_$(date +%Y%m%d_%H%M%S).sql
```

## 1) Deploy

- [ ] Включить maintenance window / оставить 1 writer
- [ ] Выкатить новый image/commit
- [ ] Запустить приложение и дождаться завершения `init_db()`

```bash
python -m bot.main
```

## 2) DB Smoke (обязательно)

- [ ] Таблицы существуют: `daily_mixes`, `daily_mix_tracks`, `share_links`, `artist_watchlist`, `release_notifications`
- [ ] Поля существуют: `release_notifications.opened_at`, `users.release_radar_enabled`, `users.fav_artists`, `users.badges`

Пример SQL-проверки:

```sql
SELECT to_regclass('public.daily_mixes');
SELECT to_regclass('public.daily_mix_tracks');
SELECT to_regclass('public.share_links');
SELECT to_regclass('public.artist_watchlist');
SELECT to_regclass('public.release_notifications');
```

Полный smoke-скрипт (таблицы, колонки, constraints/indexes, row-count):

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f docs/PROD_DB_SMOKE.sql
```

Strict assert-скрипт (fail-fast, удобно как CI/CD gate):

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f docs/PROD_DB_ASSERT.sql
```

Альтернатива через Makefile:

```bash
make prod-db-smoke
make prod-db-assert
make prod-db-backup-and-assert
make prod-db-verify-all
make prod-verify-report
make prod-verify-report COMMIT=release-2026-03-10 OPERATOR=devops
make prod-verify-report-no-backup COMMIT=hotfix OPERATOR=oncall
make prod-verify-report-dry-run COMMIT=preview OPERATOR=oncall
make prod-verify-report-rotate KEEP=30 COMMIT=release OPERATOR=devops
```

Если `make` не установлен (частый кейс на Windows), запускай напрямую:

```powershell
pwsh -File scripts/prod_verify.ps1 -DryRun -NoBackup -Commit preview -Operator oncall
```

Или через Windows launcher:

```bat
scripts\prod_verify.cmd -DryRun -NoBackup -Commit preview -Operator oncall
```

Шпаргалка команд: `scripts/prod_verify_help.txt`.
Единая ops-шпаргалка: `scripts/ops_help.txt`.
Быстрый статус среды: `scripts/status.cmd` (или `pwsh -File scripts/status.ps1`).
Для cleanup отчётов/логов можно использовать ротацию (`-RotateArtifacts`, `-KeepArtifacts`).
Безопасный диапазон `KeepArtifacts`: `1..500`.

Перед ручным прогоном можно валидировать launcher-скрипты:

```powershell
pwsh -File scripts/smoke_scripts.ps1
```

Windows shortcut:

```bat
scripts\smoke_scripts.cmd
```

Standalone cleanup (без verify):

```bash
make cleanup-reports KEEP=30
make cleanup-reports-dry-run KEEP=30
```

Windows launcher для cleanup:

```bat
scripts\cleanup_reports.cmd -KeepArtifacts 30 -DryRun
```

Unified launcher (Windows):

```bat
scripts\ops.cmd verify -DryRun -NoBackup -Commit preview -Operator oncall
scripts\ops.cmd cleanup -KeepArtifacts 30 -DryRun
scripts\ops.cmd status
scripts\ops.cmd smoke
scripts\ops.cmd report -Commit release-2026-03-10 -Operator devops
```

PowerShell unified launcher:

```powershell
pwsh -File scripts/ops.ps1 verify -DryRun -NoBackup -Commit preview -Operator oncall
pwsh -File scripts/ops.ps1 cleanup -KeepArtifacts 30 -DryRun
pwsh -File scripts/ops.ps1 status
pwsh -File scripts/ops.ps1 smoke
pwsh -File scripts/ops.ps1 report -Commit release-2026-03-10 -Operator devops
```

Make shortcut:

```bash
make prod-new-report COMMIT=release-2026-03-10 OPERATOR=devops
```

PowerShell-скрипт сохранит отчёт и лог в `docs/reports/`.
Если `COMMIT` не передан, скрипт попытается автоматически взять текущий `git rev-parse --short HEAD`.
Если `OPERATOR` не передан, скрипт возьмёт `$env:USERNAME` (или `$env:USER`).
Если `make` недоступен, скрипт автоматически переключится на прямой запуск `pg_dump/psql`.

## 3) Functional Smoke (обязательно)

- [ ] `/mix` (open/save/share/clone)
- [ ] deeplink `/start tr_...`, `/start mx_...`, `/start pl_...`
- [ ] `/radar` + `settings releases off|on`
- [ ] `/favorites` pagination
- [ ] `/playlist export <name>`
- [ ] search-flow: duplicate lock, long lyrics split, auto quality
- [ ] `/admin stats`: есть cache hit rate и latency

## 4) Observability

- [ ] Есть события в Redis `analytics:events`
- [ ] Если включён внешний sink — события уходят на `ANALYTICS_EXPORT_URL`
- [ ] Проверен канал Yandex-alert (`alert:yandex_token_refresh_fail` + Telegram push)

## 5) Rollback (если критика)

- [ ] Остановить новый deployment
- [ ] Вернуть предыдущий стабильный image/commit
- [ ] При необходимости восстановить backup

```bash
psql "$DATABASE_URL" < backup_pre_deploy_YYYYMMDD_HHMMSS.sql
```