# R5 — Excel bulk import (Masivos + Bitácoras) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A repeatable ADMINISTRADOR-only console tool that loads *Anexo 2* production
workbooks (Masivos + Bitácoras) into `faena` + children, with fuzzy catalog resolution,
natural-key dedup, and full audit.

**Architecture:** A 4-step Streamlit wizard (`importar` mode) drives three pure/semi-pure
helper modules: `import_formats.py` (declarative specs + parse/group, no DB), `catalog_resolver.py`
(normalize + `difflib` fuzzy + resolve-or-create), `import_writer.py` (dedup by `legacy_id` +
transactional insert). The wizard (`excel_import.py`) is orchestration + UI only.

**Tech Stack:** Python 3.13, Streamlit, psycopg2 (shared autocommit conn via `form_builder`),
openpyxl (already a dep), `difflib` (stdlib). Tests are script-style (`python tests/x.py`, assert +
final `print("TODOS LOS CHECKS PASAN")`), matching the repo's existing tests.

## Global Constraints

- **DB writes/tests are DEV-ONLY.** Every DB-touching test reuses the DSN guard from
  `tests/test_data_admin.py` (`DEV_REF="pxxqumcvkoltbjubyvod"`, assert ref in DSN, else refuse).
  Never write to prod from a test.
- **New catalog entries are created `es_aprobado=false`** — but only for the nine catalogs that
  *have* that column (comunidad, sitio_pesca, especie, pescador, embarcacion, cooperativa, area_pesca,
  zona_pesca, tecnico). `tipo_*` catalogs (arte, anzuelo, operacion, fondo, viento, luna, marea, gasto,
  interaccion_etp) have no `es_aprobado`; the resolver inserts them plain and only when the admin
  explicitly chooses "crear nueva".
- **Especie is matched by the `(nombre_comun, nombre_cientifico)` pair, never común alone** (homonyms).
- **No new pip dependency.** `difflib` is stdlib; `openpyxl` is already used.
- **Every insert writes a `cambio_catalogo` audit row** (`accion='importar'`); `form_builder._log`
  already attributes to the admin (`usuario_id` + `"por"`).
- **ADMINISTRADOR-only:** `registros`-style gating — the mode is *not* in `home.ANALISTA_MODES`.
- Headers are normalized with `.strip()` on read (several real headers carry trailing spaces, e.g.
  `"Dia "`); all specs key on stripped headers.
- Enum values are fixed: `faena.tipo_registro ∈ {MASIVO, BITACORA}`, `carnada.origen ∈ {COMPRADA,
  PESCADA, NA}`.

---

## File Structure

- `catalog-review-app/import_formats.py` — **new.** Declarative `FormatSpec` registry (MASIVOS_LEGACY,
  BITACORA_LEGACY), header-based `detect_format`, `parse_rows`, pure field parsers, `group_faenas`
  → `FaenaDraft`. No DB, no Streamlit.
- `catalog-review-app/catalog_resolver.py` — **new.** `normalize`, `is_na`, pure `best_matches`
  (unit-testable), plus DB-backed `catalog_names`, `resolve_exact`, `fuzzy_suggest`, `resolve_or_create`,
  `desconocido_id`, and especie-pair variants. No Streamlit.
- `catalog-review-app/import_writer.py` — **new.** `natural_key_hash`, `existing_legacy_ids`,
  `commit_batch` (transaction + per-faena savepoint + `legacy_id` + `_log`). No Streamlit.
- `catalog-review-app/excel_import.py` — **new.** `render_excel_import()` — the wizard, session-state
  step machine, mapping UI, preview, report. Plus pure helper `build_mapping_model(...)`.
- `catalog-review-app/home.py` — **edit.** +1 NAV tuple.
- `catalog-review-app/app.py` — **edit.** +1 dispatch block.
- Tests (new): `tests/test_catalog_resolver.py`, `tests/test_import_formats_parse.py`,
  `tests/test_import_formats_group.py`, `tests/test_import_writer.py`, `tests/test_excel_import.py`.

---

## Interfaces (contract the tasks share)

```python
# import_formats.py
@dataclass(frozen=True)
class Target:
    table: str            # 'faena' | 'captura' | 'faena_arte' | 'carnada' | 'interaccion_etp' | 'gasto'
    column: str
    kind: str             # 'text'|'num'|'date'|'hora'|'catalog'|'enum'
    catalog: str | None = None   # cat_* table when kind=='catalog'

@dataclass(frozen=True)
class FormatSpec:
    codigo: str                     # cat_formato_origen.codigo
    tipo_registro: str              # 'MASIVO' | 'BITACORA'
    header_signature: frozenset[str]
    faena_cols: dict[str, Target]   # stripped header -> Target (trip-level → faena)
    catch_cols: dict[str, Target]   # stripped header -> Target (row-level → captura)
    especie_comun: str              # header for captura común
    especie_cientifico: str         # header for captura científico
    key_headers: tuple[str, ...]    # grouping key headers (trip identity)
    children: dict                  # 'carnada'|'etp'|'gasto'|'arte' → sub-specs (see Task 5)

FORMATS: dict[str, FormatSpec]                   # {'MASIVOS_LEGACY':..., 'BITACORA_LEGACY':...}
def detect_format(headers: list[str]) -> str | None
def parse_date(dia, mes, ano) -> datetime.date | None
def parse_num(v) -> float | None
def parse_hora(v) -> str | None                  # 'HH:MM' or None
def parse_rows(headers, data_rows) -> list[dict] # stripped-header→value dicts, drop all-NA rows
@dataclass
class FaenaDraft:
    key: tuple
    faena_raw: dict          # header -> raw value (trip-level)
    catches: list[dict]      # each: {comun, cientifico, kg, categoria, precio}
    children_raw: dict       # {'carnada':{...}, 'etp':[...], 'gasto':[...], 'arte':{...}}
    errors: list[str]
def group_faenas(rows: list[dict], spec: FormatSpec) -> list[FaenaDraft]

# catalog_resolver.py
def normalize(v) -> str
def is_na(v) -> bool
def best_matches(candidates: list[str], value: str, n=3, cutoff=0.82) -> list[tuple[str,float]]
def catalog_names(catalog: str) -> list[dict]            # [{id, name}]
def resolve_exact(catalog: str, value: str) -> str | None
def fuzzy_suggest(catalog: str, value: str) -> list[tuple[str,str,float]]  # (id,name,score)
def resolve_or_create(catalog: str, value: str) -> str   # id
def desconocido_id(catalog: str) -> str
def resolve_especie(comun, cientifico) -> str | None
def fuzzy_especie(comun, cientifico) -> list[tuple[str,str,float]]
def resolve_or_create_especie(comun, cientifico) -> str

# import_writer.py
def natural_key_hash(codigo: str, faena_row_resolved: dict) -> str
def existing_legacy_ids(hashes: list[str]) -> set[str]
def commit_batch(spec, drafts_resolved: list[dict], *, force=False) -> dict  # report
```

---

### Task 1: `importar` nav + dispatch + wizard skeleton

**Files:**
- Create: `catalog-review-app/excel_import.py`
- Modify: `catalog-review-app/home.py` (NAV list ~17-27), `catalog-review-app/app.py` (dispatch ~1196-1207)
- Test: `tests/test_excel_import.py`

**Interfaces — Produces:** `render_excel_import()`; nav mode `"importar"`.

- [ ] **Step 1: Write the failing test** — `tests/test_excel_import.py`

```python
"""Smoke: importar mode gating + wizard skeleton renders."""
import pathlib, sys
BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from home import modes_for                       # noqa: E402

assert "importar" in modes_for("ADMINISTRADOR")
assert "importar" not in modes_for("ANALISTA")
print("TODOS LOS CHECKS PASAN")
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONIOENCODING=utf-8 python tests/test_excel_import.py`
Expected: `AssertionError` (mode not yet in NAV).

- [ ] **Step 3: Add the nav entry** — `home.py`, after the `("registros", …)` tuple:

```python
    ("importar",     "📥 Importar Excel",        "CONFIGURAR"),
```

(Leave `ANALISTA_MODES` unchanged → admin-only.)

- [ ] **Step 4: Add dispatch** — `app.py`, after the `registros` block:

```python
    if mode == "importar":
        from excel_import import render_excel_import
        render_excel_import()
        return
```

