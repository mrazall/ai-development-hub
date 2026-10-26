FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN addgroup --gid 1000 app && adduser --uid 1000 --gid 1000 --disabled-password --gecos "" app
COPY packages/contracts /app/packages/contracts
COPY services/control-plane /app/services/control-plane
RUN python -m pip install --no-cache-dir /app/packages/contracts /app/services/control-plane
# Attachments and other runtime data live in a named volume mounted at /data (owned by app so the volume inherits it).
RUN install -d -o app -g app -m 700 /data
USER app
WORKDIR /app/services/control-plane
EXPOSE 8000
CMD ["uvicorn", "aihub_control.main:app", "--host", "0.0.0.0", "--port", "8000"]
