FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./
COPY backend ./backend

RUN uv sync --frozen --no-dev

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn pawteam_api.main:app --app-dir backend/src --host 0.0.0.0 --port 8000"]
