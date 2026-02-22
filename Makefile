.PHONY: up down build logs restart shell status \
        redis-cli db-shell db-backup \
        update-ytdlp clean-downloads \
        setup session help \
        parser-up streamer-up

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
