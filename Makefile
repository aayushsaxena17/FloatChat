.PHONY: dev stop restart build setup test integration bench lint typecheck eval eval-nl eval-forecast seed-corpus secrets-current secrets-history
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
eval: eval-nl eval-forecast
eval-nl:
	uv run --all-packages --frozen python -m eval.nl.harness --split test --ablations all
eval-forecast:
	uv run --all-packages --frozen python -m eval.forecast.harness
seed-corpus:
	python3 -m scripts.dev seed-corpus
secrets-current:
	python3 scripts/security/scan.py current
secrets-history:
	python3 scripts/security/scan.py history
