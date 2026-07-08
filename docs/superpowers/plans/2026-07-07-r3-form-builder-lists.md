# R3 — Curated-list editing in the Form Builder: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a console admin view/edit a field's curated option list (`lista_opcion`) and attach/detach lists, directly inside the Form Builder's field dialog.

**Architecture:** New small module `lista_editor.py` (data layer + one expander UI entry point) called from `form_builder._campo_dialog`. Reuses `form_builder`'s DB layer (`_q`/`_exec`/`_log`) and `lista_import`'s normalization/name-column conventions. The field's `lista` key already round-trips through the builder (`_FIELD_COLS`), so persistence of attach/detach rides the existing Guardar path.

**Tech Stack:** Python 3.13, Streamlit 1.59, psycopg2, pandas. Postgres (Supabase). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-07-r3-form-builder-lists-design.md`

## Global Constraints

- Repo: `/home/maikolkali/bitacora/catalog-review-app` (work on `main`; commit after each task, **never push**).
- All UI copy in **plain Spanish**.
- DB tests run **only against DEV** (project ref `pxxqumcvkoltbjubyvod`). The dev DSN must be in `/home/maikolkali/bitacora/supabase-backend/.env` as `DATABASE_URL` (user pastes it; gitignored). Tests must hard-abort if the DSN is not the dev project.
- Python deps live in the scratchpad: `export PYLIB=/tmp/claude-1000/-home-maikolkali-bitacora-catalog-review-app/ddd35b16-92f1-4d3a-927e-cb966cd01933/scratchpad/pylib` — run everything with `PYTHONPATH="$PYLIB:."` from the repo root.
- Streamlit conventions in this repo: `width="stretch"` (not `use_container_width`), function-local `console_ui` imports, widget keys prefixed with the dialog's `k`.
- Reuse, don't duplicate: `_q`/`_exec`/`_log`/`_slug` from `form_builder.py`; `_norm`/`_name_col` from `lista_import.py`; `friendly_error` from `console_ui.py`.
- Never print any DSN.

---

### Task 1: `lista_editor.py` data layer + dev round-trip test

**Files:**
- Create: `lista_editor.py` (data-layer half)
- Create: `tests/test_lista_editor.py`

**Interfaces:**
- Consumes: `form_builder._q(sql, args=None) -> list[dict]`, `form_builder._exec(sql, args=())`, `form_builder._log(tabla, rid, accion, detalle)`; `lista_import._norm(s) -> str`, `lista_import._name_col(tabla) -> str`.
- Produces (Task 2/3 rely on these exact signatures):
  - `form_listas(formato_id: str) -> dict[str, str]` — list name → tabla
  - `get_opciones(formato_id: str, lista: str, tabla: str) -> list[dict]` — keys `registro_id`, `nombre`, `importancia` (+ `cientifico` for `cat_especie`), ordered importancia desc then nombre
  - `search_catalogo(tabla: str, q: str, exclude_ids: set[str] | None = None, limit: int = 20) -> list[dict]` — keys `id`, `nombre` (+ `cientifico`)
  - `add_opcion(formato_id, lista, tabla, registro_id, importancia=0)`
  - `remove_opcion(formato_id, lista, registro_id)`
  - `set_importancia(formato_id, lista, registro_id, imp)`
  - `create_and_add(formato_id, lista, tabla, nombre, sci=None, importancia=0) -> str` (new row id)

- [ ] **Step 1: Write the failing test**

Create `tests/test_lista_editor.py`:

```python
"""Round-trip test for lista_editor's data layer against the DEV database.

Requires the dev DSN in ../supabase-backend/.env (DATABASE_URL) and refuses to
run against anything that isn't the dev project. Creates a throwaway formato +
catalog rows, exercises the API, and cleans up after itself (audit rows in
cambio_catalogo are left — the trail is append-only by design).

Run from the repo root:  PYTHONPATH="$PYLIB:." python3 tests/test_lista_editor.py
"""
import os
import pathlib
import sys
import uuid

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