- [ ] **Step 5: Create the wizard skeleton** — `excel_import.py`:

```python
"""📥 Importar Excel — bulk load of Anexo 2 production workbooks (R5).

A 4-step wizard (subir → mapear catálogos → previsualizar → confirmar) that loads
Masivos/Bitácoras rows into faena + children. Orchestration + UI only; parsing lives
in import_formats, catalog resolution in catalog_resolver, insertion in import_writer.
"""
from __future__ import annotations
import streamlit as st

STEPS = ["Subir", "Mapear catálogos", "Previsualizar", "Confirmar"]


def _step() -> int:
    return st.session_state.setdefault("imp_step", 0)


def _reset():
    for k in list(st.session_state):
        if k.startswith("imp_"):
            del st.session_state[k]


def render_excel_import():
    from console_ui import page_header
    page_header(
        "📥 Importar Excel",
        "Carga masiva de datos históricos (formatos Masivos y Bitácoras del Anexo 2).",
        help_md=(
            "1. **Sube** el archivo `.xlsx` y confirma el formato detectado.\n"
            "2. **Mapea** los nombres del archivo a los catálogos (acepta o corrige las sugerencias).\n"
            "3. **Previsualiza**: cuántas faenas nuevas, cuáles ya existen, errores.\n"
            "4. **Confirma** para guardar. Los catálogos nuevos quedan sin aprobar, para revisión."
        ),
    )
    st.progress((_step()) / (len(STEPS) - 1), text=f"Paso {_step()+1}/{len(STEPS)}: {STEPS[_step()]}")
    if st.button("↺ Empezar de nuevo", key="imp_restart"):
        _reset(); st.rerun()

    if _step() == 0:
        _step1_upload()
    elif _step() == 1:
        _step2_map()
    elif _step() == 2:
        _step3_preview()
    else:
        _step4_commit()


def _step1_upload():
    st.info("Paso 1 en construcción.")          # replaced in Task 7


def _step2_map():
    st.info("Paso 2 en construcción.")          # replaced in Task 7


def _step3_preview():
    st.info("Paso 3 en construcción.")          # replaced in Task 8


def _step4_commit():
    st.info("Paso 4 en construcción.")          # replaced in Task 8
```

- [ ] **Step 6: Run test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 python tests/test_excel_import.py` → `TODOS LOS CHECKS PASAN`
Also: `python -m py_compile excel_import.py home.py app.py`

- [ ] **Step 7: Commit**

```bash
git add excel_import.py home.py app.py tests/test_excel_import.py
git commit -m "Importar: nav + dispatch + wizard skeleton (R5 Task 1)"
```

---

### Task 2: `catalog_resolver` — pure fuzzy core

**Files:**
- Create: `catalog-review-app/catalog_resolver.py`
- Test: `tests/test_catalog_resolver.py`

**Interfaces — Produces:** `normalize`, `is_na`, `best_matches` (consumed by Tasks 3, 7).

- [ ] **Step 1: Write the failing test** — `tests/test_catalog_resolver.py`

```python
"""Pure unit tests for catalog_resolver (no DB)."""
import pathlib, sys
BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from catalog_resolver import normalize, is_na, best_matches   # noqa: E402

assert normalize("  El   Portugués ") == "El Portugués"
assert normalize(None) == ""
assert is_na("NA") and is_na("nd") and is_na("") and is_na("  Pendiente ") and is_na(None)
assert not is_na("El Portugués")

cands = ["El Portugués", "El Mechudo", "La Reyna Cerralvo"]
# exact-ish near match ranks first, above cutoff
top = best_matches(cands, "El Portugues")     # missing accent
assert top and top[0][0] == "El Portugués"
# no reasonable match → empty
assert best_matches(cands, "Zzzzz Nowhere") == []
print("TODOS LOS CHECKS PASAN")
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONIOENCODING=utf-8 python tests/test_catalog_resolver.py`
Expected: `ModuleNotFoundError: catalog_resolver`.

- [ ] **Step 3: Implement the pure core** — `catalog_resolver.py`:

```python
"""Catalog resolution for the Excel importer: normalize free-text values, fuzzy-match
them against existing cat_* entries (difflib), and resolve-or-create ids. Especie is
matched on the (común, científico) pair — never común alone (homonyms).
"""
from __future__ import annotations
import unicodedata
from difflib import SequenceMatcher, get_close_matches

_NA = {"", "na", "nd", "n/a", "s/n", "sn", "pendiente", "desconocido",
       "sin dato", "sin datos", "none", "null", "-", "."}


def normalize(v) -> str:
    if v is None:
        return ""
    return " ".join(str(v).split()).strip()


def is_na(v) -> bool:
    return normalize(v).casefold() in _NA


def _key(s: str) -> str:
    # accent- and case-insensitive comparison key
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.casefold()


def best_matches(candidates: list[str], value: str, n: int = 3,
                 cutoff: float = 0.82) -> list[tuple[str, float]]:
    """Top-n candidate names similar to `value`, accent/case-insensitive, with scores."""
    v = _key(normalize(value))
    if not v:
        return []
    keyed = {_key(c): c for c in candidates}
    hits = get_close_matches(v, list(keyed), n=n, cutoff=cutoff)
    out = [(keyed[h], SequenceMatcher(None, v, h).ratio()) for h in hits]
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 python tests/test_catalog_resolver.py` → `TODOS LOS CHECKS PASAN`

- [ ] **Step 5: Commit**

```bash
git add catalog_resolver.py tests/test_catalog_resolver.py
git commit -m "Importar: catalog_resolver pure fuzzy core (R5 Task 2)"
```

---

### Task 3: `catalog_resolver` — DB resolve / create / Desconocido / especie

**Files:**
- Modify: `catalog-review-app/catalog_resolver.py`
- Test: `tests/test_catalog_resolver_db.py`

**Interfaces — Consumes:** `best_matches`, `normalize`, `is_na`. **Produces:** `catalog_names`,
`resolve_exact`, `fuzzy_suggest`, `resolve_or_create`, `desconocido_id`, `resolve_especie`,
`fuzzy_especie`, `resolve_or_create_especie` (consumed by Tasks 6, 7, 8).

- [ ] **Step 1: Write the failing test** — `tests/test_catalog_resolver_db.py`

```python
"""Dev-only: catalog_resolver DB resolve/create/Desconocido/especie. Guarded DSN, cleans up."""
import os, pathlib, sys, uuid
BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
DEV_REF = "pxxqumcvkoltbjubyvod"
for envf in (BASE.parent/"supabase-backend"/".env", BASE.parent/"Planning"/"supabase"/".env"):
    if envf.exists():
        for line in envf.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("DATABASE_URL="):
                os.environ["DATABASE_URL"] = line.split("=",1)[1].strip().strip("'\"")
assert DEV_REF in os.environ.get("DATABASE_URL",""), "solo DEV"
import streamlit as st                                  # noqa: E402
st.session_state = {"auth_nombre": "ZZ Import Test"}    # attribute _log
from form_builder import _q, _exec                      # noqa: E402
import catalog_resolver as R                            # noqa: E402

TAG = uuid.uuid4().hex[:8].upper()
NEW = f"ZZ Sitio {TAG}"
created = []
def cleanup():
    _exec("DELETE FROM cat_sitio_pesca WHERE nombre LIKE %s", (f"ZZ Sitio {TAG}%",))
    _exec("DELETE FROM cat_sitio_pesca WHERE nombre='Desconocido' AND id=ANY(%s)", (created or [None],))
    _exec("DELETE FROM cat_especie WHERE nombre_comun LIKE %s", (f"ZZ Esp {TAG}%",))
