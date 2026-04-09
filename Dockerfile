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
RUN pip install --no-cache-dir -r backend/requirements.txt \
    && pip install --no-cache-dir ./backend


FROM --platform=$TARGETPLATFORM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

COPY --from=backend-builder /usr/local /usr/local
COPY backend/src ./backend/src
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn smartflight.main:app --app-dir /app/backend/src --host 0.0.0.0 --port ${PORT}"]
