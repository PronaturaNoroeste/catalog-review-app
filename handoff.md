# Handoff — Go-live deployment (Boca del Álamo pilot)

_Last updated: 2026-07-07._ Taking both apps live on the real (historical) Supabase DB and shipping
them. Full plan: `C:\Users\victus\.claude\plans\reactive-swinging-trinket.md`. Runbooks:
`../Planning/supabase/PROD_ROLLOUT.md`, `catalog-review-app/DEPLOY.md`, `capture-app/BUILD.md`.

## Status at a glance
| Phase | State |
|---|---|
| **1 — Prod DB migration** | ✅ **DONE & verified** (2026-07-07) |
| **2 — Console on a VPS (Docker)** | ⏳ Not started — needs a VPS + a DNS A-record |
| **3 — Capture-app APK (EAS)** | 🔶 In progress — `eas-cli` installed, app pointed at prod; **next step is `eas login` (yours)** |

## Console enhancement rounds (post-go-live, shipped since 2026-07-07)
A parallel workstream on the console (all on `main`, tested against **dev** — the console `.env`
points at **prod**, so tests override `DATABASE_URL`/`SUPABASE_*` to dev + use throwaway rows).

- **R1 quick wins** — Usuarios: clear form on create, create técnico inline, change role, reset
  password; Formularios preview shows condition **values by name** not UUIDs; Descargar "todos los
  campos".
- **R2 export join builder** — "🔧 Constructor" mode in Descargar: pick a base entity, add catalog
  columns + child records (Resumen count/sum, or Detalle) via schema FK-discovery. Files:
  `export_builder.py`, `export_data.py:render_results`.
- **R2.1 export polish** — catalog FK ids resolve to **names by default** (toggle "Mostrar ids");
  **choose + rename columns** (both modes, `export_data._column_editor`); **save custom queries per
  user** (private + "compartir") via `export_saved.py` + migration **`0014_consulta_export`**.

✅ **`0014_consulta_export` applied to prod** (2026-07-07 via `scripts/apply.py`; verified: table +
unique(usuario_id,nombre) + 2 RLS policies, `_migrations`=14). Saved queries now work on the live
console. `usuario`-scoped saved queries need `auth_uid` (captured at login in `console_auth.py`).

**Roadmap remaining:** post-pilot backlog (R-A…R-F, details at the end of this file) · R5 Excel bulk
import (own deep plan) · R6 automated + on-demand backups. (R3 lists in the Form Builder shipped 2026-07-07: view/edit/attach
curated lists from the field dialog — `lista_editor.py`; CSV bulk stays in 📑 Listas. Add-to-list
search shows the matches as clickable buttons — one click adds; verified in a live dev browser.)
(R4 per-user form assignment shipped 2026-07-07: `usuario.formato_origen_id` + console assign UI in
👤 Usuarios; the tablet loads the técnico's assigned form and blocks if unassigned — `lista_editor`
untouched, changes in `users_admin.py` + capture-app `App.tsx`/`supabaseClient.ts`. ✅ Migration
`0015_usuario_formato` **is applied to PROD** — verified 2026-07-08: `_migrations`=15, column +
`idx_usuario_formato` present, all 3 técnicos backfilled to `BOCA_ALAMO_V2`.)

## The three repos (all on GitHub, `main`)
- `catalog-review-app` — Streamlit **admin console** → `PronaturaNoroeste/catalog-review-app`
- `capture-app` — Expo/RN **tablet app** → `PronaturaNoroeste/capture-app`
- `Planning/supabase` — SQL migrations + scripts → `PronaturaNoroeste/supabase-backend`
  (`DBScheme` is a separate repo; `Planning` root is NOT a repo.)

## Key facts (projects, secrets, accounts)
- **Supabase projects:** PROD ref `boeysdpistpvdvcwzddm` (`aws-1-us-west-1`); DEV ref
  `pxxqumcvkoltbjubyvod` (`aws-1-us-east-1`). Prod URL: `https://boeysdpistpvdvcwzddm.supabase.co`.
- **New WSL checkout (2026-07-07):** repos now also live at `~/bitacora/` (`catalog-review-app`,
  `capture-app`, `supabase-backend`) on Linux/WSL2. The console secrets arrived there as `env`
  (no dot — not loaded, not gitignored); renamed to `.env`. `supabase-backend` has no `.env` on this
  machine — the prod DSN lives in `catalog-review-app/.env` (`DATABASE_URL`).