DEV_REF = "pxxqumcvkoltbjubyvod"
envf = BASE.parent / "supabase-backend" / ".env"
dsn = None
if envf.exists():
    for line in envf.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("DATABASE_URL="):
            dsn = line.strip().split("=", 1)[1].strip().strip("'").strip('"')
            break
assert dsn, f"pon el DSN de DEV en {envf}"
assert DEV_REF in dsn, "el DSN no es el proyecto DEV — me niego a correr contra otra base"
os.environ["DATABASE_URL"] = dsn      # form_builder._dsn() prefers the environment

from form_builder import _q, _exec    # noqa: E402
import lista_editor as le             # noqa: E402

FID = str(uuid.uuid4())
TAG = f"ZZTEST R3 {FID[:8]}"


def cleanup():
    _exec("DELETE FROM lista_opcion WHERE formato_origen_id=%s", (FID,))
    _exec("DELETE FROM cat_especie WHERE nombre_comun LIKE %s", (TAG + "%",))
    _exec("DELETE FROM cat_formato_origen WHERE id=%s", (FID,))


_exec("INSERT INTO cat_formato_origen (id, codigo, nombre, activo) "
      "VALUES (%s,%s,%s,false)", (FID, f"TEST_R3_{FID[:8]}", "Throwaway R3 test"))
try:
    # 1. a fresh formato has no lists
    assert le.form_listas(FID) == {}

    # 2. create_and_add: brand-new approved especie lands in catalog + list
    n1 = f"{TAG} uno"
    rid1 = le.create_and_add(FID, "especies_test", "cat_especie", n1, "Testus unus")
    row = _q("SELECT estado, es_aprobado, nombre_cientifico FROM cat_especie WHERE id=%s",
             (rid1,))[0]
    assert row["estado"] == "aprobado" and row["es_aprobado"] is True
    assert row["nombre_cientifico"] == "Testus unus"
    ops = le.get_opciones(FID, "especies_test", "cat_especie")
    assert [o["registro_id"] for o in ops] == [rid1]
    assert ops[0]["nombre"] == n1 and ops[0]["cientifico"] == "Testus unus"
    assert ops[0]["importancia"] == 0

    # 3. search: accent/case-insensitive, respects exclude_ids
    hits = le.search_catalogo("cat_especie", f"zztest r3 {FID[:8]} UNO")
    assert any(h["id"] == rid1 for h in hits)
    hits = le.search_catalogo("cat_especie", n1, exclude_ids={rid1})
    assert not any(h["id"] == rid1 for h in hits)

    # 4. add an existing row; higher importancia sorts first
    n2 = f"{TAG} dós"                             # accent exercises _norm
    rid2 = str(uuid.uuid4())
    _exec("INSERT INTO cat_especie (id, nombre_comun, nombre_cientifico, es_aprobado, estado) "
          "VALUES (%s,%s,'Testus duo',true,'aprobado')", (rid2, n2))
    le.add_opcion(FID, "especies_test", "cat_especie", rid2, importancia=5)
    ops = le.get_opciones(FID, "especies_test", "cat_especie")
    assert [o["registro_id"] for o in ops] == [rid2, rid1]

    # 5. form_listas now sees it
    assert le.form_listas(FID) == {"especies_test": "cat_especie"}

    # 6. set_importancia reorders; re-add is an upsert (no duplicate)
    le.set_importancia(FID, "especies_test", rid1, 9)
    ops = le.get_opciones(FID, "especies_test", "cat_especie")
    assert ops[0]["registro_id"] == rid1 and ops[0]["importancia"] == 9
    le.add_opcion(FID, "especies_test", "cat_especie", rid2, importancia=7)
    assert len(le.get_opciones(FID, "especies_test", "cat_especie")) == 2

    # 7. search returns only estado='aprobado' rows (search the full unique
    # name — a short term like «dós» could match unrelated dev species)
    _exec("UPDATE cat_especie SET estado='pendiente' WHERE id=%s", (rid2,))
    assert not le.search_catalogo("cat_especie", n2)
    _exec("UPDATE cat_especie SET estado='aprobado' WHERE id=%s", (rid2,))

    # 8. remove one option; the other stays
    le.remove_opcion(FID, "especies_test", rid2)
    ops = le.get_opciones(FID, "especies_test", "cat_especie")
    assert [o["registro_id"] for o in ops] == [rid1]

    # 9. create_and_add on lista 'carnada' marks apta_carnada; blank sci → 'Pendiente'
    rid3 = le.create_and_add(FID, "carnada", "cat_especie", f"{TAG} tres")
    row = _q("SELECT apta_carnada, nombre_cientifico FROM cat_especie WHERE id=%s", (rid3,))[0]
    assert row["apta_carnada"] is True and row["nombre_cientifico"] == "Pendiente"

    print("TODOS LOS CHECKS PASAN")
