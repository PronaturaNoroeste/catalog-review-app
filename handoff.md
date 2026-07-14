# Handoff — Go-live deployment (Boca del Álamo pilot)

_Last updated: 2026-07-13._ Taking both apps live on the real (historical) Supabase DB and shipping
them. Full plan: `C:\Users\victus\.claude\plans\reactive-swinging-trinket.md`. Runbooks:
`../Planning/supabase/PROD_ROLLOUT.md`, `catalog-review-app/DEPLOY.md`, `capture-app/BUILD.md`.

## Status at a glance
| Phase | State |
|---|---|
| **1 — Prod DB migration** | ✅ **DONE & verified** (2026-07-07) |
| **2 — Console on a VPS (Docker)** | ✅ **Running** (console-only, no Caddy/TLS yet — see the 2026-07-13 VPS notes below) |
| **3 — Capture-app APK (EAS)** | ✅ **Built** 2026-07-13 — **v1.0.4 / versionCode 5**, from `main` @ `cb3a717` (includes everything below). Device smoke still pending. |

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

**Roadmap remaining:** post-pilot backlog (R-A…R-F, details at the end of this file) · R6 automated +
on-demand backups.

**R5 Excel bulk import — implemented 2026-07-10** (all 8 plan tasks, committed on `main`, tested
against **dev**): new ✏️ **📥 Importar Excel** console mode (`excel_import.py`), admin-only, 4-step
wizard (subir → mapear catálogos → previsualizar → confirmar). New modules `import_formats.py`
(declarative Masivos/Bitácoras specs, parsing, grouping into `FaenaDraft`), `catalog_resolver.py`
(normalize + fuzzy-match via `difflib` + resolve-or-create + especie pair-keyed), `import_writer.py`
(natural-key `legacy_id` dedup + transactional insert with per-faena savepoint + `cambio_catalogo`
audit). `openpyxl` added to `requirements.txt` (wasn't actually already a dep). Full test suite green
(`test_catalog_resolver[_db]`, `test_import_formats_parse/group`, `test_import_writer`,
`test_excel_import[_e2e]`) plus an AppTest boot-smoke.

Executing against the real dev schema surfaced **5 mismatches the plan's design doc got wrong**
(now fixed — see `docs/superpowers/plans/2026-07-10-r5-excel-import.md` top banner for detail):
`desconocido_id` wasn't idempotent (an `is_na()` false-positive on the literal string
"Desconocido"); the `es_aprobado`-bearing catalog set was hardcoded and wrong (`cat_tipo_arte/
anzuelo/fondo/operacion` **do** have it); `cat_area_pesca.zona_pesca_id` is `NOT NULL` with no
mapped source column (now auto-chains to a `Desconocido` `cat_zona_pesca`);
`cat_especie.nombre_cientifico` is `NOT NULL` defaulting to the literal `'Pendiente'`, which real
rows already use as the unknown-científico sentinel (lookup/insert now match that instead of
NULL/empty); `detect_format`'s Jaccard scoring failed on real partial header sets (fixed to score
by containment).

**✅ Verified against the real `Planning/DBScheme/Anexo2.xlsx` (2026-07-12)** — which surfaced two
real defects, both now fixed (commit `20a4c17`):
- **Bitácoras never imported.** The wizard auto-locked onto the first header-matching sheet
  (`produccion masivos`) and only offered a *format* override, so `producción bitácoras` was
  unreachable; the two production sheets also share ~all headers and tie on containment (0.38, below
  threshold) so detection couldn't tell them apart. Fix: `_step1_upload` now shows an **explicit sheet
  dropdown** (all sheets; auto-detected format pre-selected), and `detect_format` gained a
  **distinctive-column tie-break** (`Cantidad de aceite`→Bitácora, `Longitud total`→Monitoreo,
  `Num.Formato`→Masivos). All three data sheets now detect correctly.
- **Monitoreo pesquero was unsupported.** New **`MONITOREO_LEGACY`** format (biological): one row =
  one `medicion` (`longitud_total_cm` + `peso_gr`/`procesado` derived from Peso Entero/Eviscerado
  ×1000); `FormatSpec.kind="monitoreo"`, `group_faenas` branches to build mediciones, `import_writer`
  resolves/inserts them; `faena.tipo_registro=MASIVO` (matches the COCCBCS biological convention);
  the `cat_formato_origen` row auto-creates on first import. New dev e2e `tests/test_monitoreo_import_e2e.py`.

Along the way: unknown fishing-hours now → **NULL** (was `0`, which violates `CHECK
(tiempo_efectivo_pesca_h > 0)` — every hours-less faena would have failed to insert). That needs the
column nullable → **migration `0017_faena_tiempo_nullable`** (`Planning/supabase/migrations`, applied
to **DEV**; **PROD already in this state** — ~55k biological faenas hold NULL there). ⚠️ `Planning/`
is not a git repo, so `0017` is a loose file — apply/track it wherever prod migrations are managed.

