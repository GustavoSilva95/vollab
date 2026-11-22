# Engine do VolLab: a mesma imagem roda a API, o worker e as migrations (docker-compose.yml).
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /usr/local/bin/uv

WORKDIR /app

# Dependências primeiro (camada em cache enquanto o uv.lock não muda).
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY alembic.ini ./
COPY src ./src
RUN uv sync --locked --no-dev

# Git sha do build, gravado no retrato da decisão (PRD §5.4).
ARG ENGINE_VERSION=dev
ENV ENGINE_VERSION=${ENGINE_VERSION}

RUN useradd --create-home --uid 10001 vollab && mkdir -p /app/data/raw && chown -R vollab /app/data
USER vollab

EXPOSE 8000
CMD ["python", "-m", "vollab.api"]