finally:
    cleanup()
```

- [ ] **Step 2: Run the test to verify it fails**

Run (repo root): `PYTHONPATH="$PYLIB:." python3 tests/test_lista_editor.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'lista_editor'`
(If it fails earlier with `pon el DSN de DEV…`, stop and ask the user to paste the dev DSN into `supabase-backend/.env` first.)

- [ ] **Step 3: Write the data layer**

Create `lista_editor.py`:

```python
"""
📑 Listas curadas dentro del Constructor de formularios (R3).

Data layer + expander UI so a field's curated option list (`lista_opcion`)
can be viewed and edited without leaving the field dialog. Bulk CSV import
stays in 📑 Listas del formulario (lista_import.py). Reuses the form_builder
DB layer and lista_import's conventions (_norm, _name_col) — same homonym
policy: never merge, always create explicitly.

Two clocks (surfaced in the UI): option edits are live on the tablet after
its next sync; attaching/detaching a list edits the field definition and only
takes effect when the form is published.
"""
from __future__ import annotations

import uuid

import streamlit as st

from form_builder import _q, _exec, _log
from lista_import import _norm, _name_col


# =====================================================================
# Data layer
# =====================================================================
def form_listas(formato_id: str) -> dict[str, str]:
    """Existing curated lists of this form → {lista: tabla}."""
    return {r["lista"]: r["tabla"] for r in _q(
        "SELECT DISTINCT lista, tabla FROM lista_opcion WHERE formato_origen_id=%s",
        (formato_id,))}


def get_opciones(formato_id: str, lista: str, tabla: str) -> list[dict]:
    """The list's options with their catalog display name (+científico for
    especies), highest importancia first."""
    nc = _name_col(tabla)
    sci = ", c.nombre_cientifico AS cientifico" if tabla == "cat_especie" else ""
    return _q(f'''SELECT lo.registro_id::text AS registro_id, lo.importancia,
                         c.{nc} AS nombre{sci}
                  FROM lista_opcion lo JOIN public."{tabla}" c ON c.id = lo.registro_id
                  WHERE lo.formato_origen_id=%s AND lo.lista=%s AND lo.tabla=%s
                  ORDER BY lo.importancia DESC, c.{nc}''',
              (formato_id, lista, tabla))


def search_catalogo(tabla: str, q: str, exclude_ids: set[str] | None = None,
                    limit: int = 20) -> list[dict]:
    """Approved rows whose name (or científico) contains `q`, accent- and
    case-insensitive. Filters in Python with _norm — the exact normalization
    the import tool and the tablet use; catalogs are small enough to scan
    (lista_import builds full in-memory maps the same way). Only
    estado='aprobado' rows: the tablet mirrors approved rows only, so an
    unapproved option would silently vanish from the picker."""
    if not (q or "").strip():
        return []
    nc = _name_col(tabla)
    sci = ", nombre_cientifico AS cientifico" if tabla == "cat_especie" else ""
    rows = _q(f'SELECT id::text AS id, {nc} AS nombre{sci} FROM public."{tabla}" '
              f"WHERE estado='aprobado'")
    nq = _norm(q)
    out = [r for r in rows
           if r["id"] not in (exclude_ids or set())
           and (nq in _norm(r["nombre"]) or nq in _norm(r.get("cientifico")))]
    out.sort(key=lambda r: (not _norm(r["nombre"]).startswith(nq), _norm(r["nombre"])))
    return out[:limit]