try:
    # exact match on an existing row
    some = _q("SELECT nombre FROM cat_sitio_pesca WHERE es_aprobado LIMIT 1")
    if some:
        assert R.resolve_exact("cat_sitio_pesca", some[0]["nombre"]) is not None
    # create-or-resolve a brand new value → creates es_aprobado=false
    sid = R.resolve_or_create("cat_sitio_pesca", NEW)
    row = _q("SELECT nombre, es_aprobado FROM cat_sitio_pesca WHERE id=%s", (sid,))[0]
    assert row["nombre"] == NEW and row["es_aprobado"] is False
    assert R.resolve_or_create("cat_sitio_pesca", NEW) == sid          # idempotent
    # desconocido placeholder
    dsc = R.desconocido_id("cat_sitio_pesca"); created.append(dsc)
    assert R.desconocido_id("cat_sitio_pesca") == dsc                  # reused
    # especie pair: same común, different científico → two distinct ids (homonyms)
    a = R.resolve_or_create_especie(f"ZZ Esp {TAG}", "Genus alpha")
    b = R.resolve_or_create_especie(f"ZZ Esp {TAG}", "Genus beta")
    assert a != b
    assert R.resolve_especie(f"ZZ Esp {TAG}", "Genus alpha") == a
    print("TODOS LOS CHECKS PASAN")
finally:
    cleanup()
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONIOENCODING=utf-8 python tests/test_catalog_resolver_db.py`
Expected: `AttributeError`/`ImportError` (functions not defined).

- [ ] **Step 3: Implement the DB layer** — append to `catalog_resolver.py`:

```python
from form_builder import _q, _exec, _log

# catalogs that carry es_aprobado (created entries flagged unapproved)
_APPROVABLE = {"cat_comunidad", "cat_sitio_pesca", "cat_especie", "cat_pescador",
               "cat_embarcacion", "cat_cooperativa", "cat_area_pesca", "cat_zona_pesca",
               "cat_tecnico"}
_NAMECOL = {"cat_especie": "nombre_comun"}   # else 'nombre'


def _namecol(catalog: str) -> str:
    return _NAMECOL.get(catalog, "nombre")


def catalog_names(catalog: str) -> list[dict]:
    nc = _namecol(catalog)
    return _q(f'SELECT id::text AS id, {nc} AS name FROM public."{catalog}" '
              f'WHERE {nc} IS NOT NULL')


def _index(catalog: str) -> dict[str, str]:
    return {_key(normalize(r["name"])): r["id"] for r in catalog_names(catalog)}


def resolve_exact(catalog: str, value: str) -> str | None:
    if is_na(value):
        return None
    return _index(catalog).get(_key(normalize(value)))


def fuzzy_suggest(catalog: str, value: str) -> list[tuple[str, str, float]]:
    names = [r["name"] for r in catalog_names(catalog)]
    idx = {r["name"]: r["id"] for r in catalog_names(catalog)}
    return [(idx[n], n, sc) for n, sc in best_matches(names, value)]


def _insert(catalog: str, cols: dict) -> str:
    if catalog in _APPROVABLE:
        cols = {**cols, "es_aprobado": False}
    keys = ", ".join(f'"{k}"' for k in cols)
    ph = ", ".join(["%s"] * len(cols))
    rid = _q(f'INSERT INTO public."{catalog}" ({keys}) VALUES ({ph}) RETURNING id::text AS id',
             list(cols.values()))[0]["id"]
    _log(catalog, rid, "importar", {"creado": cols})
    return rid


def resolve_or_create(catalog: str, value: str) -> str:
    if is_na(value):
        return desconocido_id(catalog)
    hit = resolve_exact(catalog, value)
    return hit if hit else _insert(catalog, {_namecol(catalog): normalize(value)})


def desconocido_id(catalog: str) -> str:
    hit = resolve_exact(catalog, "Desconocido")
    return hit if hit else _insert(catalog, {_namecol(catalog): "Desconocido"})


# --- especie (pair-keyed) ---
def _especie_index() -> dict[tuple[str, str], str]:
    rows = _q("SELECT id::text AS id, nombre_comun, nombre_cientifico FROM cat_especie")
    return {(_key(normalize(r["nombre_comun"])), _key(normalize(r["nombre_cientifico"]))): r["id"]
            for r in rows}


def resolve_especie(comun, cientifico) -> str | None:
    if is_na(comun) and is_na(cientifico):
        return None
    c = "" if is_na(cientifico) else _key(normalize(cientifico))
    return _especie_index().get((_key(normalize(comun)), c))


def fuzzy_especie(comun, cientifico) -> list[tuple[str, str, float]]:
    # suggest on común (display "común — científico"); admin disambiguates científico
    rows = _q("SELECT id::text AS id, nombre_comun, nombre_cientifico FROM cat_especie")
    disp = {f'{r["nombre_comun"]} — {r["nombre_cientifico"] or "?"}': r["id"] for r in rows}
    names = [r["nombre_comun"] for r in rows]
    byname = {r["nombre_comun"]: r for r in rows}
    out = []
    for n, sc in best_matches(names, comun, n=5, cutoff=0.8):
        r = byname[n]
        out.append((r["id"], f'{r["nombre_comun"]} — {r["nombre_cientifico"] or "?"}', sc))
    return out


def resolve_or_create_especie(comun, cientifico) -> str:
    if is_na(comun) and is_na(cientifico):
        return desconocido_especie_id()
    hit = resolve_especie(comun, cientifico)
    if hit:
        return hit
    cols = {"nombre_comun": normalize(comun) or "Desconocido",
            "nombre_cientifico": None if is_na(cientifico) else normalize(cientifico),
            "es_aprobado": False}
    return _insert_especie(cols)


def _insert_especie(cols: dict) -> str:
    keys = ", ".join(f'"{k}"' for k in cols)
    ph = ", ".join(["%s"] * len(cols))
    rid = _q(f'INSERT INTO cat_especie ({keys}) VALUES ({ph}) RETURNING id::text AS id',
             list(cols.values()))[0]["id"]
    _log("cat_especie", rid, "importar", {"creado": cols})
    return rid


def desconocido_especie_id() -> str:
    hit = resolve_especie("Desconocido", "NA")
    return hit if hit else _insert_especie(
        {"nombre_comun": "Desconocido", "nombre_cientifico": None, "es_aprobado": False})
```

Note: `_insert` builds `es_aprobado` in for approvable catalogs; `_insert_especie` sets it directly.
The `_index`/`_especie_index` helpers query fresh each call (autocommit conn); acceptable for import
volumes. (A per-run cache can be added in Task 7 if the mapping UI feels slow.)

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 python tests/test_catalog_resolver_db.py` → `TODOS LOS CHECKS PASAN`

- [ ] **Step 5: Commit**

```bash
git add catalog_resolver.py tests/test_catalog_resolver_db.py
git commit -m "Importar: catalog_resolver DB resolve/create/especie (R5 Task 3)"
```

---

### Task 4: `import_formats` — specs, detect, parsers, parse_rows

**Files:**
- Create: `catalog-review-app/import_formats.py`
- Test: `tests/test_import_formats_parse.py`

**Interfaces — Produces:** `Target`, `FormatSpec`, `FORMATS`, `detect_format`, `parse_date`,
`parse_num`, `parse_hora`, `parse_rows` (consumed by Tasks 5, 7, 8).

- [ ] **Step 1: Write the failing test** — `tests/test_import_formats_parse.py`

```python
import datetime, pathlib, sys
BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
import import_formats as F                              # noqa: E402

assert F.parse_date(13, 8, 2009) == datetime.date(2009, 8, 13)
assert F.parse_date("NA", 8, 2009) is None
assert F.parse_num("2.7") == 2.7 and F.parse_num("NA") is None
assert F.parse_hora("7:30") == "07:30" and F.parse_hora("NA") is None

masivos_headers = list(F.FORMATS["MASIVOS_LEGACY"].header_signature)[:5] + \
    ["ID","Num.Formato","Comunidad/ Sitio de arribo","Lugar/ Sitio de pesca","Nombre comun","Captura (kg)"]
assert F.detect_format(["ID","Num.Formato","Tecnico","Dia ","Mes ","Año",
                        "Comunidad/ Sitio de arribo","Lugar/ Sitio de pesca","Nombre comun",
                        "Captura (kg)","Otros gastos"]) in ("MASIVOS_LEGACY","BITACORA_LEGACY")

rows = F.parse_rows(["Dia ", "Nombre comun", "Captura (kg)"],
                    [(13, "Cochito", 50), ("NA", "NA", "NA")])
assert rows == [{"Dia": 13, "Nombre comun": "Cochito", "Captura (kg)": 50}]   # all-NA row dropped, headers stripped
print("TODOS LOS CHECKS PASAN")
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONIOENCODING=utf-8 python tests/test_import_formats_parse.py`
Expected: `ModuleNotFoundError: import_formats`.