- **Secrets live in gitignored `.env` files (never commit / never print):**
  - `Planning/supabase/.env` → `DATABASE_URL` (**dev** DSN) + `PROD_DATABASE_URL` (**prod** DSN).
  - `catalog-review-app/.env` → now **all prod** (`DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`,
    `SUPABASE_SERVICE_ROLE_KEY`). Service-role key = server-side only.
  - `capture-app/.env` → now **prod** (`EXPO_PUBLIC_SUPABASE_URL` / `_ANON_KEY`).
- **Prod accounts (created via the console):** 6 total — 4 ADMINISTRADOR, **2 TECNICO** (`Test_07072026`,
  `Test`, both linked to a `cat_tecnico`). Use a TECNICO to test the tablet.
- **Prod backup:** `D:\Victus\Documents\Servicio\backups\prod_public_20260707.dump` (33 MB, `pg_dump -Fc`
  of `public`; restore with `pg_restore`). Pre-migration state = rollback point.
- **Local tools found/installed:** `pg_dump`/`pg_restore` at `C:\Program Files\PostgreSQL\18\bin`;
  `eas-cli 20.5.1` (global); `supabase` CLI 2.101 (needs Docker for `db dump` — Docker daemon was down).

## Targeting prod when running the Planning scripts
`.env` `DATABASE_URL` is **dev**, so override it from the environment (all scripts now honor env-first):
```bash
ENVF="D:/Victus/Documents/Servicio/Planning/supabase/.env"
PRODDSN="$(python -c "print(next(l.split('=',1)[1].strip().strip(chr(34)).strip(chr(39)) for l in open(r'$ENVF',encoding='utf-8') if l.strip().startswith('PROD_DATABASE_URL=')))")"
DATABASE_URL="$PRODDSN" python scripts/<script>.py
```
`copy_lista_opcion.py` needs both `SRC_DATABASE_URL` (dev) + `DATABASE_URL` (prod). Windows: set
`PYTHONIOENCODING=utf-8`. Redact any DSN from output.

---

## Phase 1 — Prod DB migration ✅ DONE
Ran against prod, in order (see `PROD_ROLLOUT.md`): full `pg_dump` backup → `catalog_approvals.sql`
(approve used-in-history) → `prod_prepare.py --record-baseline` → `apply.py` (0002–0013) →
`catalog_consolidations.sql` + `catalog_additions.sql` → `copy_lista_opcion.py` (dev→prod) → built a
data-driven `pescadores` list from Boca del Álamo history → `seed_form.py … v8`. Then verified the
console (all modes) + an authenticated **RLS smoke** (técnico reads catalogs/form/lists; anon blocked).

**Verified end state (prod):** 13 migrations; 3,813 catalogs approved (`estado='aprobado'`); curated
lists **especies 131 / carnada 24 / pescadores 5**; **v8 published** for `BOCA_ALAMO_V2`; 32 RLS
policies; **377,179 mediciones intact**; `crear_faena_completa` present; email/password auth works.

Remaining (first-run, not blocking): accounts were created (done). Optionally refine the curated lists
via console 📑 Listas (e.g. the pescadores list includes historical "Desconocido").

---

## Phase 2 — Console on a VPS (Docker) ⏳ TODO
Artifacts are committed in `catalog-review-app` (`Dockerfile`, `docker-compose.yml`, `Caddyfile`,
`.dockerignore`, `.env.example`, `DEPLOY.md`). `docker compose config` validated; image not built here
(Docker daemon was down — it builds on the VPS).

**You need:** a VPS with Docker + Docker Compose, and a DNS **A-record** (e.g.
`consola.tu-dominio.org` → VPS IP).

**Steps (from `DEPLOY.md`):**
1. Copy the repo to the VPS; put the **prod** secrets in `catalog-review-app/.env` (same 4 values as the
   local console `.env`).
2. `CONSOLE_DOMAIN=consola.tu-dominio.org docker compose up -d --build` — Caddy auto-provisions TLS
   (needs ports 80/443 open + DNS live).
3. Open `https://…`, log in as an ADMINISTRADOR, confirm all modes render, run a small export.
4. `decisions/` is a named volume (persists dedup decisions across restarts). Update = `git pull &&
   docker compose up -d --build`.

