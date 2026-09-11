# Everything a reader needs to run this repository. `make help` lists it.
#
# `live-classify` is deliberately absent: it is the one command that can reach a paid API, it is
# gated on two explicit environment opt-ins, and putting it behind a target would make it one
# tab-completion away from a run nobody meant to pay for.

SHELL := /bin/sh
DSN := postgresql://mad:mad_local_dev@localhost:15433/mad

.PHONY: help install fmt lint types test gate db-up db-down migrate migrate-down demo killtest api clean

help: ## List the targets
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-14s %s\n", $$1, $$2}'

install: ## Install exactly what uv.lock pins
	uv sync --frozen

fmt: ## Format
	uv run ruff format .

lint: ## Lint and formatting gate
	uv run ruff format --check .
	uv run ruff check .

types: ## Strict type check
	uv run mypy

test: ## The offline suite. Needs no database and no credential.
	uv run pytest

db-up: ## Start PostgreSQL
	docker compose up -d
	@echo "waiting for postgres..." && sleep 3

db-down: ## Stop PostgreSQL, keeping the volume
	docker compose down

migrate: db-up ## Apply migrations to head
	MAD_POSTGRES_DSN=$(DSN) uv run alembic upgrade head

migrate-down: ## Roll back to base, to prove the migration is reversible
	MAD_POSTGRES_DSN=$(DSN) uv run alembic downgrade base

demo: migrate ## Reset and seed the local database with the demonstration data
	MAD_POSTGRES_DSN=$(DSN) uv run python -m market_approach_desk.demo

api: ## Serve the API against the seeded database, flagged in the console as demo data
	MAD_POSTGRES_DSN=$(DSN) MAD_DEMO_MODE=true \
	  uv run uvicorn "market_approach_desk.api:create_app" --factory --port 8000

killtest: migrate ## THE COMPARISON: both arms, one harness, one carrier
	MAD_POSTGRES_DSN=$(DSN) uv run pytest tests/test_kill_test_postgres.py -m integration -q --no-cov

gate: ## The full local gate, in the order CI runs it
	uv sync --frozen
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy
	uv run pytest
	$(MAKE) killtest

clean: ## Remove caches
	rm -rf .pytest_cache .mypy_cache .ruff_cache