**2026-07-13 — Tembabiche incident, formato-per-form flow, list copying, published read-only view,
pyarrow pin (worked directly on the VPS checkout `/home/pnoserver/monitoreo/catalog-review-app`):**

- **PROD data fix (SQL, no migration).** The "Tembabiche" formulario had been created under the
  `BOCA_ALAMO_V2` formato (the Constructor offered no way to create a formato), so: (a) it could
  never appear in the 👤 Usuarios técnico-assignment picker (which lists *formatos*), and (b)
  `BOCA_ALAMO_V2` had **two published forms** — the tablet loads the newest per formato, so the 3
  Boca técnicos would have gotten the Tembabiche form. Fixed on PROD: new `cat_formato_origen`
  **`TEMBABICHE`**, formulario `5e6b2a1d…` re-pointed to it (0 faenas referenced it), and the 6
  curated lists its fields use copied over (178 `lista_opcion` rows).
- **Constructor: new formulario ⇒ new formato.** Paso ① now defaults to **"➕ Nuevo formato (se crea
  al guardar)"** for brand-new forms (blank *and* "Basar en" copies) — `create_formato()` derives
  `codigo` from the name (slug, `_2`-suffixed on collision). Existing formatos stay selectable
  (first form of a legacy formato); 🌱 Nueva versión keeps its formato as before. Reusing an
  existing formato for a *different* form is exactly what caused the Tembabiche mixup.
- **Curated-list reuse.** Lists stay per-formato (a copy is independent; edits never propagate):
  (a) saving a "Basar en" copy auto-copies the lists its fields reference to the new formato
  (`lista_editor.copy_lista`, idempotent via `UNIQUE(formato,lista,registro)` — re-copy merges,
  never duplicates); (b) the field dialog's list picker gained **"📋 Copiar de otro formulario…"**
  (any formato's list over the same catalog, renameable).
- **Published forms: read-only field view.** ③ Campos shows **👁️ Ver** instead of a disabled ✏️ —
  `_campo_view` dialog: full field config + the curated list's current options (read-only) + a
  **🌱 Crear nueva versión y editar** button. ⚠️ Caveat: list options are per *formato* and live on
  tablet sync, so additions made in the new draft also reach the published version — the prompt is
  workflow guardrail, not isolation (staging lists per version would need a schema change).
- **Ops incident — pyarrow 25.0.0 segfault.** Unpinned `requirements.txt` let the 2026-07-10 image
  rebuild pull pyarrow 25.0.0; every real browser session then segfaulted `libarrow.so.2500`
  (exit 139, kernel log) → container restart → session wiped → *looked like* "login bounces back
  to the login page". `requirements.txt` is now **pinned exact** (streamlit 1.58.0, pandas 3.0.3,
  numpy 2.4.6, pyarrow 24.0.0). ⚠️ AppTest/imports do NOT reproduce it — only the live websocket
  path does; verify dependency bumps with a real browser login, one package at a time.
- **VPS deploy notes.** This server runs only the `console` compose service (no Caddy/TLS; port
  8501 exposed via a deliberate **uncommitted** `docker-compose.yml` edit — kept local so
  Caddy-fronted deploys don't inherit it). Compose commands need `CONSOLE_DOMAIN=unused.local` to
  satisfy interpolation. `scripts/auto-deploy.sh` exists but its cron is **disabled** since
  2026-07-10 — rebuild manually (`docker compose build console && … up -d console`). Host has no
  Python tooling; run one-offs inside the container (its `DATABASE_URL` is **PROD**).
- **Known-stale test:** `tests/test_users_formato.py` fails at collection — its step 3 predates R-B
  (expects formatos *without* a published form in `users_admin._formatos()`); needs a
  published-form fixture.

**2026-07-13 — Catalog proposals on curated-list fields (migrations `0018` + `0019`, both applied to
DEV **and PROD**; prod `_migrations`=19).** Started from "the tablet doesn't show *proponer* on
curated lists" — which turned out to be a non-bug (the "+ Proponer" row only renders after 2+ typed
characters, and on a short curated list nobody types), but tracing it surfaced two real defects and
one design gap:

- **🔥 A Tembabiche proposal would have blocked sync.** `arte_carnada` (tipo=catalogo →
  `cat_tipo_arte`) has `permite_proponer`, but `cat_tipo_arte` was never in
  `catalogo_config.permite_propuestas`; `crear_faena_completa` **RAISEs** on a proposal into a
  non-whitelisted catalog, so the whole faena would have failed to sync and stuck in the outbox.
  Nobody hit it only because nobody had proposed there yet. **`0018`** whitelists it. (`metodo` and
  `destino_pap` also carry the flag but are `seleccion_unica` → no picker → unreachable, just sloppy.)
