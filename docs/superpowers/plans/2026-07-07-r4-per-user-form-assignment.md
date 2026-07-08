# R4 — Per-user form assignment: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Assign one form (formato) to each técnico so the capture app loads *that técnico's* form instead of a hardcoded constant, blocking técnicos who have none.

**Architecture:** A nullable FK `usuario.formato_origen_id → cat_formato_origen` (DB migration + backfill of existing técnicos). The console (`users_admin.py`) sets/edits it when managing a TECNICO. The capture app reads it from the (already-cached) profile, uses it as the formato to load, and shows a block screen when it is null. Offline persistence rides on the existing `usuario` profile cache — no new store.

**Tech Stack:** Postgres (Supabase); Python 3.13 + Streamlit + psycopg2 (console); React Native / Expo + TypeScript (capture app).

**Spec:** `docs/superpowers/specs/2026-07-07-r4-per-user-form-assignment-design.md`

## Global Constraints

- Three repos: the migration lives in **supabase-backend** (`Planning/supabase/migrations/`); the console + its tests in **catalog-review-app**; the tablet in **capture-app**. Commit in the repo you touched; **never push**.
- Work on `main`; commit after each task.
- All console + tablet UI copy in **plain Spanish**.
- **DB tests run ONLY against DEV** (project ref `pxxqumcvkoltbjubyvod`) and must hard-abort otherwise. The dev DSN is `DATABASE_URL` in `Planning/supabase/.env` (Windows) or `../supabase-backend/.env` (WSL). **Never print any DSN.**
- Windows execution: run Python from the repo root with `PYTHONIOENCODING=utf-8`; deps are installed in the environment (no scratchpad `PYLIB`). The console `.env` points at **prod**, so DB work overrides `DATABASE_URL` from the environment to dev.
- Reuse, don't duplicate: `_q`/`_exec`/`_log`/`get_conn` from `form_builder.py` (shared `autocommit=True` connection); console conventions — `@st.cache_data` helpers, `friendly_error`, `flash`, `page_header`, `width="stretch"`.

Helper used by several tasks — the dev DSN guard (bash):
```bash
DEVDSN="$(grep -m1 '^DATABASE_URL=' 'D:/Victus/Documents/Servicio/Planning/supabase/.env' | cut -d= -f2- | tr -d '"'\''')"
case "$DEVDSN" in *pxxqumcvkoltbjubyvod*) : ;; *) echo "ABORT: DSN no es DEV"; exit 1;; esac
```

---

### Task 1: DB migration `0015_usuario_formato` + backfill

**Files:**
- Create: `Planning/supabase/migrations/0015_usuario_formato.sql` (supabase-backend repo)

**Interfaces:**
- Produces: column `usuario.formato_origen_id UUID NULL REFERENCES cat_formato_origen(id)`. Tasks 2–4 rely on it existing in dev.

- [ ] **Step 1: Write the failing verification (column must not exist yet)**

Run from `catalog-review-app`:
```bash
DEVDSN="$(grep -m1 '^DATABASE_URL=' 'D:/Victus/Documents/Servicio/Planning/supabase/.env' | cut -d= -f2- | tr -d '"'\''')"
case "$DEVDSN" in *pxxqumcvkoltbjubyvod*) : ;; *) echo "ABORT"; exit 1;; esac
DATABASE_URL="$DEVDSN" PYTHONIOENCODING=utf-8 python -c "from form_builder import _q; _q('SELECT formato_origen_id FROM usuario LIMIT 0'); print('COLUMN EXISTS')"
```
Expected: FAIL — `psycopg2.errors.UndefinedColumn: column "formato_origen_id" does not exist`.

- [ ] **Step 2: Write the migration**