- [ ] **Step 3: Implement** — `import_formats.py`. Full field parsers + both specs. Use the column
maps below verbatim (stripped headers). BITACORA shares MASIVOS' body; it just lacks the
`ID/Num.Formato/Tecnico` lead columns and has a slightly different gasto tail — express it as
`_BASE_*` dicts reused by both.

```python
"""Declarative Anexo-2 production format specs (Masivos, Bitácoras) + pure parsing/grouping.
No DB, no Streamlit — safe to unit test."""
from __future__ import annotations
import datetime
from dataclasses import dataclass, field

from catalog_resolver import is_na, normalize   # reuse NA logic


@dataclass(frozen=True)
class Target:
    table: str
    column: str
    kind: str                 # text|num|date|hora|catalog|enum
    catalog: str | None = None


@dataclass(frozen=True)
class FormatSpec:
    codigo: str
    tipo_registro: str
    header_signature: frozenset
    faena_cols: dict
    catch_cols: dict
    especie_comun: str
    especie_cientifico: str
    key_headers: tuple
    children: dict = field(default_factory=dict)


# ---- parsers ----
def parse_num(v):
    if is_na(v):
        return None
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return None


def parse_date(dia, mes, ano):
    try:
        d, m, y = int(dia), int(mes), int(ano)
        return datetime.date(y, m, d)
    except (ValueError, TypeError):
        return None


def parse_hora(v):
    if is_na(v):
        return None
    s = normalize(v)
    if isinstance(v, datetime.time):
        return v.strftime("%H:%M")
    for sep in (":", "."):
        if sep in s:
            hh, _, mm = s.partition(sep)
            try:
                return f"{int(hh):02d}:{int(mm or 0):02d}"
            except ValueError:
                return None
    return None


def _strip(h):
    return normalize(h)


def parse_rows(headers, data_rows):
    hs = [_strip(h) for h in headers]
    out = []
    for r in data_rows:
        d = {hs[i]: r[i] for i in range(len(hs)) if hs[i]}
        if all(is_na(v) for v in d.values()):
            continue
        out.append(d)
    return out


def detect_format(headers):
    hs = {_strip(h) for h in headers if _strip(h)}
    best, score = None, 0.0
    for code, spec in FORMATS.items():
        sig = spec.header_signature
        j = len(hs & sig) / len(hs | sig) if (hs | sig) else 0
        if j > score:
            best, score = code, j
    return best if score >= 0.4 else None


# ---- shared faena/catch/child column maps (stripped headers) ----
_FAENA = {
    "Comunidad/ Sitio de arribo": Target("faena", "comunidad_id", "catalog", "cat_comunidad"),
    "Lugar/ Sitio de pesca":      Target("faena", "sitio_pesca_id", "catalog", "cat_sitio_pesca"),
    "Area de Pesca":              Target("faena", "area_pesca_id", "catalog", "cat_area_pesca"),
    "Zona de pesca":              Target("faena", "zona_pesca_id", "catalog", "cat_zona_pesca"),
    "Pescador":                   Target("faena", "capitan_id", "catalog", "cat_pescador"),
    "Embarcacion":                Target("faena", "embarcacion_id", "catalog", "cat_embarcacion"),
    "Cooperativa":                Target("faena", "cooperativa_id", "catalog", "cat_cooperativa"),
    "Num de pescadores":          Target("faena", "num_pescadores", "num"),
    "Gasolina (lts)":             Target("faena", "gasolina_lts", "num"),
    "Encargado del lugar":        Target("faena", "encargado_lugar", "text"),
    "Motor (hp)":                 Target("faena", "motor_hp", "num"),
    "Hora de salida":             Target("faena", "hora_salida", "hora"),
    "Hora de llegada":            Target("faena", "hora_llegada", "hora"),
    "Horas de pesca (h/min)":     Target("faena", "tiempo_efectivo_pesca_h", "num"),
    "profund_min":                Target("faena", "profundidad_min_brazas", "num"),
    "profund_max":                Target("faena", "profundidad_max_brazas", "num"),
    "Tipo de fondo":              Target("faena", "tipo_fondo_id", "catalog", "cat_tipo_fondo"),
    "Viento":                     Target("faena", "viento_id", "catalog", "cat_tipo_viento"),
    "Luna":                       Target("faena", "luna_id", "catalog", "cat_tipo_luna"),
    "Marea":                      Target("faena", "marea_id", "catalog", "cat_tipo_marea"),
    "Latitud":                    Target("faena", "latitud_legacy", "text"),
    "Longitud":                   Target("faena", "longitud_legacy", "text"),
    "Observaciones/ Pescador":    Target("faena", "observaciones", "text"),
}
_CATCH = {
    "Categoria por tamaño": Target("captura", "categoria_tamano", "text"),
    "Captura (kg)":         Target("captura", "captura_kg", "num"),
    "Precio":               Target("captura", "precio_kg", "num"),
}
# child sub-specs (headers → target columns); resolution/skip logic in Task 5 group_faenas
_CHILDREN = {
    "arte": {"tipo_arte_id": ("Arte de pesca", "cat_tipo_arte"),
             "tipo_anzuelo_id": ("Tipo de anzuelo", "cat_tipo_anzuelo"),
             "tipo_operacion_id": ("Operacion", "cat_tipo_operacion"),
             "metodo": ("Metodo/Caida", None), "material": ("Anzuelos trabajando/Material", None)},
    "carnada": {"origen": ("Comprada o pescada", None),
                "comun": ("Nombre comun carnada", None), "cientifico": ("Nombre cientifico carnada", None),
                "sitio_pesca_carnada_id": ("Sitio de pesca de la carnada", "cat_sitio_pesca"),
                "kg_aprox": ("Kg (aprox/ carnada)", None),
                "arte_pesca_id": ("Arte de pesca carnada", "cat_tipo_arte")},
    "etp": [("Especie", "Interacción"), ("Especie 2", "Interacción 2")],
    "gasto": {  # gasto tipo (cat_tipo_gasto name) : (cantidad header, monto header)
        "Gasolina": ("Gasolina (lts)", "$ gasolina"), "Anzuelos": ("anzuelos", "$anzuelos"),
        "Destorcedores": ("Destorcedores", "$ destorcedores"), "Plomadas": ("plomada", "$plomadas"),
        "Piola": ("piola", "$ piola")},
}

_MASIVOS = FormatSpec(
    codigo="MASIVOS_LEGACY", tipo_registro="MASIVO",
    header_signature=frozenset({*_FAENA, *_CATCH, "ID", "Num.Formato", "Tecnico", "Dia", "Mes",
                                "Año", "Nombre comun", "Nombre cientifico", "Otros gastos"}),
    faena_cols={**_FAENA, "Tecnico": Target("faena", "tecnico_id", "catalog", "cat_tecnico"),
                "Num.Formato": Target("faena", "codigo_formato", "text")},
    catch_cols=_CATCH, especie_comun="Nombre comun", especie_cientifico="Nombre cientifico",
    key_headers=("Dia", "Mes", "Año", "Comunidad/ Sitio de arribo", "Lugar/ Sitio de pesca",
                 "Pescador", "Embarcacion", "Tecnico"),
    children=_CHILDREN)

_BITACORA = FormatSpec(
    codigo="BITACORA_LEGACY", tipo_registro="BITACORA",
    header_signature=frozenset({*_FAENA, *_CATCH, "Dia", "Mes", "Año", "Nombre comun",
                                "Nombre cientifico", "Datos capturados por", "Cantidad de aceite"}),
    faena_cols={**_FAENA,
                "Datos capturados por": Target("faena", "tecnico_id", "catalog", "cat_tecnico")},
    catch_cols=_CATCH, especie_comun="Nombre comun", especie_cientifico="Nombre cientifico",
    key_headers=("Dia", "Mes", "Año", "Comunidad/ Sitio de arribo", "Lugar/ Sitio de pesca",
                 "Pescador", "Embarcacion", "Datos capturados por"),
    children=_CHILDREN)

FORMATS = {"MASIVOS_LEGACY": _MASIVOS, "BITACORA_LEGACY": _BITACORA}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 python tests/test_import_formats_parse.py` → `TODOS LOS CHECKS PASAN`

- [ ] **Step 5: Commit**