def add_opcion(formato_id: str, lista: str, tabla: str, registro_id: str,
               importancia: int = 0):
    _exec("""INSERT INTO lista_opcion (formato_origen_id, lista, tabla, registro_id, importancia)
             VALUES (%s,%s,%s,%s,%s)
             ON CONFLICT (formato_origen_id, lista, registro_id)
             DO UPDATE SET importancia=EXCLUDED.importancia""",
          (formato_id, lista, tabla, registro_id, int(importancia or 0)))
    _log("lista_opcion", registro_id, "agregar",
         {"lista": lista, "formato": formato_id, "origen": "constructor"})


def remove_opcion(formato_id: str, lista: str, registro_id: str):
    _exec("DELETE FROM lista_opcion WHERE formato_origen_id=%s AND lista=%s AND registro_id=%s",
          (formato_id, lista, registro_id))
    _log("lista_opcion", registro_id, "quitar",
         {"lista": lista, "formato": formato_id, "origen": "constructor"})


def set_importancia(formato_id: str, lista: str, registro_id: str, imp: int):
    _exec("UPDATE lista_opcion SET importancia=%s "
          "WHERE formato_origen_id=%s AND lista=%s AND registro_id=%s",
          (int(imp), formato_id, lista, registro_id))


def create_and_add(formato_id: str, lista: str, tabla: str, nombre: str,
                   sci: str | None = None, importancia: int = 0) -> str:
    """Create a new APPROVED catalog row — like lista_import's 'crear', it never
    merges — and add it to the list. Returns the new row's id."""
    rid = str(uuid.uuid4())
    nc = _name_col(tabla)
    cols, vals = ["id", nc, "es_aprobado", "estado"], [rid, nombre.strip(), True, "aprobado"]
    if tabla == "cat_especie":
        cols += ["nombre_cientifico", "apta_carnada"]
        vals += [((sci or "").strip() or "Pendiente"), lista == "carnada"]
    _exec(f'INSERT INTO public."{tabla}" ({", ".join(cols)}) '
          f'VALUES ({", ".join(["%s"] * len(vals))})', vals)
    _log(tabla, rid, "crear", {"nombre": nombre.strip(), "origen": "constructor"})
    add_opcion(formato_id, lista, tabla, rid, importancia)
    return rid
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `PYTHONPATH="$PYLIB:." python3 tests/test_lista_editor.py`
Expected: `TODOS LOS CHECKS PASAN` (bare-mode Streamlit warnings on stderr are normal).

- [ ] **Step 5: Commit**

```bash
git add lista_editor.py tests/test_lista_editor.py
git commit -m "Constructor: lista_editor data layer (curated lists, R3)"
```

---

### Task 2: `render_lista_editor` expander UI

**Files:**
- Modify: `lista_editor.py` (append the UI half)

**Interfaces:**
- Consumes: Task 1's data layer; `form_builder._slug`; `console_ui.friendly_error` (function-local import, repo convention).
- Produces (Task 3 relies on this exact signature): `render_lista_editor(formato_id: str | None, tabla: str | None, lista_actual: str, default_name: str, key: str) -> str` — renders the attach selectbox + options expander; returns the lista name the field should keep (`""` = sin lista). **It performs option writes itself (immediate); the caller persists only the returned name into the field definition.**

- [ ] **Step 1: Append the UI to `lista_editor.py`**