Create `Planning/supabase/migrations/0015_usuario_formato.sql`:
```sql
-- =====================================================================
-- 0015_usuario_formato.sql
-- R4 per-user form assignment: bind a TECNICO to one formato. The capture app
-- loads the latest published formulario of this formato; NULL = sin asignar
-- (el técnico no puede capturar). Backfills existing técnicos to the pilot form
-- so no live técnico is left unassigned when the new APK ships. RLS unchanged:
-- sel_usuario_propio already lets a técnico read their own row.
-- =====================================================================
ALTER TABLE usuario
    ADD COLUMN IF NOT EXISTS formato_origen_id UUID REFERENCES cat_formato_origen(id);

COMMENT ON COLUMN usuario.formato_origen_id IS
  'Formato asignado al técnico (R4). El capture app carga el último formulario publicado de este '
  'formato. NULL = sin asignar (no puede capturar). Solo aplica a rol=TECNICO.';

CREATE INDEX IF NOT EXISTS idx_usuario_formato ON usuario (formato_origen_id);

-- Backfill: existing active técnicos → the pilot formato (no-op if BOCA_ALAMO_V2
-- is absent or the técnico already has one).
UPDATE usuario
   SET formato_origen_id = (SELECT id FROM cat_formato_origen WHERE codigo = 'BOCA_ALAMO_V2')
 WHERE rol = 'TECNICO' AND formato_origen_id IS NULL
   AND EXISTS (SELECT 1 FROM cat_formato_origen WHERE codigo = 'BOCA_ALAMO_V2');

-- =====================================================================
-- FIN 0015_usuario_formato.sql
-- =====================================================================
```

- [ ] **Step 3: Apply to dev**

Run from `Planning/supabase`:
```bash
DEVDSN="$(grep -m1 '^DATABASE_URL=' 'D:/Victus/Documents/Servicio/Planning/supabase/.env' | cut -d= -f2- | tr -d '"'\''')"
case "$DEVDSN" in *pxxqumcvkoltbjubyvod*) : ;; *) echo "ABORT"; exit 1;; esac
DATABASE_URL="$DEVDSN" PYTHONIOENCODING=utf-8 python scripts/apply.py
```
Expected: prints that `0015_usuario_formato.sql` was applied (already-applied files are skipped).

- [ ] **Step 4: Verify the column + backfill**

Run from `catalog-review-app`:
```bash
DATABASE_URL="$DEVDSN" PYTHONIOENCODING=utf-8 python -c "
from form_builder import _q
_q('SELECT formato_origen_id FROM usuario LIMIT 0')            # column exists → no raise
has = _q(\"SELECT count(*) AS n FROM cat_formato_origen WHERE codigo='BOCA_ALAMO_V2'\")[0]['n']
un = _q(\"SELECT count(*) AS n FROM usuario WHERE rol='TECNICO' AND activo AND formato_origen_id IS NULL\")[0]['n']
print('BOCA_ALAMO_V2 en dev:', has, '· técnicos activos sin formato:', un)
assert has == 0 or un == 0, 'backfill dejó técnicos activos sin formato'
print('VERIFY OK')
" 2>&1 | grep -v "No runtime found"
```
Expected: `VERIFY OK`.

- [ ] **Step 5: Commit (supabase-backend repo)**

```bash
cd D:/Victus/Documents/Servicio/Planning/supabase
git add migrations/0015_usuario_formato.sql
git commit -m "0015: usuario.formato_origen_id — per-técnico form assignment (R4)"
```

---

### Task 2: Console data layer + dev round-trip test

**Files:**
- Modify: `users_admin.py` — `create_usuario`, `set_rol`, `list_usuarios`; add `_formatos()`
- Create: `tests/test_users_formato.py`

**Interfaces:**
- Consumes: `form_builder._q`, `form_builder._exec`; the column from Task 1.
- Produces (Task 3 relies on these signatures):
  - `create_usuario(uid, nombre, email, rol, tecnico_id, region_id, formato_origen_id=None, created_by=None)`
  - `set_rol(uid, rol, tecnico_id, formato_origen_id=None)`
  - `list_usuarios()` rows also carry `formato_origen_id` and `formato` (name)
  - `_formatos() -> list[dict]` with keys `id`, `nombre` (active formatos)

- [ ] **Step 1: Write the failing test**

