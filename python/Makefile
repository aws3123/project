.PHONY: install dev server consumer test format lint

install:
	uv sync

dev:
	uv run uvicorn app.main:app --host 0.0.0.0 --port $${APP_PORT:-8000}
# Note: --reload omitted; on Windows the multiprocessing reloader spawns
# subprocesses that don't inherit the uv venv, causing ModuleNotFoundError.
# If you need reload, run: .venv/Scripts/python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

consumer:
	uv run python mq/consumer.py

test:
	uv run pytest

format:
	uv run black .

lint:
	uv run ruff check .
