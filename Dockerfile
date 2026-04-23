ARG TARGETPLATFORM=linux/amd64

FROM --platform=$TARGETPLATFORM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./
COPY frontend/scripts ./scripts
RUN npm ci

COPY frontend/ ./
RUN npm run build


FROM --platform=$TARGETPLATFORM python:3.11-slim AS backend-builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
COPY backend/pyproject.toml ./backend/pyproject.toml
COPY backend/src ./backend/src
COPY flights-search/README.md ./flights-search/README.md
COPY flights-search/pyproject.toml ./flights-search/pyproject.toml
COPY flights-search/src ./flights-search/src
RUN pip install --no-cache-dir -r backend/requirements.txt \
    && pip install --no-cache-dir ./flights-search \
    && pip install --no-cache-dir ./backend


FROM --platform=$TARGETPLATFORM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    FLIGHTS_SEARCH_REPO=/app/flights-search \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PLAYWRIGHT_SKIP_BROWSER_GC=1

WORKDIR /app

COPY --from=backend-builder /usr/local /usr/local
COPY backend/src ./backend/src
COPY flights-search/src ./flights-search/src
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

RUN python -m playwright install-deps chromium \
    && python -m playwright install chromium

EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn smartflight.main:app --app-dir /app/backend/src --host 0.0.0.0 --port ${PORT}"]
