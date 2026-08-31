.PHONY: setup dev-backend dev-frontend migrate downgrade test check build compose

setup:
	uv sync
	cd frontend && npm install

dev-backend:
	uv run uvicorn pawteam_api.main:app --app-dir backend/src --reload --port 8000

dev-frontend:
	cd frontend && npm run dev

migrate:
	uv run alembic upgrade head

downgrade:
	uv run alembic downgrade base

test:
	uv run pytest

check:
	uv run ruff check backend
	cd frontend && npm run check

build:
	cd frontend && npm run build

compose:
	docker compose up --build