```bash
git add import_formats.py tests/test_import_formats_parse.py
git commit -m "Importar: import_formats specs + parsers + detect (R5 Task 4)"
```

---

### Task 5: `import_formats` — `group_faenas` → `FaenaDraft`

**Files:**
- Modify: `catalog-review-app/import_formats.py`
- Test: `tests/test_import_formats_group.py`

**Interfaces — Consumes:** `FormatSpec`, parsers. **Produces:** `FaenaDraft`, `group_faenas`
(consumed by Tasks 7, 8).

- [ ] **Step 1: Write the failing test** — `tests/test_import_formats_group.py`

```python
import pathlib, sys
BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
import import_formats as F                              # noqa: E402

spec = F.FORMATS["MASIVOS_LEGACY"]
def row(comun, kg, **kw):
    base = {"Dia": 13, "Mes": 8, "Año": 2009, "Comunidad/ Sitio de arribo": "Punta Coyote",
            "Lugar/ Sitio de pesca": "El Mechudo", "Pescador": "Playa Camarón I",
            "Embarcacion": "NA", "Tecnico": "NA", "Nombre comun": comun, "Captura (kg)": kg}
    base.update(kw); return base

rows = [row("Cochito", 50), row("Mojarra", 6), row("Burro", "NA")]   # 3rd has no kg
drafts = F.group_faenas(rows, spec)
assert len(drafts) == 1                              # one trip
d = drafts[0]
assert len(d.catches) == 2                           # kg-less catch dropped
assert any("Captura (kg)" in e or "kg" in e for e in d.errors)   # and reported
assert d.faena_raw["tiempo_efectivo_pesca_h"] in (0, 0.0)        # NA hours → 0 w/ warning
assert any("tiempo" in e.lower() for e in d.errors)

# boat-fallback: same day/site, NA pescador, two boats → two faenas
r2 = [row("X", 1, Pescador="NA", Embarcacion="Albatros II"),
      row("Y", 2, Pescador="NA", Embarcacion="Naydeli")]
assert len(F.group_faenas(r2, spec)) == 2

# unparseable date → faena flagged, no catches emitted for insert
bad = F.group_faenas([row("Z", 1, Dia="NA")], spec)
assert bad and bad[0].errors and bad[0].key is None
print("TODOS LOS CHECKS PASAN")
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONIOENCODING=utf-8 python tests/test_import_formats_group.py`
Expected: `AttributeError: group_faenas`.

- [ ] **Step 3: Implement** — append to `import_formats.py`:

```python
from dataclasses import dataclass as _dc

@_dc
class FaenaDraft:
    key: tuple | None
    faena_raw: dict
    catches: list
    children_raw: dict
    errors: list


def _faena_fields(row, spec):
    """Map trip-level raw row → {faena_column: raw_or_parsed_value} (pre-catalog)."""
    out, errors = {}, []
    for header, t in spec.faena_cols.items():
        v = row.get(header)
        if t.kind == "num":
            out[t.column] = parse_num(v)
        elif t.kind == "hora":
            out[t.column] = parse_hora(v)
        elif t.kind == "catalog":
            out[t.column] = ("catalog", t.catalog, v)      # resolved later
        else:
            out[t.column] = None if is_na(v) else normalize(v)
    # fecha
    out["fecha"] = parse_date(row.get("Dia"), row.get("Mes"), row.get("Año"))
    # required hours default
    if not out.get("tiempo_efectivo_pesca_h"):
        out["tiempo_efectivo_pesca_h"] = 0
        errors.append("tiempo de pesca desconocido → 0 (revisar)")
    out["tipo_registro"] = spec.tipo_registro
    return out, errors


def _catch(row, spec):
    kg = parse_num(row.get("Captura (kg)"))
    if kg is None:
        return None
    return {"comun": row.get(spec.especie_comun), "cientifico": row.get(spec.especie_cientifico),
            "captura_kg": kg,
            "categoria_tamano": None if is_na(row.get("Categoria por tamaño"))
            else normalize(row.get("Categoria por tamaño")),
            "precio_kg": parse_num(row.get("Precio"))}


def _key(row, spec):
    return tuple(normalize(row.get(h)) for h in spec.key_headers)


def group_faenas(rows, spec):
    order, buckets = [], {}
    for row in rows:
        k = _key(row, spec)
        if k not in buckets:
            buckets[k] = []; order.append(k)
        buckets[k].append(row)
    drafts = []
    for k in order:
        group = buckets[k]
        faena_raw, errors = _faena_fields(group[0], spec)
        valid_key = k if faena_raw.get("fecha") else None
        if faena_raw.get("fecha") is None:
            errors.append("fecha inválida (Día/Mes/Año) — faena omitida")
        catches = []
        for row in group:
            c = _catch(row, spec)
            if c is None:
                errors.append(f"captura sin kg omitida: {normalize(row.get(spec.especie_comun))}")
            else:
                catches.append(c)
        children_raw = _children(group[0], spec)      # trip-level children from first row
        drafts.append(FaenaDraft(valid_key, faena_raw, catches, children_raw, errors))
    return drafts


def _children(row, spec):
    ch = spec.children
    out = {"arte": {}, "carnada": {}, "etp": [], "gasto": []}
    for col, (header, cat) in ch["arte"].items():
        v = row.get(header)
        out["arte"][col] = ("catalog", cat, v) if cat else (None if is_na(v) else normalize(v))
    if not is_na(row.get(ch["carnada"]["comun"][0])) or not is_na(row.get(ch["carnada"]["origen"][0])):
        for col, (header, cat) in ch["carnada"].items():
            v = row.get(header)
            out["carnada"][col] = ("catalog", cat, v) if cat else (None if is_na(v) else normalize(v))
    for esp_h, int_h in ch["etp"]:
        if not is_na(row.get(esp_h)):
            out["etp"].append({"comun": row.get(esp_h), "interaccion": row.get(int_h)})
    for tipo, (cant_h, monto_h) in ch["gasto"].items():
        monto = parse_num(row.get(monto_h))
        if monto is not None:
            out["gasto"].append({"tipo": tipo, "cantidad": parse_num(row.get(cant_h)),
                                 "monto_total": monto})
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 python tests/test_import_formats_group.py` → `TODOS LOS CHECKS PASAN`

- [ ] **Step 5: Commit**

```bash
git add import_formats.py tests/test_import_formats_group.py
git commit -m "Importar: group_faenas → FaenaDraft (R5 Task 5)"
```

---

### Task 6: `import_writer` — dedup + transactional insert

**Files:**
- Create: `catalog-review-app/import_writer.py`
- Test: `tests/test_import_writer.py`

**Interfaces — Consumes:** `catalog_resolver`, `import_formats`. **Produces:** `natural_key_hash`,
`existing_legacy_ids`, `resolve_draft`, `commit_batch` (consumed by Task 8).

- [ ] **Step 1: Write the failing test** — `tests/test_import_writer.py` (guarded DEV DSN, throwaway
data via the resolver; asserts faena+captura inserted with `legacy_id`, audit rows attributed, and a
**re-run skips** the same faena; cleans up all rows it created by `legacy_id` prefix).

