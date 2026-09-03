# Minimal development container for the Phase 0 foundation.
# NOT production infrastructure. No trading, no exchange, no external services.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir -e ".[dev]" || pip install --no-cache-dir -r requirements.txt

COPY . .

# Default: run the offline bootstrap (safe on an offline machine).
CMD ["python", "-m", "app.main"]