```python
# =====================================================================
# UI — rendered inside the Form Builder's field dialog
# =====================================================================
_SIN = "— sin lista —"
_NUEVA = "➕ Nueva lista…"


def render_lista_editor(formato_id: str | None, tabla: str | None,
                        lista_actual: str, default_name: str, key: str) -> str:
    """Attach control + options editor for one field. Returns the lista name
    the field should keep ('' = sin lista); the caller saves it on Guardar.
    Option edits (add/remove/importancia) write to lista_opcion immediately."""
    from console_ui import friendly_error
    if not tabla:
        return lista_actual                     # no catalog → nothing to curate
    if not formato_id:
        st.caption("Elige primero el **formato** del formulario (Paso 1) para "
                   "poder usar listas curadas.")
        return lista_actual

    existentes = sorted(l for l, t in form_listas(formato_id).items() if t == tabla)
    if lista_actual and lista_actual not in existentes:
        existentes.append(lista_actual)         # just-attached, still-empty list
    opts = [_SIN] + existentes + [_NUEVA]
    cur = lista_actual if lista_actual in existentes else _SIN
    sel = st.selectbox(
        "Lista curada (las opciones que ve el técnico)", opts,
        index=opts.index(cur), key=f"{key}_sel",
        help="Con una lista curada, el técnico ve solo este subconjunto del "
             "catálogo, ordenado por importancia — no el catálogo completo.")
    if sel == _NUEVA:
        from form_builder import _slug
        lista = _slug(st.text_input("Nombre de la lista nueva", default_name,
                                    key=f"{key}_nm"))
    else:
        lista = "" if sel == _SIN else sel
    st.caption("Adjuntar o quitar la lista es parte del formulario: llega a la "
               "tableta al **publicar**. Las opciones de la lista, en cambio, "
               "cambian al instante.")
    if not lista:
        return ""

    ops = get_opciones(formato_id, lista, tabla)
    es_especie = tabla == "cat_especie"
    with st.expander(f"📑 Opciones de la lista «{lista}» ({len(ops)})",
                     expanded=not ops):
        st.caption("Los cambios de aquí abajo son **inmediatos** en la tableta "
                   "(tras sincronizar). Para subir una lista completa desde un "
                   "CSV usa **📑 Listas del formulario**.")
        if not ops:
            st.warning("La lista está vacía — el técnico no verá opciones en "
                       "este campo hasta que añadas algunas.")
        else:
            import pandas as pd
            df = pd.DataFrame(ops).set_index("registro_id")
            df["quitar"] = False
            show = (["nombre", "cientifico"] if es_especie else ["nombre"]) \
                + ["importancia", "quitar"]
            edited = st.data_editor(
                df[show], key=f"{key}_ed", hide_index=True, width="stretch",
                disabled=["nombre"] + (["cientifico"] if es_especie else []),
                column_config={
                    "nombre": st.column_config.TextColumn("Nombre"),
                    "cientifico": st.column_config.TextColumn("Científico"),
                    "importancia": st.column_config.NumberColumn(
                        "Importancia", step=1,
                        help="Más alto = más arriba en la lista de la tableta."),
                    "quitar": st.column_config.CheckboxColumn("Quitar"),
                })
            if st.button("💾 Guardar cambios en la lista", key=f"{key}_apply"):
                try:
                    orig = {o["registro_id"]: o for o in ops}
                    for rid, row in edited.iterrows():
                        if row["quitar"]:
                            remove_opcion(formato_id, lista, rid)
                        elif int(row["importancia"]) != orig[rid]["importancia"]:
                            set_importancia(formato_id, lista, rid,
                                            int(row["importancia"]))
                    st.rerun()
                except Exception as e:  # noqa: BLE001
                    st.error(friendly_error(e))

        st.markdown("**Añadir opción**")
        q = st.text_input("Buscar en el catálogo", key=f"{key}_q",
                          placeholder="Escribe parte del nombre…")
        if q.strip():
            res = search_catalogo(tabla, q,
                                  exclude_ids={o["registro_id"] for o in ops})
            if res:
                fmt = ((lambda r: f"{r['nombre']} ({r.get('cientifico') or 'sin científico'})")
                       if es_especie else (lambda r: r["nombre"]))
                pick = st.selectbox("Coincidencias en el catálogo", res,
                                    format_func=fmt, key=f"{key}_pick")
                if st.button("➕ Añadir a la lista", key=f"{key}_add"):
                    try:
                        add_opcion(formato_id, lista, tabla, pick["id"])
                        st.rerun()
                    except Exception as e:  # noqa: BLE001
                        st.error(friendly_error(e))
            else:
                st.caption("Sin coincidencias en el catálogo.")
            sci_in = (st.text_input("Nombre científico (opcional, para crear)",
                                    key=f"{key}_sci") if es_especie else None)
            if st.button(f"🆕 Crear «{q.strip()}» y añadir", key=f"{key}_new",
                         help="Crea un registro nuevo aprobado en el catálogo — "
                              "nunca fusiona con los existentes."):
                try:
                    create_and_add(formato_id, lista, tabla, q.strip(), sci_in)
                    st.rerun()
                except Exception as e:  # noqa: BLE001
                    st.error(friendly_error(e))
    return lista
```

