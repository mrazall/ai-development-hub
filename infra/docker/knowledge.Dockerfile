FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN addgroup --gid 1000 app && adduser --uid 1000 --gid 1000 --disabled-password --gecos "" app
COPY packages/contracts /app/packages/contracts
COPY services/knowledge /app/services/knowledge
RUN python -m pip install --no-cache-dir /app/packages/contracts /app/services/knowledge
USER app
WORKDIR /app/services/knowledge
EXPOSE 8000
CMD ["uvicorn", "aihub_knowledge.api:app", "--host", "0.0.0.0", "--port", "8000"]
