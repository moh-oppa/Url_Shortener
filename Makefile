.DEFAULT_GOAL := help
COMPOSE := docker compose

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

up: ## Start the full stack
	$(COMPOSE) up -d --build

down: ## Stop the stack
	$(COMPOSE) down

logs: ## Tail api logs
	$(COMPOSE) logs -f api

deps: ## Start only Postgres + Redis (for running the API on the host)
	$(COMPOSE) up -d postgres redis

test: ## Run the test suite
	cd backend && python -m pytest

lint: ## Lint and format check
	cd backend && ruff check . && ruff format --check .

fmt: ## Autofix lint and format
	cd backend && ruff check --fix . && ruff format .

migrate: ## Apply migrations
	cd backend && alembic upgrade head

revision: ## Create a migration: make revision m="add links table"
	cd backend && alembic revision --autogenerate -m "$(m)"

.PHONY: help up down logs deps test lint fmt migrate revision