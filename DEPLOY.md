# Deploying the console (Docker on a VPS)

The admin console is a Streamlit app. It talks to the **prod** Supabase DB directly
(psycopg2) for the catalog/form/lista tooling and uses the Supabase Auth admin API to
create users. It is fronted by Caddy for automatic HTTPS.

## Prerequisites
- A VPS with Docker + Docker Compose.
- A DNS **A record** for your console hostname (e.g. `consola.tu-dominio.org`) → the VPS IP.
- The prod Supabase project stood up per `../Planning/supabase/PROD_ROLLOUT.md`.

## Secrets
`console_config.py` reads env first, then `.env`. Copy and fill:

```bash
cp .env.example .env      # gitignored — never commit
```

Required: `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`.
The **service-role key is a secret** — it stays only in this server's env. It is never
baked into the image (the Dockerfile COPYs named source files only; `.dockerignore` excludes
`.env`).

## Run

```bash
CONSOLE_DOMAIN=consola.tu-dominio.org docker compose up -d --build
docker compose logs -f console      # watch startup / health
```

Caddy provisions a Let's Encrypt cert on first boot (needs ports 80+443 open and DNS
pointing at the box). Then open `https://consola.tu-dominio.org`.

**Local smoke (no TLS):** uncomment the `console` `ports:` mapping in `docker-compose.yml`,
`docker compose up --build console`, and hit `http://localhost:8501`.

## Access control
The app has its own login gate (`console_auth`), and the console is **open until the first
ADMINISTRADOR exists** (bootstrap). So on a fresh prod DB, the very first visitor can create
the first admin — either create that admin quickly, or keep the site private (Caddy
`basic_auth`, commented in `Caddyfile`) until it's done. Use strong admin passwords.

## Persistence & updates
- `decisions/` (dedup decisions) is a named volume — survives restarts/rebuilds.
- Update: `git pull && docker compose up -d --build`.

## Verify
- `https://…` loads with a valid cert; log in as admin.
- Every mode renders (Duplicados, Catálogos, Propuestas, Formularios, Listas, Usuarios,
  Descargar datos). Create a TECNICO. Export a small dataset.
- Restart the stack and confirm `decisions/` persisted.
