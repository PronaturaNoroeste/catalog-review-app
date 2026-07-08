# R4 — Per-user form assignment: Design spec

**Goal:** Let an admin assign a specific form (formato) to each técnico, so the capture
app loads *that técnico's* form instead of a compiled-in constant. Prepares the pilot for a
multi-cooperativa rollout where different técnicos capture different forms.

**Date:** 2026-07-07

## Context — current state

The capture app is hardcoded to a single form. `capture-app/src/config.ts` defines
`FORMATO_PILOTO = 'BOCA_ALAMO_V2'`; `App.tsx` bootstrap resolves that codigo →
`cat_formato_origen.id` and caches that one form for **every** técnico, regardless of who logs
in. There is no per-técnico notion of "which form is mine."

Data model (relevant bits):
- `usuario` (id = auth.users.id): `rol`, `region_id` (RLS scope), `tecnico_id` (→ `cat_tecnico`),
  `activo`. RLS `sel_usuario_propio` lets a user read **their own** row.
- `formulario`: scoped by `formato_origen_id` (→ `cat_formato_origen`), versioned; the tablet
  downloads the **latest published** form for a formato. RLS: readable by `authenticated`.
- `cat_formato_origen`: the cooperativa/site/format catalog (a controlled vocab, no approval flow).

## Locked decisions

- **Granularity:** assignment is at the **`formato_origen`** level (a cooperativa/site), not a
  specific form version — versioning stays automatic (tablet always pulls the latest published).
- **Cardinality:** **exactly one** formato per técnico → a nullable FK column on `usuario`, not a
  join table. (A join table is the future path if this ever becomes many-per-técnico — explicitly
  out of scope now, YAGNI.)
- **Unassigned técnico:** the tablet **blocks** with a plain-Spanish message; it does not load any
  form and does not fall back to a default.
- **Offline persistence:** included — the assigned formato is cached locally so an offline
  cold-start still loads the right cached form.
- **Console assignment:** **optional** (not hard-required) with a warning when left empty.
- **Capture app:** built now, as part of R4 (not deferred to the Phase 3 APK work).

## Architecture overview

Three coordinated changes, each independently safe to ship (see Rollout ordering):

1. **DB migration** `0015_usuario_formato` — add the column + backfill existing técnicos.
2. **Console** (`users_admin.py`) — assign/edit the formato when managing a TECNICO.
3. **Capture app** — read the assigned formato from the profile, block if none, persist offline.

---

## 1 — Data model & migration (`Planning/supabase/migrations/0015_usuario_formato.sql`)

- Add the column:
  ```sql
  ALTER TABLE usuario
    ADD COLUMN formato_origen_id UUID REFERENCES cat_formato_origen(id);
  COMMENT ON COLUMN usuario.formato_origen_id IS
    'Formato asignado al técnico (R4). El capture app carga el último formulario publicado de este '
    'formato. NULL = sin asignar (el técnico no puede capturar). Solo aplica a rol=TECNICO.';
  CREATE INDEX idx_usuario_formato ON usuario (formato_origen_id);
  ```
- **Backfill** so no live técnico is ever blocked when the new APK ships:
  ```sql
  UPDATE usuario
     SET formato_origen_id = (SELECT id FROM cat_formato_origen WHERE codigo = 'BOCA_ALAMO_V2')
   WHERE rol = 'TECNICO' AND formato_origen_id IS NULL;
  ```
- **RLS:** no change. `sel_usuario_propio` already lets a técnico read their own `usuario` row
  (the new column rides along); `formulario` is already readable by `authenticated`.
- Applied dev → prod via `apply.py` (env-first DSN override, per `PROD_ROLLOUT.md`). `_migrations`
  advances to 15.

## 2 — Console (`users_admin.py`)

- **Data layer:**
  - `create_usuario(...)` and `set_rol(...)` gain a `formato_origen_id` param, persisted only when
    `rol == 'TECNICO'` (NULL otherwise — mirrors the existing `tecnico_id` handling).
  - New helper `formato_options() -> list[dict]` — active `cat_formato_origen` rows as
    `{id, nombre}` (or `codigo` if `nombre` is absent), for the selectbox.
  - Extend the users listing query to show each técnico's assigned formato name (LEFT JOIN
    `cat_formato_origen`).
