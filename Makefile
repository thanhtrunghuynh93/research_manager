.PHONY: help dev down web test lint typecheck migrate migrate-check migration bootstrap seed e2e check-traceability check-docs

COMPOSE := docker compose -f infra/docker-compose.yml -f infra/docker-compose.dev.yml --env-file infra/.env

help:
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

dev: ## start the dev stack (postgres, minio, mailpit, api, worker)
	$(COMPOSE) up -d --build
	$(COMPOSE) exec api uv run alembic upgrade head

down: ## stop the dev stack
	$(COMPOSE) down

web: ## run the frontend dev server
	cd frontend && npm run dev

test: ## run backend tests
	cd backend && uv run pytest

lint: ## lint backend and frontend
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run lint-imports
	cd frontend && npm run lint

typecheck: ## type-check backend and frontend
	cd backend && uv run mypy app
	cd frontend && npm run typecheck

migrate: ## apply migrations to the dev database
	cd backend && uv run alembic upgrade head

migrate-check: ## fail if models and migrations differ
	cd backend && uv run alembic check

migration: ## create a migration: make migration m="add users"
	cd backend && uv run alembic revision --autogenerate -m "$(m)"

bootstrap: ## create the workspace and professor (first run only): make bootstrap name="Lab" email=... who="Prof X"
	$(COMPOSE) exec api uv run python -m app.cli identity bootstrap \
		--name "$(or $(name),Research Lab)" \
		--email "$(or $(email),prof@example.edu)" \
		--display-name "$(or $(who),Professor)"

seed: ## load the demo dataset
	cd backend && uv run python -m app.cli seed demo

e2e: ## run Playwright end-to-end tests against the dev stack
	cd frontend && npm run e2e

check-traceability: ## verify every requirement ID is covered in architecture and tests
	python3 scripts/check_traceability.py

check-docs: ## verify the docs against the tree: paths, cited API routes, counts, versions
	python3 scripts/check_docs.py
