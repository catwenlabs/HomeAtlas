FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

# Install dependencies first for better layer caching (stub package, overwritten below)
COPY pyproject.toml ./
RUN mkdir -p app tests && touch app/__init__.py tests/__init__.py \
    && pip install --no-cache-dir ".[dev]"

COPY app ./app
COPY tests ./tests
COPY alembic ./alembic
COPY alembic.ini ./

RUN useradd --create-home appuser && chown -R appuser:appuser /srv
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