Create `tests/test_users_formato.py`:
```python
"""Dev-only round-trip for the R4 formato-assignment data layer (users_admin).

Locates the DEV DSN (Planning/supabase/.env on Windows, or
../supabase-backend/.env on WSL), refuses to run against anything else, creates
a throwaway formato + usuario, and asserts formato_origen_id round-trips and is
cleared when the role changes away from TECNICO. Audit rows in cambio_catalogo
are left behind by design. Run from the repo root:

    PYTHONIOENCODING=utf-8 python tests/test_users_formato.py
"""
import os
import pathlib
import sys
import uuid

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

DEV_REF = "pxxqumcvkoltbjubyvod"
CANDS = [BASE.parent / "supabase-backend" / ".env",
         BASE.parent / "Planning" / "supabase" / ".env"]
dsn = None
for envf in CANDS:
    if envf.exists():
        for line in envf.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("DATABASE_URL="):
                dsn = line.strip().split("=", 1)[1].strip().strip("'").strip('"')
                break
    if dsn:
        break
assert dsn, f"pon el DSN de DEV en una de: {[str(c) for c in CANDS]}"
assert DEV_REF in dsn, "el DSN no es el proyecto DEV — me niego a correr contra otra base"
os.environ["DATABASE_URL"] = dsn          # form_builder._dsn() prefers the environment

from form_builder import _q, _exec         # noqa: E402
import users_admin as ua                   # noqa: E402

UID = str(uuid.uuid4())
FID = str(uuid.uuid4())
EMAIL = f"zztest_r4_{UID[:8]}@example.test"


def cleanup():
    _exec("DELETE FROM usuario WHERE id=%s", (UID,))
    _exec("DELETE FROM cat_formato_origen WHERE id=%s", (FID,))


cleanup()
_exec("INSERT INTO cat_formato_origen (id, codigo, nombre, activo) "
      "VALUES (%s,%s,%s,true)", (FID, f"ZZ_R4_{UID[:8]}", "Throwaway R4 formato"))
try:
    # 1. create a TECNICO with a formato assignment → persists
    ua.create_usuario(UID, "ZZ Test R4", EMAIL, "TECNICO", None, None, formato_origen_id=FID)
    row = _q("SELECT rol::text AS rol, formato_origen_id::text AS f FROM usuario WHERE id=%s",
             (UID,))[0]
    assert row["rol"] == "TECNICO" and row["f"] == FID

    # 2. list_usuarios surfaces the formato id + name
    me = next(r for r in ua.list_usuarios() if r["id"] == UID)
    assert me["formato_origen_id"] == FID and me["formato"] == "Throwaway R4 formato"

    # 3. _formatos includes our active throwaway formato
    assert any(f["id"] == FID for f in ua._formatos())

    # 4. set_rol away from TECNICO clears the formato (kept only for TECNICO)
    ua.set_rol(UID, "ADMINISTRADOR", None, formato_origen_id=None)
    assert _q("SELECT formato_origen_id FROM usuario WHERE id=%s",
              (UID,))[0]["formato_origen_id"] is None

    # 5. set_rol back to TECNICO with a formato → set again
    ua.set_rol(UID, "TECNICO", None, formato_origen_id=FID)
    assert _q("SELECT formato_origen_id::text AS f FROM usuario WHERE id=%s",
              (UID,))[0]["f"] == FID

    print("TODOS LOS CHECKS PASAN")
finally:
    cleanup()
```

- [ ] **Step 2: Run the test to verify it fails**

Run from `catalog-review-app`:
```bash
PYTHONIOENCODING=utf-8 python tests/test_users_formato.py 2>&1 | grep -v "No runtime found"
```
Expected: FAIL — `TypeError: create_usuario() got an unexpected keyword argument 'formato_origen_id'`.

- [ ] **Step 3: Implement the data layer**

