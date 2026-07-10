# R5 — Excel bulk import (Masivos + Bitácoras) — Design

**Date:** 2026-07-10
**Status:** Approved (design); implementation plan pending.
**Scope of this slice:** the two production formats of *Anexo 2*
(`MASIVOS_LEGACY`, `BITACORA_LEGACY`). Monitoreo-pesquero (biological →
`medicion`) is explicitly deferred to a later slice.

## Context

The console can capture and edit fisheries data one record at a time, but the
institute holds decades of historical data in Excel workbooks (the *Anexo 2*
compendium: 2009–2022). Admins need a **repeatable** tool to load those workbooks
into the database, not a one-off migration script — new historical files keep
arriving in the same format.

The database was pre-seeded for exactly this: `cat_formato_origen` already has
`MASIVOS_LEGACY` ("Masivos Legacy (Anexo 2)"), `BITACORA_LEGACY` ("Bitácoras
Legacy (Anexo 2)") and `CM07` ("CM-07 Biológico"); `faena` carries `legacy_id`,
`codigo_formato`, `tipo_registro`, and `latitud_legacy`/`longitud_legacy`. `faena`
is effectively empty today (≈8 test rows), so this is greenfield loading.

Sample workbook: `Planning/DBScheme/Anexo2.xlsx`. Its data sheets are
`produccion masivos` (82 cols) and `producción bitácoras recortada` (79 cols) —
near-identical layouts — plus `Validación` (canonical catalog value lists) and
`Monitore pesquero Recortado` (biological, out of scope here).

### Decisions taken during brainstorming
1. **Repeatable admin tool** (not a one-time migration).
2. **Masivos + Bitácoras first**, behind a pluggable per-format mapping so the
   biological format and other compendia (Nayarit, CoccBCS…) are added as data,
   not new code.
3. **Fuzzy-match + confirm** for catalog resolution: exact matches auto-resolve;
   unmatched/ambiguous names are confirmed by the admin before commit.
4. **Detect & skip duplicate faenas** by natural key on re-import.

## Data shape

Each production row is **one species caught on one trip**. Trip-level columns
(date, community, site, fisher, boat, gasoline, hours, wind/moon/tide, ETP
interaction, expenses…) repeat across the rows of a trip; only the catch columns
(común/científico, kg, size, price) vary. So rows group into a **faena** with
many **capturas**.

Grouping is unambiguous in the sample: `ID`/`Num.Formato` are `NA` throughout, so
the trip identity is the tuple of trip-level values. Example — rows sharing
`13/8/2009 · Punta Coyote · El Mechudo · Playa Camarón I` form one faena with 5
capturas; when the fisher is `NA`, the boat disambiguates (rows keyed by
`Albatros II`).

## Architecture

A new ADMINISTRADOR-only console mode **`importar` — "📥 Importar Excel"** (nav
group CONFIGURAR; excluded from `ANALISTA_MODES`), rendered as a **4-step wizard**
whose state lives in `session_state` (a `step` counter + the parsed/mapped
payload), mirroring the existing `render_*` modules and dispatched from `app.py`.

```
Step 1  Subir & detectar  → Step 2  Mapear catálogos
   → Step 3  Previsualizar → Step 4  Confirmar (commit) → Reporte
```

### Step 1 — Subir & detectar
- `st.file_uploader` (`.xlsx`) → `openpyxl.load_workbook(read_only=True,
  data_only=True)`.
- **Auto-detect format** by header signature: match the sheet's header row
  against each registered format's expected column set (Jaccard over normalized
  headers); pick the best, let the admin confirm/override (Masivos vs Bitácoras).
- Show the resolved sheet, detected format, and data-row count.

### Step 2 — Mapear catálogos
- For every field bound to a catalog, collect the **distinct raw values** in the
  file.
- Values that **exactly** (normalized, case-insensitive) match an existing
  catalog entry resolve silently.
- Remaining values render in a **compact per-catalog table**: the raw value, the
  best fuzzy suggestion, and a choice — *aceptar sugerencia* / *elegir otra
  existente* / *crear nueva* / *Desconocido*. `NA`/`ND`/blank/`pendiente`
  pre-select *Desconocido*.
- Output: a `(catalog, raw_value) → resolved_id` map plus the set of
  **new entries to create** (deferred until commit). A per-catalog *Desconocido*
  placeholder is created on demand and reused.

### Step 3 — Previsualizar
- Group rows into faenas by the natural key; resolve every FK via the Step-2 map;
  build faena + captura + child records.
- **Validate** per faena/row (see Validation). **Duplicate-detect** each faena
  against existing `faena` rows by natural key (see Idempotency).
- Summary: **N faenas nuevas · M ya existen (se omiten) · X capturas · R filas con
  error**, with expandable detail (which rows, which errors, which faenas skipped
  and why). Skipped duplicates can be **force-included** with an explicit toggle.

### Step 4 — Confirmar (commit)
- Insert on the shared psycopg2 connection inside **one transaction with a
  per-faena `SAVEPOINT`**: a faena that fails to insert is rolled back to its
  savepoint and reported; the rest commit. (The shared connection is
  `autocommit=True`; the importer wraps the batch in an explicit
  `BEGIN…COMMIT` for the duration, then restores autocommit.)
- New catalog entries are created first, `es_aprobado=false`, so they surface in
  the existing 🔎 Duplicados / 📥 Propuestas review.
- Each faena stores provenance in `legacy_id` (natural-key hash) and, when
  present, `codigo_formato` (Num.Formato). Every insert writes a `cambio_catalogo`
  audit row (`accion='importar'`, attributed to the admin via the `_log`
  attribution already in place).
- Final **report**: faenas/capturas created, catalogs created, faenas skipped,
  rows failed — downloadable as CSV for the record.

