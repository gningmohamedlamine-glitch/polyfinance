FROM node:24-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && useradd --system --uid 10001 dashboard
COPY backend/ backend/
COPY agents/ agents/
COPY data/prices_daily.csv data/fx_usdcad_daily.csv data/market_events.csv data/sector_etfs_daily.csv data/assets_universe.csv data/esg_publications.csv data/esg_emissions.csv data/esgv_holdings.cs[v] data/
COPY data/sources/ data/sources/
COPY --from=frontend /build/dist/frontend/browser/ frontend/dist/frontend/browser/
USER dashboard
EXPOSE 8080
CMD ["gunicorn", "--chdir", "backend", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "4", "--timeout", "180", "--access-logfile", "-", "--error-logfile", "-", "--worker-tmp-dir", "/dev/shm", "config.wsgi:application"]