In `users_admin.py`, replace `create_usuario`:
```python
def create_usuario(uid, nombre, email, rol, tecnico_id, region_id,
                   formato_origen_id=None, created_by=None):
    _exec("""INSERT INTO usuario (id, nombre, email, rol, tecnico_id, region_id,
                                  formato_origen_id, activo, created_by)
             VALUES (%s,%s,%s,%s,%s,%s,%s,true,%s)
             ON CONFLICT (id) DO UPDATE SET nombre=excluded.nombre, email=excluded.email,
               rol=excluded.rol, tecnico_id=excluded.tecnico_id, region_id=excluded.region_id,
               formato_origen_id=excluded.formato_origen_id, activo=true""",
          (uid, nombre, email, rol, tecnico_id, region_id,
           formato_origen_id if rol == "TECNICO" else None, created_by))
```

Replace `list_usuarios`:
```python
def list_usuarios():
    return _q("""SELECT u.id::text AS id, u.nombre, u.email, u.rol::text AS rol, u.activo,
                        u.tecnico_id::text AS tecnico_id, t.nombre AS tecnico,
                        u.formato_origen_id::text AS formato_origen_id, f.nombre AS formato
                 FROM usuario u
                 LEFT JOIN cat_tecnico t        ON t.id = u.tecnico_id
                 LEFT JOIN cat_formato_origen f ON f.id = u.formato_origen_id
                 ORDER BY u.activo DESC, u.rol, u.nombre""")
```

Replace `set_rol`:
```python
def set_rol(uid: str, rol: str, tecnico_id, formato_origen_id=None):
    """Change a user's role. tecnico_id/formato_origen_id are kept only for TECNICO."""
    _exec("UPDATE usuario SET rol=%s, tecnico_id=%s, formato_origen_id=%s WHERE id=%s",
          (rol, tecnico_id if rol == "TECNICO" else None,
           formato_origen_id if rol == "TECNICO" else None, uid))
    _log("usuario", uid, "cambiar_rol", {"rol": rol})
```

Add next to `_regiones` (after it):
```python
@st.cache_data(ttl=300, show_spinner=False)
def _formatos():
    return _q("SELECT id::text AS id, nombre FROM cat_formato_origen WHERE activo ORDER BY nombre")
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 python tests/test_users_formato.py 2>&1 | grep -v "No runtime found"
```
Expected: `TODOS LOS CHECKS PASAN`.

- [ ] **Step 5: Commit**

```bash
cd D:/Victus/Documents/Servicio/catalog-review-app
git add users_admin.py tests/test_users_formato.py
git commit -m "Usuarios: formato_origen_id data layer + dev round-trip test (R4)"
```

---

### Task 3: Console UI — assign formato on create + manage

**Files:**
- Modify: `users_admin.py` — `render_users_admin` (create form + listing) and `_manage_account`

**Interfaces:**
- Consumes: `_formatos()`, `create_usuario(..., formato_origen_id=...)`, `set_rol(..., formato_origen_id=...)`, `list_usuarios()` rows with `formato_origen_id`/`formato` (Task 2).

- [ ] **Step 1: Add the formato selectbox to the create form**

In `render_users_admin`, right after the técnico picker block:
```python
        tecnico_id, new_tec = None, None
        if rol == "TECNICO":
            tecnico_id, new_tec = _tec_picker(tmap, key=f"ua_tec_{n}")
```
add:
```python
        formato_id = None
        if rol == "TECNICO":
            fmap = {f["id"]: f["nombre"] for f in _formatos()}
            formato_id = st.selectbox(
                "Formulario asignado (tableta)", [None] + list(fmap),
                format_func=lambda i: "— sin asignar —" if i is None else fmap.get(i, i),
                key=f"ua_fmt_{n}",
                help="El técnico solo podrá capturar el formulario de este formato en la tableta.")
            if not formato_id:
                st.caption("Un técnico sin formulario asignado no podrá capturar en la tableta.")
```

- [ ] **Step 2: Pass the formato into `create_usuario`**

In the same function, change the create call:
```python
                create_usuario(uid, nombre.strip(), email.strip().lower(), rol, tid, region_id)
```
to:
```python
                create_usuario(uid, nombre.strip(), email.strip().lower(), rol, tid, region_id,
                               formato_origen_id=formato_id)
```

- [ ] **Step 3: Show the assignment in the listing**