- **UI** (`render_users_admin`):
  - In the **create** form and the **edit/role** row, when `rol == 'TECNICO'`, render a
    **"Formulario asignado"** selectbox including a **"— sin asignar —"** option; default to the
    técnico's current assignment on edit.
  - When left "— sin asignar —", show a caption: *"Un técnico sin formulario asignado no podrá
    capturar en la tableta."* (warning, not a block — assignment is optional).
  - Show the current assignment in the técnico listing.
- **Plain Spanish** throughout; reuse `friendly_error` on writes (repo convention).

## 3 — Capture app

- **`src/sync/supabaseClient.ts`** — extend `loadUsuario`'s select and the `Usuario` type with
  `formato_origen_id: string | null`.
- **`App.tsx` bootstrap** — replace the hardcoded formato resolution:
  - Remove the `cat_formato_origen … .eq('codigo', FORMATO_PILOTO)` lookup.
  - Resolve `formatoId` as follows:
    1. If `usuario?.formato_origen_id` is present → use it (it's already the UUID). No dedicated
       persistence step is needed: `loadUsuario` already caches the whole profile under
       `USUARIO_KEY`, so `formato_origen_id` rides along with it for free.
    2. Else if online read returned a profile with **null** formato → **blocked screen**:
       *"No tienes un formulario asignado — contacta a un administrador."* Do not call `cacheForm`.
    3. Else (offline / profile read failed) → fall back to the cached `usuario` profile
       (`kvStorage.get(USUARIO_KEY)`) and read its `formato_origen_id`; if present, load from
       `getCachedForm`; if absent, show the offline/first-run message
       (*"Conéctate a internet para descargar tu formulario."*).
  - `cacheForm` / `syncListas` / `getCachedForm` continue to key on this `formatoId`.
- **`config.ts`** — `FORMATO_PILOTO` is removed from the bootstrap path (kept only if another module
  still references it; `CATALOGOS_PILOTO`, the catalog-sync list, is untouched).
- **Offline store:** reuse the existing `USUARIO_KEY` profile cache in the SQLite `kv` table via
  `kvStorage` (already used for the auth session and profile) — no new key, no new dependency.

## 4 — Testing

- **Console (dev-only DB round-trip)** — mirror the R3 test harness (`tests/`, dev DSN guard,
  throwaway rows): create a usuario with a formato assignment → read it back → reassign → clear;
  assert `formato_origen_id` round-trips and is NULLed when rol changes away from TECNICO.
- **Console (AppTest smoke)** — Usuarios mode renders with the new selectbox present; app boots
  without exception (`auth_rol`/`auth_nombre` pre-seeded, per repo convention).
- **Migration** — apply to dev; assert the column exists and the backfill set every active TECNICO
  to the Boca del Álamo formato; then prod.
- **Capture app (manual device check)** — an assigned técnico loads their form; an unassigned
  técnico sees the block screen; airplane-mode cold-start loads the cached form via the
  `formato_origen_id` in the cached `usuario` profile. (The capture app has little automated
  coverage; this stays manual.)

## 5 — Rollout ordering

1. **Migration** — adds the column and backfills existing técnicos. The *current* (hardcoded) APK
   ignores the column and keeps working; no live técnico becomes unassigned.
2. **Console** — admins can now set assignments (dev-tested first, as always, since the console
   `.env` points at prod).
3. **New APK** (folds into Phase 3) — reads the assignment and enforces the block-on-unassigned.

The three are independently safe precisely because the backfill guarantees no live técnico is ever
unassigned at cutover.

## Non-goals (YAGNI)

- Multiple formatos per técnico / a `tecnico_formato` join table (revisit only if cardinality
  changes).
- Assigning a specific form *version* (the tablet's latest-published model already handles versions).
- Region-derived assignment (formato is not 1:1 with region).
