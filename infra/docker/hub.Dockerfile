# The hub in one image: control plane API + the built web panel (used by the quickstart; production may
# mount its own build over /app/web instead).
FROM node:22.11-slim AS web
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/web ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 AIHUB_WEB_DIR=/app/web
WORKDIR /app
RUN addgroup --gid 1000 app && adduser --uid 1000 --gid 1000 --disabled-password --gecos "" app
COPY packages/contracts /app/packages/contracts
COPY services/control-plane /app/services/control-plane
RUN python -m pip install --no-cache-dir /app/packages/contracts /app/services/control-plane
COPY --from=web /web/dist /app/web
RUN install -d -o app -g app -m 700 /data /shared
USER app
WORKDIR /app/services/control-plane
EXPOSE 8000
CMD ["uvicorn", "aihub_control.main:app", "--host", "0.0.0.0", "--port", "8000"]