```python
"""Dev-only round-trip for import_writer: resolve a fixture draft → commit → re-commit skips."""
import os, pathlib, sys, uuid
BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
DEV_REF = "pxxqumcvkoltbjubyvod"
for envf in (BASE.parent/"supabase-backend"/".env", BASE.parent/"Planning"/"supabase"/".env"):
    if envf.exists():
        for line in envf.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("DATABASE_URL="):
                os.environ["DATABASE_URL"] = line.split("=",1)[1].strip().strip("'\"")
assert DEV_REF in os.environ.get("DATABASE_URL",""), "solo DEV"
import streamlit as st                                  # noqa: E402
st.session_state = {"auth_nombre": "ZZ Import Writer"}
from form_builder import _q, _exec                      # noqa: E402
import import_formats as F, import_writer as W          # noqa: E402

TAG = "ZZW" + uuid.uuid4().hex[:6]
spec = F.FORMATS["MASIVOS_LEGACY"]
def row(comun, kg):
    return {"Dia":13,"Mes":8,"Año":2009,"Comunidad/ Sitio de arribo":f"{TAG} Comunidad",
            "Lugar/ Sitio de pesca":f"{TAG} Sitio","Pescador":f"{TAG} Pescador","Embarcacion":"NA",
            "Tecnico":f"{TAG} Tecnico","Nombre comun":comun,"Captura (kg)":kg,
            "Horas de pesca (h/min)":3}
drafts = F.group_faenas([row("Cochito",50), row("Mojarra",6)], spec)

def created_faenas():
    return _q("SELECT id::text AS id FROM faena WHERE legacy_id LIKE %s", (f"{spec.codigo}:%",))
def cleanup():
    ids=[r["id"] for r in _q("SELECT id::text AS id FROM faena f "
         "JOIN cat_sitio_pesca s ON s.id=f.sitio_pesca_id WHERE s.nombre=%s",(f"{TAG} Sitio",))]
    for t in ("captura","carnada","interaccion_etp","gasto","faena_arte"):
        _exec(f"DELETE FROM {t} WHERE faena_id=ANY(%s)", (ids or [None],))
    _exec("DELETE FROM cambio_catalogo WHERE registro_id=ANY(%s)", (ids or [None],))
    _exec("DELETE FROM faena WHERE id=ANY(%s)", (ids or [None],))
    for c,val in (("cat_comunidad",f"{TAG} Comunidad"),("cat_sitio_pesca",f"{TAG} Sitio"),
                  ("cat_pescador",f"{TAG} Pescador"),("cat_tecnico",f"{TAG} Tecnico")):
        _exec(f"DELETE FROM {c} WHERE nombre=%s",(val,))
    _exec("DELETE FROM cat_especie WHERE nombre_comun IN ('Cochito','Mojarra') AND es_aprobado=false "
          "AND NOT EXISTS (SELECT 1 FROM captura c WHERE c.especie_id=cat_especie.id)")
try:
    cleanup()
    resolved = [W.resolve_draft(spec, d) for d in drafts]
    rep = W.commit_batch(spec, resolved)
    assert rep["faenas_nuevas"] == 1 and rep["capturas"] == 2, rep
    fa = _q("SELECT legacy_id, tipo_registro::text AS tr FROM faena f "
            "JOIN cat_sitio_pesca s ON s.id=f.sitio_pesca_id WHERE s.nombre=%s",(f"{TAG} Sitio",))
    assert fa and fa[0]["legacy_id"].startswith(spec.codigo+":") and fa[0]["tr"]=="MASIVO"
    # re-commit → skipped as duplicate
    resolved2 = [W.resolve_draft(spec, d) for d in F.group_faenas([row("Cochito",50)], spec)]
    rep2 = W.commit_batch(spec, resolved2)
    assert rep2["faenas_nuevas"]==0 and rep2["ya_existen"]==1, rep2
    print("TODOS LOS CHECKS PASAN")
finally:
    cleanup()
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONIOENCODING=utf-8 python tests/test_import_writer.py`
Expected: `ModuleNotFoundError: import_writer`.

- [ ] **Step 3: Implement** — `import_writer.py`:

```python
"""Dedup + transactional insert for the Excel importer. Resolves a FaenaDraft's catalog
placeholders to ids, computes a natural-key legacy_id for idempotency, and commits a batch
with a per-faena SAVEPOINT so one bad faena doesn't sink the rest."""
from __future__ import annotations
import hashlib
import uuid

from form_builder import get_conn, _q, _log
import catalog_resolver as R


def _resolve_cell(v):
    """('catalog', cat, raw) → id (resolve/create); else pass-through."""
    if isinstance(v, tuple) and len(v) == 3 and v[0] == "catalog":
        _, cat, raw = v
        return R.resolve_or_create(cat, raw)
    return v


def resolve_draft(spec, draft):
    """FaenaDraft → {faena, catches, arte, carnada, etp, gasto, errors, key} with ids resolved."""
    faena = {k: _resolve_cell(v) for k, v in draft.faena_raw.items()}
    faena["legacy_id"] = natural_key_hash(spec.codigo, faena)
    catches = [{"especie_id": R.resolve_or_create_especie(c["comun"], c["cientifico"]),
                "captura_kg": c["captura_kg"], "categoria_tamano": c["categoria_tamano"],
                "precio_kg": c["precio_kg"]} for c in draft.catches]
    arte = {k: _resolve_cell(v) for k, v in draft.children_raw["arte"].items()}
    carn = draft.children_raw["carnada"]
    carnada = None
    if carn:
        carnada = {"origen": _origen(carn.get("origen")),
                   "especie_id": R.resolve_or_create_especie(carn.get("comun"), carn.get("cientifico")),
                   "sitio_pesca_carnada_id": _resolve_cell(carn.get("sitio_pesca_carnada_id")),
                   "kg_aprox": _num(carn.get("kg_aprox")), "arte_pesca_id": _resolve_cell(carn.get("arte_pesca_id"))}
    etp = [{"especie_id": R.resolve_or_create("cat_especie", e["comun"]) if False else
            R.resolve_or_create_especie(e["comun"], "NA"),
            "tipo_interaccion_id": R.resolve_or_create("cat_tipo_interaccion_etp", e["interaccion"])}
           for e in draft.children_raw["etp"]]
    gasto = [{"tipo_gasto_id": R.resolve_or_create("cat_tipo_gasto", g["tipo"]),
              "cantidad": g["cantidad"], "monto_total": g["monto_total"]}
             for g in draft.children_raw["gasto"]]
    return {"key": draft.key, "faena": faena, "catches": catches, "arte": arte,
            "carnada": carnada, "etp": etp, "gasto": gasto, "errors": list(draft.errors)}


def _origen(v):
    m = R.normalize(v).casefold()
    if m.startswith("compr"): return "COMPRADA"
    if m.startswith("pesc"):  return "PESCADA"
    return "NA"


def _num(v):
    try: return float(v)
    except (TypeError, ValueError): return None


def natural_key_hash(codigo, faena_resolved):
    parts = [codigo, str(faena_resolved.get("fecha")), str(faena_resolved.get("comunidad_id")),
             str(faena_resolved.get("sitio_pesca_id")), str(faena_resolved.get("capitan_id")),
             str(faena_resolved.get("embarcacion_id")), str(faena_resolved.get("tecnico_id"))]
    return codigo + ":" + hashlib.sha1("|".join(parts).encode()).hexdigest()[:24]


def existing_legacy_ids(hashes):
    if not hashes:
        return set()
    rows = _q("SELECT legacy_id FROM faena WHERE legacy_id = ANY(%s)", (list(hashes),))
    return {r["legacy_id"] for r in rows}


_FAENA_COLS = ("legacy_id", "codigo_formato", "formato_origen_id", "tipo_registro", "fecha",
               "comunidad_id", "sitio_pesca_id", "area_pesca_id", "zona_pesca_id", "embarcacion_id",
               "cooperativa_id", "capitan_id", "tecnico_id", "encargado_lugar", "num_pescadores",
               "gasolina_lts", "motor_hp", "tiempo_efectivo_pesca_h", "profundidad_min_brazas",
               "profundidad_max_brazas", "tipo_fondo_id", "viento_id", "luna_id", "marea_id",
               "latitud_legacy", "longitud_legacy", "hora_salida", "hora_llegada", "observaciones")


def _formato_id(codigo):
    return _q("SELECT id::text AS id FROM cat_formato_origen WHERE codigo=%s", (codigo,))[0]["id"]


def _ins(cur, table, cols: dict):
    rid = str(uuid.uuid4())
    cols = {"id": rid, **cols}
    keys = ", ".join(f'"{k}"' for k in cols)
    ph = ", ".join(["%s"] * len(cols))
    cur.execute(f'INSERT INTO public."{table}" ({keys}) VALUES ({ph})', list(cols.values()))
    return rid


def commit_batch(spec, resolved, *, force=False):
    formato_id = _formato_id(spec.codigo)
    hashes = [r["faena"]["legacy_id"] for r in resolved if r["key"]]
    dup = set() if force else existing_legacy_ids(hashes)
    rep = {"faenas_nuevas": 0, "ya_existen": 0, "capturas": 0, "faenas_error": 0, "errores": []}
    conn = get_conn()
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            for r in resolved:
                if r["key"] is None:
                    rep["faenas_error"] += 1; rep["errores"] += r["errors"]; continue
                if r["faena"]["legacy_id"] in dup:
                    rep["ya_existen"] += 1; continue
                cur.execute("SAVEPOINT sp")
                try:
                    f = {k: r["faena"].get(k) for k in _FAENA_COLS}
                    f["formato_origen_id"] = formato_id
                    fid = _ins(cur, "faena", f)
                    for c in r["catches"]:
                        _ins(cur, "captura", {"faena_id": fid, **c}); rep["capturas"] += 1
                    if any(v is not None for v in r["arte"].values()):
                        _ins(cur, "faena_arte", {"faena_id": fid, **{k: v for k, v in r["arte"].items() if v is not None}})
                    if r["carnada"]:
                        _ins(cur, "carnada", {"faena_id": fid, **{k: v for k, v in r["carnada"].items() if v is not None},
                                              "kg_aprox": r["carnada"].get("kg_aprox") or 0})
                    for e in r["etp"]:
                        _ins(cur, "interaccion_etp", {"faena_id": fid, **e})
                    for g in r["gasto"]:
                        _ins(cur, "gasto", {"faena_id": fid, **g})
                    cur.execute("RELEASE SAVEPOINT sp")
                    _log("faena", fid, "importar", {"legacy_id": f["legacy_id"], "capturas": len(r["catches"])})
                    rep["faenas_nuevas"] += 1
                except Exception as e:      # noqa: BLE001
                    cur.execute("ROLLBACK TO SAVEPOINT sp")
                    rep["faenas_error"] += 1; rep["errores"].append(str(e))
        conn.commit()
    except Exception:
        conn.rollback(); raise
    finally:
        conn.autocommit = True
    return rep
```