- **Proposing a name that already exists in the catalog but not in the list.** A curated list is a
  strict *subset*, and the picker only ever saw the list → it offered "+ Proponer" and minted a
  duplicate row. Most catalogs swallow it (their UNIQUE is scoped by an FK the RPC leaves NULL, and
  NULL≠NULL — that's where prod's 48 duplicate pescadores / 95 duplicate sitios come from), but
  `cat_tipo_arte` is **UNIQUE (nombre)** with no NULL escape → `unique_violation` → faena fails to
  sync. Fix (tablet, `cb3a717`): `catalogOutsiders()` surfaces an **exact** catalog match as
  "ya existe · fuera de esta lista"; picking it selects the real row and sends no proposal, and it
  counts as an exact match so "+ Proponer" hides. Exact-only on purpose (a partial match would leak
  the whole catalog into a curated picker). **Deliberately not auto-selected** — common names are
  homonyms (two fish, two fishermen), so the técnico decides, not the code.
- **An approved name vanished from the field it was proposed on.** The strict picker shows listed
  rows + *this device's pending* proposals; approval flips the row to `aprobado` (dropping it from
  that union) and nothing ever added it to the `lista_opcion` list → gone, despite being approved.
  **`0019`**: the tablet now sends `lista` with each proposal and the RPC records it (+ the faena's
  `formato_origen_id`) on the `cambio_catalogo` audit row; the console queue reads it back
  (`proposal_origin`) and **pre-selects that form + list** on approval (`3ed4722`). The old
  hardcoded `LISTABLE` map is gone (it covered only cat_especie/cat_pescador with Boca's list names,
  so Tembabiche's lists and cat_tipo_arte had **no** add-to-list option at all); `listas_for()` now
  reads the lists the form actually curates. Pre-`0019` proposals degrade to the manual choice.

`0019` is **backward compatible**: a proposal without `lista` takes a no-op `CASE` branch, so older
APKs keep working unchanged. ✅ **The tablet half shipped in v1.0.4 / versionCode 5** (built 2026-07-13
from `cb3a717`), so the whole chain is live end-to-end — but ⚠️ **none of it has been exercised on a
device yet** (see the Phase 3 device smoke).
Verified: 34/34 tablet tests (`npm test`, 6 new) + `tsc`; dev e2e of the RPC (real
`crear_faena_completa` with a `cat_tipo_arte` proposal carrying `lista` → audit row holds lista +
formato); console dev round-trip `tests/test_proposals_review.py`. Also fixed a test that was **already
red on `main`** — `getDb opens the database exactly once` (the `formulario_cache.nombre` ALTER made
boot run 2 execs; the assertion was stale, not the code). Migration `0017` was also committed — it had
been a loose untracked file.

**Descargar-datos page — lag + column-editor fixes (2026-07-12, commits `7481e5c` `48761c7` `1fa9a89`):**
toggling a column in "🎚️ Elegir y renombrar columnas" felt laggy and behaved wrongly. Three causes,
all in `export_data.py`:
- **Full-page rerun on every toggle** — Streamlit re-ran all of `render_export` (a ~44 ms saved-queries
  DB round-trip + full-frame summary recompute + a re-render of the 100-row preview) on each click.
  Fix: the column picker + downloads now live in an **`@st.fragment`** (`_columns_and_download`), so a
  toggle reruns only that block. (The preview SQL was already cached in `session_state`.)
- **2nd toggle reverted + list scrolled to top** — `_column_editor` rebuilt the `st.data_editor` `data`
  frame from its own edited output each rerun (unstable object → grid remount → scroll reset; output→input
  feedback → dropped edit). Fix: build the baseline **once per dataset** (`exp_coled_base`, stable object),
  read edits from the return value, never feed them back.
- **KeyError on stale/hot-reloaded session** — baseline was built only on signature change; now built
  whenever `exp_coled_base` is absent **or** the dataset signature changed.

**Data-row editor shipped 2026-07-10** (commit `7e0d6cb`): new ✏️ **Registros (datos)**
console mode (`data_admin.py`) — ADMINISTRADOR-only edit/delete of faena + child rows (11 single-`id`-PK
data tables; `tecnico_comunidad` composite PK excluded). Filter-based row picker (id / FK / date range;
no `count(*)` on big tables), FK-nameless fallback to raw UUID, dependents-guarded delete. `_log` now
attributes every change (catalog **and** data) to the admin (`usuario_id` + `"por"`); no FK on
`cambio_catalogo.usuario_id`. Dev round-trip test: `tests/test_data_admin.py`.

**R5 Excel import — key design decisions** (Masivos+Bitácoras first, pluggable for the rest): repeatable
4-step wizard (`importar` mode); fuzzy-match+confirm catalog resolution (`difflib`, auto-create unknowns
`es_aprobado=false`, NA→*Desconocido* placeholder); rows group into a faena by trip-level natural key,
each species row → captura; dedup by `faena.legacy_id` = natural-key hash (detect & skip on re-import);
target formats already seeded (`MASIVOS_LEGACY`/`BITACORA_LEGACY`/`CM07`); sample file
`Planning/DBScheme/Anexo2.xlsx`. New modules planned: `excel_import.py`, `import_formats.py`,
`catalog_resolver.py`.

(R3 lists in the Form Builder shipped 2026-07-07: view/edit/attach
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

## Phase 3 — Capture-app APK (EAS) ✅ BUILT — device smoke pending
**A production APK was built on 2026-07-13: `v1.0.4` / `versionCode 5`, cut from `main` @ `cb3a717`.**
It therefore carries everything shipped that day: the one-line header (truncate + horizontal-scroll
buttons + tap-to-reveal + ⓘ), the **dynamic form name** in the header (a Tembabiche técnico no longer
sees "Boca del Álamo"), and the curated-list proposal work (outsider guard + proposals carrying their
`lista`, the client half of migrations `0018`/`0019`).

`capture-app/eas.json` (preview + production APK profiles) and `BUILD.md` are committed; the dev
"Descartar" button is gated behind `__DEV__`; `capture-app/.env` points at prod; `eas-cli 20.5.1`.
Rebuild = bump `version` + `versionCode` in `app.json`, then
`eas build --platform android --profile production`.

**⚠️ Still owed — the day-0 device smoke** (Huawei tablet, per `DEVICE_TESTING.md`). Nothing in this
APK has been seen running on hardware. Log in as **`Test_07072026`** (the PRUEBAS técnico — never a
real one), load the form, capture a faena **offline**, GPS/map, then **Sincronizar** → it appears in
the console/DB; verify kg→gr routing. Plus the two things this build changed and no test can cover:
- **Header**: does the title truncate cleanly, do the buttons drag, is the ⓘ legible at `type.caption`
  on the teal bar (bump to `type.body` if not)?
- **Proposals on a curated list**: type a name that exists in the catalog but not the list → expect
  **"ya existe · fuera de esta lista"**, not "+ Proponer". Then propose a genuinely new one, approve it
  in the console (📥 Propuestas — the form + list should be **pre-selected**), and confirm it stays
  visible in the field instead of vanishing.

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
- **Tablet APK — ✅ shipped as v1.0.4 / versionCode 5** (built 2026-07-13 from `cb3a717`; supersedes the
  never-built v1.0.2/vc3 plan). It carries R-E offline-login + password reset + the decimal version,
  and the two 2026-07-13 header changes below. Device smoke still pending — see Phase 3.
  It includes the **header overflow fix (2026-07-13, `capture-app`
  `a9df431`/`3ffee61`/`838c017`)**: on narrow devices the title `Boca del Álamo · v<version>`
  word-wrapped **and** the button row (`flexWrap: 'wrap'`) spilled onto a second line, inflating the
  header — two causes, not one. In `App.tsx`: the title/user lines now truncate (`numberOfLines={1}` +
  tail ellipsis) and the buttons sit in a **horizontal `ScrollView`** instead of wrapping. Because the
  title can now be cut, tapping the header info block opens an **`Alert`** with the full title + user +
  version, and an **ⓘ glyph** marks it as tappable — the glyph is a *sibling* of the title `Text`
  (`barTitleRow`), not part of its string, so the ellipsis can't eat it. ⚠️ Typechecks, and it is
  **in the v1.0.4 APK, but has never been seen on a device** — eyeball it on the Huawei (truncation
  point, drag feel of the button strip, ⓘ legibility at `type.caption` on the teal bar).
  It also carries the **dynamic header title (2026-07-13, `capture-app` `0b1229e`)**:
  the header + tap-Alert hardcoded "Boca del Álamo" with only the version dynamic, so a técnico
  assigned to Tembabiche saw *"Boca del Álamo · v1"* (the right form **was** loading — only the label
  lied). Now `cacheForm` selects `formulario.nombre`, `formulario_cache` gains a `nombre` column
  (try/ignore `ALTER TABLE` patches existing installs — there's still no migration system), and
  `App.tsx` renders `form.nombre` (fallback `'Formulario'` for a stale offline cache). The dead
  `FORMATO_PILOTO` const (unused since R4) is gone. Typechecks; in v1.0.4; not yet run on a device.

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
