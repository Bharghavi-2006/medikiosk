# MediKiosk interview engine — production-ish container.
# Build:  docker build -t medikiosk .
# Run:    docker run --rm -p 8000:8000 --env-file .env medikiosk
# (or just: docker compose up -d)

FROM python:3.12-slim

# Non-root user
RUN useradd --create-home --uid 1000 kiosk

WORKDIR /app

# Dependencies first (better layer caching)
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# App + kiosk UI
COPY backend/app ./app
COPY frontend/index.html ./frontend/index.html
RUN chown -R kiosk:kiosk /app

ENV FRONTEND_PATH=/app/frontend/index.html \
    PYTHONUNBUFFERED=1

USER kiosk
EXPOSE 8000

# Single worker: interview state is per-WebSocket; scale with more
# replicas behind the proxy, not more workers in one process.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--no-server-header"]