Note: `_log` uses `_exec` on the same (now non-autocommit) connection, so audit rows commit atomically
with the batch — call it after `RELEASE SAVEPOINT` as shown.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 python tests/test_import_writer.py` → `TODOS LOS CHECKS PASAN`

- [ ] **Step 5: Commit**

```bash
git add import_writer.py tests/test_import_writer.py
git commit -m "Importar: import_writer dedup + transactional insert (R5 Task 6)"
```

---

### Task 7: Wizard Steps 1–2 (upload/detect + catalog mapping)

**Files:**
- Modify: `catalog-review-app/excel_import.py`
- Test: `tests/test_excel_import.py` (extend with a pure `build_mapping_model` unit test)

**Interfaces — Consumes:** `import_formats`, `catalog_resolver`. **Produces:**
`build_mapping_model(drafts, spec) -> dict`; session keys `imp_wb`, `imp_format`, `imp_rows`,
`imp_map` (`{(catalog, raw): id}`).

- [ ] **Step 1: Add failing unit test** for the pure mapping-model builder — append to
`tests/test_excel_import.py`:

```python
import import_formats as F                              # noqa: E402
from excel_import import build_mapping_model            # noqa: E402
spec = F.FORMATS["MASIVOS_LEGACY"]
rows = F.parse_rows(["Dia ","Mes ","Año","Comunidad/ Sitio de arribo","Lugar/ Sitio de pesca",
                     "Pescador","Embarcacion","Tecnico","Nombre comun","Nombre cientifico","Captura (kg)"],
                    [(1,1,2020,"CoA","SiA","PeA","NA","TeA","Cochito","Balistes","5")])
model = build_mapping_model(rows, spec)
# every catalog-bound distinct value appears, keyed by catalog
assert ("cat_sitio_pesca","SiA") in model["values"]
assert ("cat_comunidad","CoA") in model["values"]
assert model["especies"] == [("Cochito","Balistes")]
print("TODOS LOS CHECKS PASAN")
```

- [ ] **Step 2: Run to verify it fails** — `ImportError: build_mapping_model`.

- [ ] **Step 3: Implement Steps 1–2** in `excel_import.py`. Replace `_step1_upload`/`_step2_map` and
add `build_mapping_model`. Key logic (follow the `data_admin.py` widget idioms):

```python
import openpyxl
import import_formats as IF
import catalog_resolver as R


def _distinct_catalog_values(rows, spec):
    vals = {}      # (catalog, raw) -> None
    for r in rows:
        for header, t in {**spec.faena_cols, **spec.catch_cols}.items():
            if t.kind == "catalog" and not R.is_na(r.get(header)):
                vals[(t.catalog, R.normalize(r.get(header)))] = None
        # child catalogs (arte, carnada sitio/arte)
        for col, (header, cat) in {**spec.children["arte"]}.items():
            if cat and not R.is_na(r.get(header)):
                vals[(cat, R.normalize(r.get(header)))] = None
    return list(vals)


def build_mapping_model(rows, spec):
    values = [(c, v) for (c, v) in _distinct_catalog_values(rows, spec)]
    especies = []
    seen = set()
    for r in rows:
        pair = (R.normalize(r.get(spec.especie_comun)), R.normalize(r.get(spec.especie_cientifico)))
        if pair != ("", "") and pair not in seen:
            seen.add(pair); especies.append(pair)
    return {"values": {kv: None for kv in values}, "especies": especies}


def _step1_upload():
    up = st.file_uploader("Archivo Excel (.xlsx)", type=["xlsx"], key="imp_file")
    if not up:
        return
    wb = openpyxl.load_workbook(up, read_only=True, data_only=True)
    # choose the data sheet: the one whose header row best matches a known format
    best = None
    for ws in wb.worksheets:
        headers = [c for c in next(ws.iter_rows(values_only=True), [])]
        code = IF.detect_format([h for h in headers if h])
        if code:
            best = (ws.title, code, headers); break
    if not best:
        st.error("No reconozco el formato de ninguna hoja (esperaba Masivos o Bitácoras)."); return
    title, code, headers = best
    code = st.selectbox("Formato detectado", list(IF.FORMATS),
                        index=list(IF.FORMATS).index(code),
                        format_func=lambda c: IF.FORMATS[c].codigo)
    ws = wb[title]
    data = list(ws.iter_rows(min_row=2, values_only=True))
    rows = IF.parse_rows(headers, data)
    st.success(f"Hoja **{title}** · formato **{code}** · **{len(rows)}** filas de datos.")
    if st.button("Continuar →", type="primary"):
        st.session_state["imp_format"] = code
        st.session_state["imp_rows"] = rows
        st.session_state["imp_step"] = 1
        st.rerun()


def _step2_map():
    spec = IF.FORMATS[st.session_state["imp_format"]]
    rows = st.session_state["imp_rows"]
    model = build_mapping_model(rows, spec)
    st.caption("Confirma a qué catálogo corresponde cada nombre. Las coincidencias exactas ya están "
               "resueltas; revisa sólo lo que no coincide.")
    mapping = st.session_state.setdefault("imp_map", {})
    unresolved = 0
    for (catalog, raw), _ in model["values"].items():
        exact = R.resolve_exact(catalog, raw)
        if exact:
            mapping[(catalog, raw)] = exact; continue
        unresolved += 1
        with st.container(border=True):
            st.markdown(f"**{raw}** · `{catalog}`")
            sugg = R.fuzzy_suggest(catalog, raw)
            choices = {f"➕ Crear «{raw}»": ("new", raw), "🚫 Desconocido": ("desc", None)}
            for cid, name, score in sugg:
                choices[f"{name}  ({int(score*100)}%)"] = ("id", cid)
            pick = st.selectbox("Asignar a", list(choices), key=f"imp_m_{catalog}_{raw}")
            kind, val = choices[pick]
            mapping[(catalog, raw)] = {"new": None, "desc": "__DESC__", "id": val}[kind] \
                if kind != "id" else val
            if kind == "new":
                mapping[(catalog, raw)] = ("__NEW__", raw)
            if kind == "desc":
                mapping[(catalog, raw)] = ("__DESC__", catalog)
    st.caption(f"{unresolved} valor(es) por confirmar. Especies se resuelven por par común+científico "
               "en la vista previa.")
    c1, c2 = st.columns(2)
    if c1.button("← Volver"):
        st.session_state["imp_step"] = 0; st.rerun()
    if c2.button("Previsualizar →", type="primary"):
        st.session_state["imp_step"] = 2; st.rerun()