**Notes:** the console has its own login gate and is **open until the first admin exists** — prod already
has admins, so it won't be open. Optional extra hardening: Caddy `basic_auth` (commented in `Caddyfile`).

---

## Phase 3 — Capture-app APK (EAS) 🔶 IN PROGRESS
`capture-app/eas.json` (preview + production APK profiles), `app.json` (v1.0.0, versionCode 1), and
`BUILD.md` are committed; the dev "Descartar" button is gated behind `__DEV__`. `capture-app/.env` now
points at prod. `eas-cli 20.5.1` is installed.

**You need:** a (free) Expo account.

**Steps (from `BUILD.md`):**
1. **`eas login`** ← next action, must be interactive in a real terminal.
2. `eas init` (creates/links the Expo project, writes `projectId` into `app.json`) — can be run after login.
3. Set prod build env vars:
   ```
   eas env:create --environment production --name EXPO_PUBLIC_SUPABASE_URL  --value https://boeysdpistpvdvcwzddm.supabase.co
   eas env:create --environment production --name EXPO_PUBLIC_SUPABASE_ANON_KEY --value <prod anon key from catalog-review-app/.env>
   ```
4. `cd capture-app && eas build --platform android --profile production` (prompts once to auto-generate
   an Android keystore → interactive). Produces a sideloadable **APK** URL (~10–20 min, GMS-free — no
   Play Store).
5. **Day-0 device smoke** (Huawei tablet, per `DEVICE_TESTING.md`): log in as `Test_07072026`, load the v8
   form, capture a faena **offline**, GPS/map, then **Sincronizar** → the faena appears in the console/DB;
   verify kg→gr routing.

**Dev testing before the APK:** `cd capture-app && npx expo start -c` — the `-c` is required because
`EXPO_PUBLIC_*` are inlined at bundle time (a plain reload keeps stale values). This is what fixed the
"invalid credentials" issue (app was bundling the old dev project).

---

## Gotchas discovered during go-live (so they don't bite again)
- **App/project mismatch = "invalid credentials".** The capture app bundled the **dev** project while
  accounts were created in **prod**. Fix: point `capture-app/.env` at prod + `expo start -c`.
- **`EXPO_PUBLIC_*` are bundle-time constants** — always `-c` (clear cache) or rebuild after changing them.
- **`seed_form.py` read the DSN only from `.env`** (ignored the env override) → silently hit dev. Fixed to
  prefer `os.environ` (committed). `apply.py`/`prod_prepare.py`/`copy_*` already were env-first.
- **Historical catalogs import unapproved** (`es_aprobado=false`) and the capture app mirrors only approved
  rows → every picker would be empty. `prod/catalog_approvals.sql` (approve used-in-history) must run
  **before** `0003` so its backfill lands `estado='aprobado'`.
- **Curated `lista_opcion` ids diverge dev↔prod.** Dev's pescadores list was 100% dev-test ids (all
  skipped); some especies/carnada too. `copy_lista_opcion.py` is FK-safe (skips + reports); prod pescadores
  was rebuilt from Boca del Álamo faena history instead.
- **Baseline `0001` is not idempotent** — it must be pre-recorded in `_migrations`
  (`prod_prepare.py --record-baseline`) so `apply.py` starts at `0002`.
- **Free-tier Supabase has no dashboard backups** and allows only 2 projects/org (so no scratch clone). We
  used a local `pg_dump` (PostgreSQL 18 bin) instead; `supabase db dump` needs Docker.
- **Auth model changed:** email+password (admin-created), NOT anonymous — the "anonymous sign-ins" toggle
  is obsolete. Memory `m2-auth-model` was corrected.

## Definition of done
Console reachable over HTTPS on the VPS (admins log in, all modes work); a signed prod APK sideloaded on a
Huawei tablet where a técnico logs in, captures offline, and syncs a faena that appears in the console —
kg→gr correct. Watch prod DB size vs the 500 MB free-tier ceiling (currently 226 MB); move to Pro only if
approached.

