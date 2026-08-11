# syntax=docker/dockerfile:1
#
# Backend image for the Lemely FastAPI service (MISSION.md §3 "Definition of
# done for deployment"). Multi-stage: a builder stage resolves the `web` +
# `db` extras into a venv, the runtime stage copies only that venv plus the
# package source — no compiler toolchain, no dev/test deps, no .git.
#
# Binds 0.0.0.0 inside the container (lemely/web/__main__.py defaults to
# 127.0.0.1, which is correct for a bare-metal dev run but unreachable from
# outside a container — LEMELY_WEB_HOST=0.0.0.0 below overrides it; see
# docker-compose.yml).

ARG PYTHON_VERSION=3.13-slim

FROM python:${PYTHON_VERSION} AS builder

# Build-time only: compiling psycopg[binary]'s deps and PyMuPDF wheels can
# need a C toolchain on some platforms; keep it out of the runtime stage.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy only the dependency manifest first so `pip install` layers cache
# across source-only changes.
COPY pyproject.toml ./
# hatchling (the build backend) requires the package tree to exist to read
# version/metadata even for a `pip install .`-style resolve, so bring the
# package in before installing. README.md is referenced by [project.readme].
COPY lemely ./lemely
COPY README.md ./

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
# `web` + `db`: the FastAPI server, uvicorn, and the SQLAlchemy/Alembic/psycopg
# stack the containerised backend needs. No `ui` (Gradio, debug-only per
# MISSION §3), no `dev` (pytest/ruff/mypy — test tooling has no place in a
# shipped image).
RUN pip install --no-cache-dir ".[web,db]"

FROM python:${PYTHON_VERSION} AS runtime

# Non-root: a compromised app process should not run as the image's root.
RUN groupadd --system lemely && useradd --system --gid lemely --create-home lemely

WORKDIR /app
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LEMELY_WEB_HOST=0.0.0.0 \
    LEMELY_WEB_PORT=8000

COPY --from=builder /opt/venv /opt/venv
COPY lemely ./lemely
COPY alembic.ini ./
COPY README.md ./
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# `.lemely-cache` is where the Gemini disk cache and the persistent spend
# ledger (BUILD/MISSION.md §8) live; created here so it is owned by the
# non-root user rather than materialising root-owned on first write.
RUN mkdir -p /app/.lemely-cache \
    && chown -R lemely:lemely /app \
    && chmod +x /usr/local/bin/docker-entrypoint.sh

USER lemely

EXPOSE 8000

# No CORS middleware is installed anywhere in this image (see
# docker-compose.yml for the reasoning) — the container only ever needs to
# answer same-origin requests proxied by the web/nginx service or direct
# operator/health-check traffic.
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).status == 200 else 1)"

ENTRYPOINT ["docker-entrypoint.sh"]
