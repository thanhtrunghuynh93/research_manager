.PHONY: help test lint typecheck check-traceability check-docs

help:
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

test: ## run backend tests
	cd backend && uv run pytest

lint: ## lint backend and frontend
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run lint-imports
	cd frontend && npm run lint

typecheck: ## type-check backend and frontend
	cd backend && uv run mypy app
	cd frontend && npm run typecheck

check-traceability: ## verify every requirement ID is covered in architecture and tests
	python3 scripts/check_traceability.py

check-docs: ## verify the docs against the tree: paths, cited and called API routes, the ADR index
	python3 scripts/check_docs.py
