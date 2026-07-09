FROM python:3.12-slim

# curl for the container healthcheck; no build toolchain needed (psycopg2-binary is a wheel)
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Runtime modules (the full Supabase-backed console, not the old CSV-only tool).
# Wildcard on purpose: new modules must not need a Dockerfile edit to ship
# (see 2ac0ad6, f13ab3b for the ModuleNotFoundError bugs this caused).
# .dockerignore already excludes test_*.py / tests/.
COPY *.py ./
COPY .streamlit/ ./.streamlit/
# Static CSV snapshots the Duplicados (dedup) screen reads.
COPY catalogos_export/ ./catalogos_export/

# decisions/ (dedup decisions) is written at runtime — mount it as a volume, don't COPY it.
RUN mkdir -p decisions

# NOTE: no secrets are baked in. DATABASE_URL / SUPABASE_URL / SUPABASE_ANON_KEY /
# SUPABASE_SERVICE_ROLE_KEY are injected at runtime (compose env_file or -e). See DEPLOY.md.

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD curl -f http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