In the listing loop, replace:
```python
            c[2].markdown(f"téc: {u['tecnico'] or '—'}")
```
with:
```python
            _form = f"  \nform: {u['formato']}" if u["rol"] == "TECNICO" and u.get("formato") else ""
            c[2].markdown(f"téc: {u['tecnico'] or '—'}{_form}")
```

- [ ] **Step 4: Add the formato selectbox to `_manage_account` (change-role)**

In `_manage_account`, replace:
```python
    newtec, newtec_name = u.get("tecnico_id"), None
    if newrol == "TECNICO":
        newtec, newtec_name = _tec_picker(tmap, key=f"roltec_{uid}", current=u.get("tecnico_id"))
    if st.button("Guardar rol", key=f"chr_{uid}", width="stretch"):
        try:
            tid = newtec
            if newrol == "TECNICO" and newtec_name and newtec_name.strip():
                tid = create_tecnico(newtec_name)
            if newrol == "TECNICO" and not tid:
                st.error("Un técnico debe vincularse a un cat_tecnico.")
            else:
                set_rol(uid, newrol, tid)
                flash(f"Rol de {u['nombre']} cambiado a {newrol}."); st.rerun()
        except Exception as e:  # noqa: BLE001
            st.error(friendly_error(e))
```
with:
```python
    newtec, newtec_name = u.get("tecnico_id"), None
    newfmt = u.get("formato_origen_id")
    if newrol == "TECNICO":
        newtec, newtec_name = _tec_picker(tmap, key=f"roltec_{uid}", current=u.get("tecnico_id"))
        fmap = {f["id"]: f["nombre"] for f in _formatos()}
        fopts = [None] + list(fmap)
        cur = u.get("formato_origen_id")
        newfmt = st.selectbox(
            "Formulario asignado (tableta)", fopts,
            index=fopts.index(cur) if cur in fopts else 0,
            format_func=lambda i: "— sin asignar —" if i is None else fmap.get(i, i),
            key=f"rolfmt_{uid}")
        if not newfmt:
            st.caption("Sin formulario asignado, el técnico no podrá capturar en la tableta.")
    if st.button("Guardar rol", key=f"chr_{uid}", width="stretch"):
        try:
            tid = newtec
            if newrol == "TECNICO" and newtec_name and newtec_name.strip():
                tid = create_tecnico(newtec_name)
            if newrol == "TECNICO" and not tid:
                st.error("Un técnico debe vincularse a un cat_tecnico.")
            else:
                set_rol(uid, newrol, tid, formato_origen_id=newfmt if newrol == "TECNICO" else None)
                flash(f"Rol de {u['nombre']} cambiado a {newrol}."); st.rerun()
        except Exception as e:  # noqa: BLE001
            st.error(friendly_error(e))
```

- [ ] **Step 5: AppTest smoke — app boots, Usuarios renders**

Write to a scratch file (NOT the repo) `smoke_r4.py`:
```python
import os, sys
os.chdir(r"D:/Victus/Documents/Servicio/catalog-review-app")
sys.path.insert(0, r"D:/Victus/Documents/Servicio/catalog-review-app")
from streamlit.testing.v1 import AppTest

at = AppTest.from_file("app.py", default_timeout=120)
at.session_state["auth_rol"] = "ADMINISTRADOR"
at.session_state["auth_nombre"] = "QA"
at.run(); assert not at.exception, at.exception
at.session_state["console_mode"] = "usuarios"
at.run(); assert not at.exception, at.exception
print("SMOKE PASS")
```
Run: `PYTHONIOENCODING=utf-8 python <scratch>/smoke_r4.py`
Expected: `SMOKE PASS` (this read-only smoke uses the console `.env` = prod, matching the R3 norm; it renders modes and clicks nothing).

- [ ] **Step 6: Re-run the Task 2 test (regression) + commit**

```bash
PYTHONIOENCODING=utf-8 python tests/test_users_formato.py 2>&1 | grep -v "No runtime found"   # TODOS LOS CHECKS PASAN
git add users_admin.py
git commit -m "Usuarios: assign/edit formato del técnico en la UI (R4)"
```

