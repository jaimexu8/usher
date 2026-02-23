FROM python:3.12-slim

WORKDIR /app

# Install build deps for any C extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY coc_bot/ ./coc_bot/

# SQLite DB lives here — mount a volume at this path
RUN mkdir -p /app/data

ENV SQLITE_PATH=/app/data/bot.db \
    LOG_LEVEL=INFO \
    COMMAND_PREFIX=! \
    POLL_INTERVAL=120

CMD ["python", "-m", "coc_bot"]
