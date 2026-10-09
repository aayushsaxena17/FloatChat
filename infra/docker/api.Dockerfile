FROM library/python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c AS runtime
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 PATH="/app/.venv/bin:$PATH"
WORKDIR /app
RUN pip install --no-cache-dir uv==0.10.4
COPY pyproject.toml uv.lock .python-version ./
COPY apps/api apps/api
COPY packages/core packages/core
COPY workers workers
RUN uv sync --all-packages --frozen --no-dev
COPY infra/alembic.ini infra/alembic.ini
COPY infra/migrations infra/migrations
COPY scripts/bootstrap_db.py scripts/bootstrap_db.py
COPY scripts/integration_probe.py scripts/integration_probe.py
RUN useradd --uid 10001 --create-home floatchat \
    && mkdir -p /var/lib/floatchat/query-cache && chown 10001 /var/lib/floatchat/query-cache
USER 10001
EXPOSE 8000
CMD ["uvicorn", "floatchat_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
