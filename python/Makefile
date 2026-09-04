.PHONY: install dev server consumer test format lint

install:
	uv sync

dev:
	uv run uvicorn app.main:app --host 0.0.0.0 --port $${APP_PORT:-8000}
# Note: --reload omitted; on Windows the multiprocessing reloader spawns
# subprocesses that don't inherit the uv venv, causing ModuleNotFoundError.
# If you need reload, run: .venv/Scripts/python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Kafka 消费者已内嵌于 FastAPI lifespan（app.main），随 `dev` 一起启动，
# 不再需要独立的 consumer 脚本入口。

test:
	uv run pytest

format:
	uv run black .

lint:
	uv run ruff check .