---

### Task 4: Capture app — load the assigned formato, block if none

**Files:**
- Modify: `capture-app/src/sync/supabaseClient.ts` — `Usuario` type + `loadUsuario` select
- Modify: `capture-app/App.tsx` — bootstrap + a block screen
- Modify: `capture-app/src/config.ts` — drop `FORMATO_PILOTO` from the bootstrap path (only if unused elsewhere)

**Interfaces:**
- Consumes: `usuario.formato_origen_id` (from the DB column, Task 1). Offline persistence rides on the existing `USUARIO_KEY` profile cache in `loadUsuario`.

- [ ] **Step 1: Add `formato_origen_id` to the profile type + read**

In `capture-app/src/sync/supabaseClient.ts`, in `interface Usuario`, after the `tecnico_id` line add:
```typescript
  formato_origen_id: string | null;   // → cat_formato_origen (R4: which form loads on the tablet)
```
And in `loadUsuario`, extend the select:
```typescript
      .select('id, nombre, rol, region_id, tecnico_id, pescador_id')
```
to:
```typescript
      .select('id, nombre, rol, region_id, tecnico_id, pescador_id, formato_origen_id')
```

- [ ] **Step 2: Rework `bootstrap` in `App.tsx`**

Add a block-state next to the other `useState` hooks (near the top of the component):
```typescript
  const [blocked, setBlocked] = useState<string | null>(null);
```
Replace the current `bootstrap` body (the profile load + hardcoded formato lookup + sync) with:
```typescript
  async function bootstrap() {
    setBlocked(null);
    setStatus('Cargando perfil…');
    const u = await loadUsuario();
    setUsuario(u);

    const formatoId = u?.formato_origen_id ?? null;
    if (u && !formatoId) {
      setBlocked('No tienes un formulario asignado. Pide a un administrador que te asigne uno.');
      return;
    }
    if (!formatoId) {
      setBlocked('No se pudo cargar tu perfil. Conéctate a internet e inténtalo de nuevo.');
      return;
    }

    // Refresh from the server when reachable; fall back to the local cache offline.
    try {
      setStatus('Actualizando catálogos…');
      const n = await syncCatalogs(supabase(), CATALOGOS_PILOTO);
      const { resueltas } = await reconcileProposals(supabase());
      setStatus('Actualizando formulario…');
      await cacheForm(supabase(), formatoId);
      const nl = await syncListas(supabase(), formatoId);   // curated per-form option lists
      console.log(`catalogos: ${n} filas · propuestas reconciliadas: ${resueltas} · listas: ${nl}`);
    } catch (e) {
      console.log('sin conexión, usando caché local:', String(e));
    }

    const cached = await getCachedForm(formatoId);
    if (!cached) throw new Error('No hay formulario en caché. Conéctate a internet y reinicia.');
    setForm(cached);
    await refreshPend();
    setStatus('Listo');
  }
```

- [ ] **Step 3: Render the block screen + reset on logout**

In `App.tsx`, add this branch just before the existing `if (!form) {` spinner branch:
```tsx
  if (blocked) {
    return (
      <View style={[s.flex, s.center]}>
        <Text style={[s.status, { paddingHorizontal: space.lg, textAlign: 'center' }]}>{blocked}</Text>
        <Pressable style={s.btnGhost} onPress={logout}><Text style={s.btnGhostTxt}>Salir</Text></Pressable>
      </View>
    );
  }
```
In `logout`, add `setBlocked(null);` alongside the other resets. (If `Pressable`/`s.btnGhost`/`s.btnGhostTxt` are not already in scope, reuse whatever button + style the existing bar uses — match the sign-out control in the top bar; `space` is already imported from `./src/ui/theme`.)

- [ ] **Step 4: Drop the unused `FORMATO_PILOTO` from `App.tsx`'s import**

In `App.tsx`, change the config import so `FORMATO_PILOTO` is no longer imported (keep `CATALOGOS_PILOTO`). For example:
```typescript
import { CATALOGOS_PILOTO } from './src/config';
```
Leave `FORMATO_PILOTO` defined in `config.ts` (harmless; still documents the pilot slug) unless a search shows no remaining references.

