# Kin API + worker image. Build context is the repo root.
FROM python:3.12.16-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir uv==0.11.32
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/app ./app
COPY supabase/migrations ./supabase/migrations
ENV MIGRATIONS_DIR=/app/supabase/migrations
RUN useradd --system --uid 10001 kin && chown -R kin /app
USER kin
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-access-log"]