## Prod test-data hygiene (2026-07-08)
Prod device tests must be captured under the **`Test` / `Test_07072026`** logins, which are now
linked to a dedicated `cat_tecnico` **"PRUEBAS — no usar en campo"**
(`95ab1dd0-0661-4961-b7bc-ff0a1b640875`) — so test faenas are separable from real data. (Before this,
those logins were wired to real técnicos — `Test_07072026`→MBOV with 748 real faenas — so purging by
them would have deleted history.) Cleanup tool: `Planning/supabase/scripts/purge_test_faenas.py`
(preview-by-default, prod-guarded, never prints the DSN, `--max` guard). Purge test data with
`--tecnico-id 95ab1dd0-…`; delete a single faena with `--faena-id <uuid>`. See `capture-app/DEVICE_TESTING.md`.
The first APK test faena (`8d61a9c6`, técnico "Miguel Angel Alvarez Hernandez") was deleted 2026-07-08.

Same purge is also in the **console**: ADMINISTRADOR → sidebar **DATOS → 🧹 Datos de prueba**
(`maintenance.py`) — preview + two-step-confirm delete of the PRUEBAS técnico's faenas, plus
delete-one-by-id. It targets only the test técnico (resolved by name), so it can't touch real data;
it acts on whatever DB the console points at (prod).

## Post-pilot backlog (planned 2026-07-08)
Requested improvements; decisions already made with the user. Full design in the session plan file.
Suggested order: R-A, R-B (quick) → R-C, R-D, R-E → R-F (own deep plan). Each ships with an AppTest
smoke / dev-DSN round-trip test; tablet items need `tsc` + a device check and a new APK.

**Status (2026-07-08): R-A…R-F implemented + pushed.** Admin set-password tool removed (self-service
replaces it). Open follow-ups:
- **R-E:** enable the code token `{{ .Token }}` in the Supabase "Reset Password" email template
  (done on prod; template saved at `docs/reset-password-email-template.html`).
- **R-F:** migration `0016_version_decimal` applied to **DEV + PROD** (2026-07-08). Prod renumbered
  v8→0.8 (publicado) and v9→0.9 (borrador); both columns NUMERIC; faenas all NULL (untouched). The
  decimal-version console is now safe against prod.
- **Tablet APK v1.0.2 / versionCode 3** (offline-login + password reset + decimal version) is built
  when you say go.

- **R-A · Clearer login messages** (`console_auth.py`) — split branches so a user knows their password
  was right: valid-but-not-a-console-role → "correo y contraseña correctos, pero esta cuenta (rol X)
  no tiene acceso…"; deactivated → distinct message; bad creds → "correo o contraseña incorrectos".
- **R-B · Show only current formatos** — assignment (`users_admin._formatos`) offers only formatos
  with a **published** form (`EXISTS … formulario … estado='publicado'`); creation
  (`form_builder.py`) keeps the in-use default (`formatos_en_uso`) and **drops** the "Mostrar formatos
  históricos" toggle so legacy/`*_LEGACY`/`DEPRECADO` don't show.
- **R-C · Analista region lock** — load `region_id` at login (`_rol_of` + `auth_region` session key);
  in `export_data.render_export`, for ANALISTA force the region to their own (locked caption, no
  multiselect) and **hide the 🔧 Constructor**; `set_rol` must preserve/set `region_id`. Region lives
  only on `faena`. Files: `console_auth.py`, `export_data.py`, `users_admin.py`.
- **R-D · Constructor value filters** — add per-base catalog-FK filters (comunidad, región,
  cooperativa…) to `export_builder.render_builder` via `catalog_parents(base)`; `build_query` returns
  `(sql, params)` and emits `WHERE b."fk" = ANY(%s::uuid[])`; persist in the saved-query config.
- **R-E · Self-service password reset (console + tablet)** — Supabase **recovery OTP code** (a reset
  *link* can't complete in Streamlit). Prereq: enable the code token `{{ .Token }}` in the Supabase
  "Reset Password" email template. Console: `/auth/v1/recover` → `/auth/v1/verify` (type=recovery) →
  `PUT /auth/v1/user`. Tablet: `resetPasswordForEmail` → `verifyOtp` → `updateUser`.
- **R-F · Decimal form versions (own deep plan)** — versions become `NUMERIC` and **admin-entered**;
  migration `0016` converts `formulario.version` + `faena.formulario_version` INT→NUMERIC and
  **renumbers /10** (v8→0.8; app-captured faenas updated, legacy NULL untouched). Console: admin
  version input replaces auto-increment. Tablet: `formulario_cache.version` → REAL; new APK. Cross-repo
  + touches captured prod data — give it its own spec before building.
