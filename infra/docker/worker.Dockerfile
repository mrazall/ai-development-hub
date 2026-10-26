# A worker in a container. As shipped it runs only the built-in mock engines (demo, tests); real engines
# (Claude Code, Codex) run on a machine where their CLIs are installed and logged in — see docs/workers.md.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends git >/dev/null && rm -rf /var/lib/apt/lists/*
WORKDIR /app
RUN addgroup --gid 1000 app && adduser --uid 1000 --gid 1000 --disabled-password --gecos "" app
COPY packages/contracts /app/packages/contracts
COPY packages/agent-adapters /app/packages/agent-adapters
COPY packages/mcp-knowledge /app/packages/mcp-knowledge
RUN python -m pip install --no-cache-dir /app/packages/contracts /app/packages/agent-adapters /app/packages/mcp-knowledge
RUN install -d -o app -g app /work /shared
USER app
RUN git config --global user.name "AI Hub demo" && git config --global user.email demo@aihub.local
ENV AIHUB_HUB=http://control-plane:8000 AIHUB_WORKER_ID=demo-worker AIHUB_TOKEN_FILE=/shared/worker-token
# Wait for the hub's demo seed to hand over the token, then run (real engines disabled).
CMD ["sh", "-c", "mkdir -p /work/demo && until [ -s \"$AIHUB_TOKEN_FILE\" ]; do sleep 2; done; exec aihub-worker --control-plane \"$AIHUB_HUB\" --worker-id \"$AIHUB_WORKER_ID\" --token-file \"$AIHUB_TOKEN_FILE\""]
