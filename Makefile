.PHONY: dev stop restart build setup test integration bench lint typecheck eval secrets-current secrets-history
dev:
	python3 -m scripts.dev dev
stop:
	python3 -m scripts.dev stop
restart:
	python3 -m scripts.dev restart
build:
	python3 -m scripts.dev build
setup:
	uv sync --all-packages --frozen
	pnpm install --frozen-lockfile
	uv run --all-packages --frozen pre-commit install
test:
	uv run --all-packages --frozen python -m pytest -m 'not integration'
	pnpm test
integration:
	uv run --all-packages --frozen python -m scripts.integration
bench:
	STAGE1_BENCH=1 uv run --all-packages --frozen python -m pytest tests/stage1/test_chunk_scale.py -q -s
lint:
	uv run --all-packages --frozen ruff check .
	uv run --all-packages --frozen ruff format --check .
	pnpm lint
	pnpm format:check
typecheck:
	uv run --all-packages --frozen mypy
	pnpm typecheck
eval:
	@echo "not yet implemented"
secrets-current:
	python3 scripts/security/scan.py current
secrets-history:
	python3 scripts/security/scan.py history
