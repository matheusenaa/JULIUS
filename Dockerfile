# --- 1. Compila o frontend (PWA) ---
FROM node:24-alpine AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npx vite build --outDir /out/static

# --- 2. Backend Python servindo API + frontend ---
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_ENV=production
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=frontend /out/static ./static
RUN useradd --create-home julius && mkdir -p data && chown -R julius /app
USER julius
EXPOSE 8010
# Migrations a cada deploy: idempotentes, nunca apagam dados
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8010} --proxy-headers --forwarded-allow-ips='*'"]
