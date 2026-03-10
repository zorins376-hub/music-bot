.PHONY: up down build logs restart shell status \
        redis-cli db-shell db-backup \
        update-ytdlp clean-downloads \
	setup session help \
	prod-db-smoke prod-db-assert \
	prod-db-backup-and-assert \
	prod-db-verify-all \
	prod-verify-report \
	prod-verify-report-no-backup \
	prod-verify-report-dry-run \
	prod-verify-report-rotate \
	cleanup-reports cleanup-reports-dry-run \
	scripts-smoke \
	prod-new-report \
        parser-up streamer-up

KEEP ?= 20

# ── Основные команды ──────────────────────────────────────────────────────

up:              ## Запустить бота (сборка + старт)
	docker compose up -d --build

down:            ## Остановить всё
	docker compose down

restart:         ## Перезапустить только бота
	docker compose restart bot

build:           ## Пересобрать образ бота без кэша
	docker compose build --no-cache bot

logs:            ## Логи бота в реальном времени
	docker compose logs -f bot

logs-all:        ## Логи всех сервисов
	docker compose logs -f

status:          ## Статус контейнеров
	docker compose ps

# ── Разработка ────────────────────────────────────────────────────────────

shell:           ## bash внутри контейнера бота
	docker compose exec bot bash

redis-cli:       ## Открыть redis-cli
	docker compose exec redis redis-cli

db-shell:        ## Открыть psql (PostgreSQL)
	docker compose exec postgres psql -U $${POSTGRES_USER:-musicbot} $${POSTGRES_DB:-musicbot}

db-backup:       ## Бэкап базы данных в папку backups/
	@mkdir -p backups
	docker compose exec postgres pg_dump -U $${POSTGRES_USER:-musicbot} $${POSTGRES_DB:-musicbot} \
		> backups/backup_$$(date +%Y%m%d_%H%M%S).sql
	@echo "Бэкап сохранён в backups/"

prod-db-smoke:   ## Smoke-проверка production DB (нужен DATABASE_URL + psql)
	psql "$$DATABASE_URL" -v ON_ERROR_STOP=1 -f docs/PROD_DB_SMOKE.sql

prod-db-assert:  ## Fail-fast проверка production DB (нужен DATABASE_URL + psql)
	psql "$$DATABASE_URL" -v ON_ERROR_STOP=1 -f docs/PROD_DB_ASSERT.sql

prod-db-backup-and-assert: ## Backup + fail-fast проверка production DB (нужны DATABASE_URL + psql + pg_dump)
	@mkdir -p backups
	pg_dump "$$DATABASE_URL" > backups/prod_pre_assert_$$(date +%Y%m%d_%H%M%S).sql
	psql "$$DATABASE_URL" -v ON_ERROR_STOP=1 -f docs/PROD_DB_ASSERT.sql

prod-db-verify-all: ## Full pre-deploy DB verification (backup + assert + smoke)
	$(MAKE) prod-db-backup-and-assert
	$(MAKE) prod-db-smoke

prod-verify-report: ## Full verify + timestamped report (PowerShell)
	pwsh -File scripts/prod_verify.ps1 -Commit "$$COMMIT" -Operator "$$OPERATOR"

prod-verify-report-no-backup: ## Verify report without backup step (emergency/fast mode)
	pwsh -File scripts/prod_verify.ps1 -NoBackup -Commit "$$COMMIT" -Operator "$$OPERATOR"

prod-verify-report-dry-run: ## Dry-run verify report (no DB calls)
	pwsh -File scripts/prod_verify.ps1 -DryRun -NoBackup -Commit "$$COMMIT" -Operator "$$OPERATOR"

prod-verify-report-rotate: ## Verify report + rotate old report/log artifacts (KEEP=<n>, default 20)
	pwsh -File scripts/prod_verify.ps1 -RotateArtifacts -KeepArtifacts "$(KEEP)" -Commit "$$COMMIT" -Operator "$$OPERATOR"

cleanup-reports: ## Standalone cleanup for verify reports/logs (KEEP=<n>, default 20)
	pwsh -File scripts/cleanup_reports.ps1 -KeepArtifacts "$(KEEP)"

cleanup-reports-dry-run: ## Preview cleanup without deleting files
	pwsh -File scripts/cleanup_reports.ps1 -KeepArtifacts "$(KEEP)" -DryRun

scripts-smoke: ## Smoke-check PowerShell/CMD launch scripts
	pwsh -File scripts/smoke_scripts.ps1

prod-new-report: ## Create timestamped production execution report skeleton
	pwsh -File scripts/new_prod_report.ps1 -Commit "$$COMMIT" -Operator "$$OPERATOR"

# ── v1.1: Парсер + Стример ────────────────────────────────────────────────

parser-up:       ## Запустить парсер каналов (v1.1, нужен PYROGRAM_SESSION_STRING)
	docker compose up -d --build parser

streamer-up:     ## Запустить Voice Chat стример (v1.1, нужен PYROGRAM_SESSION_STRING)
	docker compose up -d --build streamer

session:         ## Сгенерировать PYROGRAM_SESSION_STRING
	docker compose run --rm bot python -m parser.generate_session

# ── Обслуживание ──────────────────────────────────────────────────────────

update-ytdlp:    ## Обновить yt-dlp внутри контейнера
	docker compose exec bot pip install -U yt-dlp

clean-downloads: ## Очистить временную папку downloads
	rm -rf downloads/*

# ── Первый запуск ─────────────────────────────────────────────────────────

setup:           ## Первоначальная настройка (.env.example → .env + папки)
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "Создан .env — вставь BOT_TOKEN и POSTGRES_PASSWORD!"; \
	else \
		echo ".env уже существует"; \
	fi
	@mkdir -p data downloads logs backups sessions

help:            ## Показать эту справку
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'