- [ ] **Step 2: Verify the module imports cleanly**

Run: `PYTHONPATH="$PYLIB:." python3 -c "import lista_editor; print('import OK'); assert callable(lista_editor.render_lista_editor)"`
Expected: `import OK` (dialog UI itself is exercised in Task 4 — Streamlit dialogs aren't reachable from AppTest).

- [ ] **Step 3: Re-run the Task 1 test (regression)**

Run: `PYTHONPATH="$PYLIB:." python3 tests/test_lista_editor.py`
Expected: `TODOS LOS CHECKS PASAN`

- [ ] **Step 4: Commit**

```bash
git add lista_editor.py
git commit -m "Constructor: lista curada editor UI (expander in the field dialog)"
```

---

### Task 3: Wire into `form_builder` (build_campo + field dialog)

**Files:**
- Modify: `form_builder.py` — `build_campo` (~line 687–716) and `_campo_dialog` (~line 1109–1119 and the Guardar call ~line 1217–1222)
- Modify: `tests/test_lista_editor.py` (append a pure-function test for `build_campo`)

**Interfaces:**
- Consumes: `render_lista_editor(formato_id, tabla, lista_actual, default_name, key) -> str` from Task 2; existing `build_campo(c, v, bindable)` and `_set_or_pop`.
- Produces: `build_campo` honors two new `v` keys — `lista_managed: bool` and `lista: str` (empty string drops the field's `lista` key). Old callers that don't pass `lista_managed` are unaffected (the key is preserved via `dict(c)`).

- [ ] **Step 1: Append the failing pure-function test**

Append to `tests/test_lista_editor.py`, just before the final `print`/`finally` (i.e. inside the `try:` block, after check 9):

```python
    # 10. build_campo: lista set / dropped / preserved
    from form_builder import build_campo
    base_v = {"key": "especie", "label": "Especie", "tipo": "catalogo",
              "bind_tipo": "core", "bind_columna": "captura.especie_id",
              "catalogo": "cat_especie"}
    c0 = {"key": "especie", "tipo": "catalogo", "lista": "especies"}
    # managed + new name → set
    out = build_campo(c0, {**base_v, "lista_managed": True, "lista": "otra"}, {})
    assert out["lista"] == "otra"
    # managed + empty → dropped (detach)
    out = build_campo(c0, {**base_v, "lista_managed": True, "lista": ""}, {})
    assert "lista" not in out
    # not managed → preserved untouched (old callers can't drop it)
    out = build_campo(c0, base_v, {})
    assert out["lista"] == "especies"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH="$PYLIB:." python3 tests/test_lista_editor.py`
Expected: FAIL at check 10 with `AssertionError` on `assert out["lista"] == "otra"` — build_campo doesn't yet honor `lista_managed`, so `out["lista"]` is still the preserved `"especies"`. Checks 1–9 still pass and cleanup still runs (the `finally` block).

- [ ] **Step 3: Implement — build_campo**

In `form_builder.py`, inside `build_campo`, right after the `flags_managed` block:

```python
    if v.get("flags_managed"):
        _set_or_pop(out, "permite_proponer", bool(v.get("permite_proponer")))
        _set_or_pop(out, "permite_otro_texto", bool(v.get("permite_otro_texto")))
    if v.get("lista_managed"):
        _set_or_pop(out, "lista", (v.get("lista") or "").strip())
```

(The first two lines already exist — add only the `lista_managed` pair.)

- [ ] **Step 4: Implement — the dialog**

In `_campo_dialog` (form_builder.py), replace this block:

```python
    flags_managed = tipo in ("catalogo", "seleccion_unica", "multiseleccion")
    prop = otro = None
    if flags_managed:
        if c.get("lista"):
            st.info(f"📑 Este campo usa la lista curada **«{c['lista']}»**. Sus opciones se "
                    "administran en **📑 Listas del formulario**, no aquí.")
```

with:

```python
    flags_managed = tipo in ("catalogo", "seleccion_unica", "multiseleccion")
    prop = otro = None
    lista_val, lista_managed = c.get("lista", ""), False
    if flags_managed:
        field_cat = (bindable.get(col, {}).get("catalogo") if bt == "core" else cat_sel) or ""
        if tipo == "catalogo" and field_cat:
            from lista_editor import render_lista_editor
            lista_val = render_lista_editor(work.get("formato_id"), field_cat,
                                            lista_val, _slug(label), f"{k}_le")
            lista_managed = True
        elif c.get("lista"):
            st.info(f"📑 Este campo usa la lista curada **«{c['lista']}»**. Sus opciones se "
                    "administran en **📑 Listas del formulario**, no aquí.")
```

Then extend the Guardar call's `v` dict (the `build_campo(c, {...}, bindable)` literal) with the two new keys:

```python
            out = build_campo(c, {"key": key_val, "label": label, "tipo": tipo,
                                  "requerido": req, "autocompletar": auto, "ayuda": ayuda,
                                  "bind_tipo": bt, "bind_columna": col, "catalogo": cat_sel,
                                  "flags_managed": flags_managed, "permite_proponer": prop,
                                  "permite_otro_texto": otro, "opciones_simple": opciones_simple,
                                  "lista_managed": lista_managed, "lista": lista_val,
                                  "managed": managed, "adv": adv}, bindable)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `PYTHONPATH="$PYLIB:." python3 tests/test_lista_editor.py`
Expected: `TODOS LOS CHECKS PASAN`

- [ ] **Step 6: Commit**

```bash
git add form_builder.py tests/test_lista_editor.py
git commit -m "Constructor: attach/detach + edit listas curadas from the field dialog (R3)"
```

---

### Task 4: End-to-end verification + handoff update

**Files:**
- Modify: `handoff.md` (roadmap line)
- Create (scratchpad only, not committed): AppTest smoke script

**Interfaces:**
- Consumes: everything above; the AppTest convention from the repo (`auth_rol`/`auth_nombre` pre-seeded session state).

- [ ] **Step 1: AppTest smoke — app boots, Formularios mode renders**

Write to the scratchpad (NOT the repo) `smoke_r3.py`:

```python
import os, sys
os.chdir("/home/maikolkali/bitacora/catalog-review-app")
sys.path.insert(0, "/home/maikolkali/bitacora/catalog-review-app")
from streamlit.testing.v1 import AppTest

at = AppTest.from_file("app.py", default_timeout=120)
at.session_state["auth_rol"] = "ADMINISTRADOR"
at.session_state["auth_nombre"] = "QA"
at.run(); assert not at.exception, at.exception
at.session_state["console_mode"] = "formularios"
at.run(); assert not at.exception, at.exception
print("SMOKE PASS")
```

Run: `PYTHONPATH="$PYLIB" python3 <scratchpad>/smoke_r3.py`
Expected: `SMOKE PASS`

**Note:** the console `.env` points at **prod**; this smoke is read-only (it renders modes, clicks nothing). That matches the Task-verification norm used for 0014.

- [ ] **Step 2: Manual dialog check against dev (the dialog isn't AppTest-reachable)**

Run the console against dev — override the DSN from the environment so `.env` (prod) is not used:

```bash
DEVDSN="$(python3 - <<'EOF'
import pathlib
for l in pathlib.Path("/home/maikolkali/bitacora/supabase-backend/.env").read_text().splitlines():
    if l.strip().startswith("DATABASE_URL="):
        print(l.split("=",1)[1].strip().strip("'").strip('"')); break
EOF
)"
cd /home/maikolkali/bitacora/catalog-review-app
DATABASE_URL="$DEVDSN" PYTHONPATH="$PYLIB" python3 -m streamlit run app.py --server.headless true
```

Then in the browser (or ask the user to click through) verify, on a dev form's especie field:
1. The «Lista curada» selectbox shows the existing lists (e.g. «especies») and «➕ Nueva lista…».
2. The expander lists the options with importancia; editing an importancia + «Guardar cambios en la lista» persists (reopen to confirm).
3. Searching a species finds it; «Añadir a la lista» adds it; «Quitar» + save removes it (remove the same test row).
4. Choosing «— sin lista —» + «Guardar campo» removes the field's lista (badge «📑 lista …» disappears from the field card); re-attach restores it and its options are intact (detach kept the rows).
5. A newly created «➕ Nueva lista…» shows the empty-list warning.

- [ ] **Step 3: Update the handoff roadmap**

In `handoff.md`, change:

```
**Roadmap remaining:** R3 lists in the Form Builder (drop CSV) · R4 per-user form assignment · R5
Excel bulk import (own deep plan) · R6 automated + on-demand backups.
```

to:

```
**Roadmap remaining:** R4 per-user form assignment · R5 Excel bulk import (own deep plan) · R6
automated + on-demand backups. (R3 lists in the Form Builder shipped 2026-07-07: view/edit/attach
curated lists from the field dialog — `lista_editor.py`; CSV bulk stays in 📑 Listas.)
```

- [ ] **Step 4: Final full test run + commit**

Run: `PYTHONPATH="$PYLIB:." python3 tests/test_lista_editor.py` → `TODOS LOS CHECKS PASAN`
Run the Step 1 smoke again → `SMOKE PASS`

```bash
git add handoff.md
git commit -m "docs: R3 shipped — curated-list editing in the Form Builder"
```

---

## Self-review notes

- **Spec coverage:** view options (Task 2 expander), manual add/create/remove/importancia (Tasks 1–2), attach/detach with reuse-or-create + detach-keeps-rows (Tasks 2–3), approved-only search (Task 1 check 7), two-clocks copy + empty-list warning (Task 2), CSV mode untouched (no task touches `lista_import.py`), audit `_log` on writes (Task 1), friendly errors (Task 2), dev-only round-trip + AppTest smoke + manual dialog check (Tasks 1, 4). No gaps found.
- **Type consistency:** `render_lista_editor(formato_id, tabla, lista_actual, default_name, key) -> str` matches its Task 3 call site; `build_campo`'s `lista_managed`/`lista` keys match the dialog's `v` dict; data-layer signatures in Task 2's UI match Task 1 exactly.
- **Known constraint:** `work["formato_id"]` can be `None` only before Paso 1 completes; `render_lista_editor` handles it with a caption (no crash).