```

The mapping values encode the admin's choice; Task 8's resolve step turns `("__NEW__", raw)` /
`("__DESC__", cat)` / an id into the final id (create / Desconocido / use existing). Exact matches are
pre-filled. (Especie mapping is handled in preview via `resolve_or_create_especie`, which already
fuzzy-creates; a future refinement can add an especie confirm table here.)

- [ ] **Step 4: Run the unit test** → `TODOS LOS CHECKS PASAN`; `python -m py_compile excel_import.py`.

- [ ] **Step 5: Manual check (dev browser)** — `streamlit run app.py`, log in as admin, 📥 Importar
Excel, upload `Planning/DBScheme/Anexo2.xlsx`: it detects `produccion masivos` → MASIVOS_LEGACY, shows
row count, and Step 2 lists unmatched names with fuzzy suggestions. (Document result; do not commit
DB writes.)

- [ ] **Step 6: Commit**

```bash
git add excel_import.py tests/test_excel_import.py
git commit -m "Importar: wizard steps 1-2 upload/detect + catalog mapping (R5 Task 7)"
```

---

### Task 8: Wizard Steps 3–4 (preview + commit) + end-to-end test

**Files:**
- Modify: `catalog-review-app/excel_import.py`
- Test: `tests/test_excel_import_e2e.py`

**Interfaces — Consumes:** `import_formats`, `catalog_resolver`, `import_writer`. **Produces:**
`apply_mapping(spec, drafts, mapping)` (turns admin choices into resolved drafts), Step 3/4 UI.

- [ ] **Step 1: Write the failing e2e test** — `tests/test_excel_import_e2e.py`: build a small
in-memory `.xlsx` with openpyxl (a couple of masivos rows), drive the **non-UI** path
(`parse_rows → group_faenas → apply_mapping(auto: exact-or-create) → commit_batch`), assert faenas +
capturas created and a re-run skips them; guarded DEV DSN; cleanup by sitio name. (Mirror
`tests/test_import_writer.py`'s guard + cleanup; add an `apply_mapping` that, given an empty admin map,
falls back to `resolve_or_create`.)

- [ ] **Step 2: Run to verify it fails** — `ImportError: apply_mapping`.

- [ ] **Step 3: Implement Steps 3–4 + `apply_mapping`** in `excel_import.py`:

```python
import import_writer as IW


def apply_mapping(spec, drafts, mapping):
    """Rewrite each draft's ('catalog', cat, raw) cells using the admin mapping, then resolve
    the rest (create/Desconocido/especie) via import_writer.resolve_draft."""
    def rewrite(v):
        if isinstance(v, tuple) and len(v) == 3 and v[0] == "catalog":
            _, cat, raw = v
            choice = mapping.get((cat, R.normalize(raw)))
            if isinstance(choice, str):                      # a chosen existing id
                return choice
            if isinstance(choice, tuple) and choice[0] == "__DESC__":
                return R.desconocido_id(cat)
            return R.resolve_or_create(cat, raw)             # __NEW__ or unmapped → create/exact
        return v
    resolved = []
    for d in drafts:
        d.faena_raw = {k: rewrite(v) for k, v in d.faena_raw.items()}
        d.children_raw["arte"] = {k: rewrite(v) for k, v in d.children_raw["arte"].items()}
        resolved.append(IW.resolve_draft(spec, d))
    return resolved


def _step3_preview():
    spec = IF.FORMATS[st.session_state["imp_format"]]
    drafts = IF.group_faenas(st.session_state["imp_rows"], spec)
    resolved = apply_mapping(spec, drafts, st.session_state.get("imp_map", {}))
    hashes = [r["faena"]["legacy_id"] for r in resolved if r["key"]]
    dup = IW.existing_legacy_ids(hashes)
    nuevas = sum(1 for r in resolved if r["key"] and r["faena"]["legacy_id"] not in dup)
    ya = sum(1 for r in resolved if r["key"] and r["faena"]["legacy_id"] in dup)
    err = sum(1 for r in resolved if r["key"] is None)
    caps = sum(len(r["catches"]) for r in resolved if r["key"] and r["faena"]["legacy_id"] not in dup)
    st.session_state["imp_resolved"] = resolved
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Faenas nuevas", nuevas); c2.metric("Ya existen", ya)
    c3.metric("Capturas", caps); c4.metric("Con error", err)
    warnings = [e for r in resolved for e in r["errors"]]
    if warnings:
        with st.expander(f"⚠️ {len(warnings)} avisos"):
            for w in warnings[:200]:
                st.caption("• " + w)
    force = st.checkbox("Forzar inclusión de faenas que ya existen", key="imp_force")
    c1, c2 = st.columns(2)
    if c1.button("← Volver"):
        st.session_state["imp_step"] = 1; st.rerun()
    if c2.button(f"Guardar {nuevas} faena(s) →", type="primary", disabled=nuevas == 0 and not force):
        st.session_state["imp_step"] = 3; st.rerun()


def _step4_commit():
    from console_ui import friendly_error
    spec = IF.FORMATS[st.session_state["imp_format"]]
    resolved = st.session_state["imp_resolved"]
    try:
        rep = IW.commit_batch(spec, resolved, force=st.session_state.get("imp_force", False))
    except Exception as e:                                    # noqa: BLE001
        st.error(friendly_error(e)); return
    st.success(f"✅ {rep['faenas_nuevas']} faenas · {rep['capturas']} capturas guardadas. "
               f"{rep['ya_existen']} ya existían. {rep['faenas_error']} con error.")
    if rep["errores"]:
        with st.expander("Errores"):
            for e in rep["errores"][:200]:
                st.caption("• " + e)
    st.info("Los catálogos nuevos quedaron **sin aprobar** — revísalos en 🔎 Duplicados / 📥 Propuestas.")
    if st.button("Importar otro archivo", type="primary"):
        _reset(); st.rerun()
```

- [ ] **Step 4: Run the e2e test** → `TODOS LOS CHECKS PASAN`; `python -m py_compile excel_import.py`.

- [ ] **Step 5: AppTest smoke** — extend `tests/test_excel_import.py` to run `app.py` with
`auth_rol=ADMINISTRADOR`, `console_mode=importar`, and assert `not at.exception` at step 0. (Mirror the
AppTest block from the data-editor verification.)

- [ ] **Step 6: Full manual run (dev)** — import `Anexo2.xlsx` end to end in the browser: map catalogs,
preview counts, confirm, verify faenas/capturas appear in ✏️ Registros and re-import is skipped. Clean
up the dev rows afterward.

- [ ] **Step 7: Commit**

```bash
git add excel_import.py tests/test_excel_import_e2e.py tests/test_excel_import.py
git commit -m "Importar: wizard steps 3-4 preview/commit + e2e (R5 Task 8)"
```

---

## Verification (whole feature)

Run all new tests from the repo root (`catalog-review-app/`):

```bash
for t in test_catalog_resolver test_import_formats_parse test_import_formats_group \
         test_excel_import test_catalog_resolver_db test_import_writer test_excel_import_e2e; do
  PYTHONIOENCODING=utf-8 python tests/$t.py || echo "FAILED: $t"
done
```

Pure tests (`test_catalog_resolver`, `test_import_formats_*`, the `build_mapping_model` unit) need no
DB. The `_db`, `_writer`, and `_e2e` tests require the DEV DSN and are self-guarded + self-cleaning.
Then the manual dev-browser run in Task 8 Step 6 is the acceptance gate.

## Self-Review notes (author)

- **Spec coverage:** 4-step wizard (Tasks 1,7,8), fuzzy+confirm resolution (Tasks 2,3,7),
  auto-create-unapproved column-gated (Task 3), especie pair (Tasks 3,5,6), grouping by natural key
  (Task 5), dedup by `legacy_id` (Task 6), transactional insert + audit (Task 6), field mapping to real
  columns (Task 4), non-goals honored (no medicion, no valor_campo_faena, no rollback UI). ✔
- **Type consistency:** `('catalog', cat, raw)` placeholder is produced in `import_formats._faena_fields`
  / `_children` and consumed in `import_writer._resolve_cell` and `excel_import.apply_mapping` — same
  3-tuple shape throughout. `FaenaDraft`/`FormatSpec` fields match across Tasks 4–8. ✔
- **Known follow-ups (documented, not blocking):** ETP común resolves via
  `resolve_or_create_especie(comun,"NA")` (científico unknown from these columns) — acceptable; a
  dedicated especie-confirm table in Step 2 is a future refinement; per-run resolver cache if the
  mapping UI is slow on large files.