## Modules

Kept small and single-purpose:

- **`excel_import.py`** — `render_excel_import()`: the wizard, orchestration,
  session-state machine, preview/report rendering. No mapping knowledge of its
  own — it drives the format spec + resolver.
- **`import_formats.py`** — declarative registry. Per format:
  `codigo` (→ `formato_origen_id`), `tipo_registro`, the **column→target**
  mapping (which faena/captura/child column each Excel column feeds, with a
  parser: text/num/date/hora/catalog-ref), the **faena grouping key**, and the
  **catalog bindings** (field → `cat_*` table, with especie flagged as
  común+científico pair). `MASIVOS_LEGACY` and `BITACORA_LEGACY` are two entries;
  the near-identical layout is expressed as shared column groups.
- **`catalog_resolver.py`** — `normalize(value)`, `fuzzy_matches(catalog, value)`
  (`difflib.get_close_matches`, cutoff ≈0.82, against approved **and** unapproved
  names so imports don't re-create pending entries), `resolve_or_create(...)`,
  and per-catalog *Desconocido* placeholders. **Especie** resolves on the
  `(nombre_comun, nombre_cientifico)` pair — never común alone (homonyms); a `NA`
  científico resolves/creates an entry with `nombre_cientifico` null.

**Reused:** `form_builder._q/_exec/_log`, `console_ui` (page_header, flash,
confirm_button, friendly_error, empty_state), `catalog_admin` FK helpers where
useful, `home.py`/`app.py` nav + dispatch. **New dependency:** none (`openpyxl`
is already a dependency; `difflib` is stdlib).

## Field mapping (Masivos/Bitácoras → schema)

Trip-level → **`faena`**: fecha (Día/Mes/Año), comunidad_id (Comunidad/Sitio de
arribo), sitio_pesca_id (Lugar/Sitio de pesca), area_pesca_id, zona_pesca_id,
capitan_id (Pescador), embarcacion_id, cooperativa_id, tecnico_id
(Técnico/"Datos capturados por"), num_pescadores, gasolina_lts, motor_hp,
encargado_lugar, hora_salida, hora_llegada, tiempo_efectivo_pesca_h (Horas/Tiempo
de pesca), profundidad_min/max_brazas, tipo_fondo_id, viento_id, luna_id,
marea_id, latitud_legacy/longitud_legacy, observaciones.

Per row → **`captura`**: especie_id (común+científico), captura_kg,
categoria_tamano (Categoría por tamaño), precio_kg (Precio).

Per faena → children:
- **`faena_arte`**: Arte de pesca → tipo_arte_id, Método/Caída, #Piola/Luz de
  malla, Tipo/Tamaño/Material de anzuelo, Operación → tipo_operacion_id.
- **`carnada`**: origen (Comprada/Pescada), especie (común+científico carnada),
  sitio_pesca_carnada_id, kg_aprox, arte_pesca_id.
- **`interaccion_etp`**: Especie/Interacción (+ Especie 2/Interacción 2) →
  especie_id + tipo_interaccion_id.
- **`gasto`**: the cantidad/$ columns (gasolina, anzuelos, destorcedores, plomada,
  piola, aceite, baterías, carnada, otros) → tipo_gasto_id + monto_total.

Columns with **no schema home** are dropped and listed in the spec's
"unmapped columns" note (not stored in `valor_campo_faena`).

## Validation rules

- **Required faena FKs** (comunidad, sitio, capitán, técnico) always resolve —
  worst case to *Desconocido* — so a faena is never blocked on a missing FK.
- **`tiempo_efectivo_pesca_h`** (NOT NULL): parsed from Horas/Tiempo de pesca;
  unparseable/NA → `0` with a per-faena warning surfaced in the preview.
- **`captura_kg`** (NOT NULL): a catch row with no numeric kg is **reported and
  skipped** (the faena still imports with its valid capturas).
- **Child records** are best-effort: a child that can't satisfy its required
  columns (e.g. a gasto with no amount) is skipped with a warning; it never fails
  the faena.
- Date assembled from Día/Mes/Año; an unparseable date fails the **faena** (all
  its rows), reported in the preview.

## Idempotency

`legacy_id` = a stable hash of the faena natural key
(`formato · fecha · comunidad · sitio · capitán · embarcación · técnico`). Step 3
queries existing `faena.legacy_id` for the batch's hashes; matches are marked
**"ya existe"** and skipped by default. This makes re-importing the same (or an
overlapping) file safe. Force-include overrides per preview.

## Testing

- **Unit — `import_formats`:** fixture rows → expected grouped faenas + resolved
  targets; NA handling; grouping key incl. the boat-fallback case; unparseable
  date fails the faena; missing kg skips the captura.
- **Unit — `catalog_resolver`:** deterministic `difflib` cases (exact, near-dup,
  no-match→create, NA→Desconocido); especie común+científico pairing incl.
  homonym separation and null científico.
- **Dev round-trip (guarded DEV DSN, throwaway rows):** import a tiny in-memory
  fixture → faenas/capturas created + catalogs auto-created `es_aprobado=false` +
  attributed `cambio_catalogo` rows; **re-import → every faena skipped as
  duplicate**; a row with no kg skipped but its faena present; cleanup.
- **AppTest smoke:** `importar` renders (ADMINISTRADOR), absent for `ANALISTA`.

## Non-goals (this slice)

- Monitoreo-pesquero / `medicion` (individual biometrics) — next slice, same
  wizard, a third `import_formats` entry.
- No rollback UI (natural-key dedup covers re-runs); a batch/`lote` table can be
  added later if bulk-undo is needed.
- No persistent fuzzy-alias memory across imports (each import confirms its own
  mappings).
- No `valor_campo_faena` catch-all for unmapped columns.