- [ ] **Step 5: Typecheck**

Run:
```bash
cd D:/Victus/Documents/Servicio/capture-app
npx tsc --noEmit
```
Expected: no errors. (If `tsc` reports an unused `FORMATO_PILOTO`, remove it from `config.ts`; if it flags the ghost import, ensure Step 4's import list is correct.)

- [ ] **Step 6: Manual device/emulator check (documented; no RN test harness)**

With the console (Task 3) pointed at a dev técnico:
1. A técnico **with** a formato assigned → the app loads that form (no picker), captures as before.
2. A técnico **with none** (set "— sin asignar —" in the console) → the block screen shows *"No tienes un formulario asignado…"* with a working **Salir**.
3. Assign one, relaunch → form loads. Then **airplane mode**, relaunch → the cached form still loads (offline reads the cached profile + `getCachedForm`).

- [ ] **Step 7: Commit**

```bash
cd D:/Victus/Documents/Servicio/capture-app
git add App.tsx src/sync/supabaseClient.ts src/config.ts
git commit -m "Tablet: load the técnico's assigned formato; block if unassigned (R4)"
```

---

### Task 5: Docs — handoff roadmap

**Files:**
- Modify: `catalog-review-app/handoff.md` (roadmap line)

- [ ] **Step 1: Update the roadmap**

In `handoff.md`, change the roadmap line from:
```
**Roadmap remaining:** R4 per-user form assignment · R5 Excel bulk import (own deep plan) · R6
```
to:
```
**Roadmap remaining:** R5 Excel bulk import (own deep plan) · R6
```
and append to the R3 parenthetical block a new sentence:
```
(R4 per-user form assignment shipped 2026-07-07: usuario.formato_origen_id + console assign UI;
the tablet loads the técnico's assigned form and blocks if unassigned. Migration 0015 must be
applied to prod via apply.py before the new APK ships.)
```

- [ ] **Step 2: Commit**

```bash
cd D:/Victus/Documents/Servicio/catalog-review-app
git add handoff.md
git commit -m "docs: R4 shipped — per-user form assignment"
```

---

## Rollout notes (not executed by this plan)

Prod is **not** touched here. When ready to go live, in order:
1. Apply `0015` to **prod**: from `Planning/supabase`, `DATABASE_URL="<PROD_DATABASE_URL>" python scripts/apply.py` (env-first override, per `PROD_ROLLOUT.md`). The backfill pins the existing prod técnicos to Boca del Álamo, so the current APK keeps working.
2. Deploy the console (Task 2–3) — admins can now assign formatos.
3. Build the new APK (folds into Phase 3) — it reads the assignment and enforces the block.

## Self-review

- **Spec coverage:** column + backfill + no-RLS-change (Task 1); optional console assign on create + edit, listing display (Tasks 2–3); capture app reads assignment, blocks if none, offline via existing profile cache (Task 4); dev-only round-trip + AppTest smoke + manual device check (Tasks 2–4); rollout ordering + prod-deferred (Rollout notes). Non-goals (join table, per-version, region-derived) intentionally untouched. No gaps.
- **Type consistency:** `create_usuario(..., formato_origen_id=None, created_by=None)` and `set_rol(..., formato_origen_id=None)` match their Task 3 call sites; `list_usuarios()` exposes `formato_origen_id`/`formato` consumed in Task 3 and Task 2's test; `_formatos()` returns `{id, nombre}` used by both selectboxes and the test; `Usuario.formato_origen_id` matches the `loadUsuario` select and the `bootstrap` read.
- **Placeholder scan:** every code step shows complete code; the only conditional guidance (Task 4 Step 3/4 style-reuse) names the concrete fallback (match the top-bar sign-out control) rather than leaving it open.
- **Known constraint:** a pre-upgrade cached profile lacks `formato_origen_id` → treated as unassigned until the next online sync re-caches it; acceptable and self-healing.
