FROM python:3.11-slim

RUN useradd -m -u 1000 appuser

WORKDIR /app

# Install deps first so this layer is cached when only app code changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# postgresql-client provides pg_dump for scripts/backup.py
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client \
 && rm -rf /var/lib/apt/lists/*

# App code
COPY app/ ./app/
COPY static/ ./static/
COPY templates/ ./templates/
COPY scripts/ ./scripts/
COPY migrations/ ./migrations/
COPY alembic.ini .

# Generate placeholder PWA icons if not present

RUN mkdir -p /app/data && chown appuser:appuser /app/data

USER appuser

EXPOSE 5000

# The scheduler runs in the separate `worker` service, so the web tier is free
# to scale. Jobs also take a Postgres advisory lock, so even two schedulers
# cannot run the pipeline concurrently.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "120", "app:create_app()"]
