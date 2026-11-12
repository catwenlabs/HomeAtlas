API_DIR := apps/api
WEB_DIR := apps/web
PY := $(API_DIR)/.venv/bin/python

DEV_COMPOSE := docker compose -f deploy/docker-compose.yml -f deploy/compose.dev.yaml
ENV_FILE ?= deploy/.env
ENV_EXAMPLE_FILE ?= deploy/.env.example
POSTGRES_DEV_HOST := 127.0.0.1
POSTGRES_DEV_PORT ?= 54321

# Source deploy/.env (fall back to the example) so POSTGRES_PASSWORD matches
# the running postgres container, then point the app at the dev port overlay.
LOAD_ENV = if [ -f "$(ENV_FILE)" ]; then set -a; . "$(ENV_FILE)"; set +a; elif [ -f "$(ENV_EXAMPLE_FILE)" ]; then set -a; . "$(ENV_EXAMPLE_FILE)"; set +a; else echo "missing $(ENV_FILE) and $(ENV_EXAMPLE_FILE)" >&2; exit 1; fi
DEV_DB_ENV = POSTGRES_HOST=$(POSTGRES_DEV_HOST) POSTGRES_PORT=$(POSTGRES_DEV_PORT)

.PHONY: api-install test lint fmt typecheck web-build \
	dev dev-db-up dev-db-down dev-db-logs dev-migrate dev-api dev-web-install dev-web \
	compose-config

api-install: ## Create apps/api/.venv and install dev dependencies (uv preferred)
	@if [ -x "$(PY)" ]; then echo "venv ready: $(PY)"; exit 0; fi; \
	cd $(API_DIR); \
	if command -v uv >/dev/null 2>&1; then \
		uv venv --python 3.12 .venv && uv pip install -p .venv/bin/python -e ".[dev]"; \
	else \
		python3 -m venv .venv && .venv/bin/pip install --upgrade pip && .venv/bin/pip install -e ".[dev]"; \
	fi

test: dev-db-up api-install ## Run the API test suite against the dev postgres
	@set -eu; \
	$(LOAD_ENV); \
	cd $(API_DIR); \
	env $(DEV_DB_ENV) .venv/bin/pytest

lint: ## ruff check + format check
	cd $(API_DIR) && .venv/bin/ruff check . && .venv/bin/ruff format --check .

fmt: ## ruff autofix + format
	cd $(API_DIR) && .venv/bin/ruff check --fix . && .venv/bin/ruff format .

typecheck: api-install ## mypy strict
	cd $(API_DIR) && .venv/bin/mypy app

web-build: ## tsc --noEmit + vite build
	cd $(WEB_DIR) && npm run build

dev: ## Full local dev environment (postgres + api + web)
	sh scripts/dev.sh

dev-db-up: ## Start postgres with the dev port overlay (127.0.0.1:54321)
	$(DEV_COMPOSE) up -d --wait postgres

dev-db-down: ## Stop and remove the dev postgres container (volume is kept)
	$(DEV_COMPOSE) rm -sf postgres

dev-db-logs: ## Tail postgres logs
	$(DEV_COMPOSE) logs -f --tail=200 postgres

dev-migrate: api-install dev-db-up ## Apply alembic migrations to the dev database
	@set -eu; \
	$(LOAD_ENV); \
	cd $(API_DIR); \
	env $(DEV_DB_ENV) .venv/bin/python -m alembic upgrade head

dev-api: api-install dev-db-up ## Run uvicorn with reload against the dev postgres
	@set -eu; \
	$(LOAD_ENV); \
	cd $(API_DIR); \
	env $(DEV_DB_ENV) .venv/bin/python -m alembic upgrade head; \
	env $(DEV_DB_ENV) .venv/bin/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

dev-web-install:
	cd $(WEB_DIR) && npm install

dev-web:
	cd $(WEB_DIR) && npm run dev

compose-config: ## Validate the merged compose files
	$(DEV_COMPOSE) config --quiet
