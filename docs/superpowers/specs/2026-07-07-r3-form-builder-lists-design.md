# R3 — Curated-list editing in the Form Builder (design)

_2026-07-07 · catalog-review-app console · approved by user_

## Problem

Curated per-form option lists (`lista_opcion`, migration 0013) are what the tablet's pickers
actually show. Today they can only be managed in the separate 📑 Listas del formulario mode via
CSV upload, and the Form Builder shows list-bound fields as read-only ("se administran en 📑
Listas, no aquí"). There is no way to attach a list to a field from the builder at all — only
`seed_form.py` ever set the `lista` key. Small everyday changes (add one species, drop one,
reorder) force a full CSV round-trip.

## Scope (agreed)

In the Form Builder's field dialog, for fields that resolve to a catalog table:

1. **See** the list's current options (names + científico for especies + importancia).
2. **Edit by hand**: add one option (search the catalog; create a new approved row if missing),
   remove one, tweak importancia.
3. **Attach/detach** a lista on the field: reuse an existing list of the form (same tabla) or
   create a new one by name; detach only unlinks the field — the list's rows stay.

Out of scope: CSV upload stays exclusively in 📑 Listas del formulario (bulk path, unchanged).

## Approach

New small module **`lista_editor.py`** (data layer + one UI entry point), called from
`form_builder._campo_dialog` (form_builder.py:1068, `@st.dialog`). Reuses the existing DB layer
(`_exec`/`_q`/`_log` from `form_builder`) and `lista_import`'s conventions (`_norm`, `_name_col`,
create-approved-row SQL). Chosen over growing `lista_import.py` (mixes two UIs) or inlining in
`form_builder.py` (already 1,551 lines).

The capture app is generic — `getListaItems(lista, tabla)` draws any field's options from the
mirrored `lista_opcion` by list name + the field's catalog table — so attach/detach is not limited
to the three preset lists.

## Design

### Data layer (`lista_editor.py`)

- `form_listas(formato_id) -> dict[str, str]` — existing list names → tabla, for the attach picker.
- `get_opciones(formato_id, lista) -> list[dict]` — options joined to their catalog table for the
  display name (name column via `lista_import._name_col`; include `nombre_cientifico` when tabla
  is `cat_especie`), ordered by importancia desc, name asc.
- `search_catalogo(tabla, q, formato_id, lista, limit≈20)` — accent-insensitive ILIKE on the name
  column (and científico for especies), excluding rows already in the list; **only
  `estado='aprobado'` rows** — the tablet mirrors approved catalog rows only, so an unapproved
  option would silently vanish from the picker.
- `add_opcion(formato_id, lista, tabla, registro_id, importancia=0)` — same upsert as the import
  tool (`ON CONFLICT (formato_origen_id, lista, registro_id) DO UPDATE SET importancia=…`).
- `remove_opcion(formato_id, lista, registro_id)` — delete the lista_opcion row.
- `set_importancia(formato_id, lista, registro_id, imp)` — update.
- `create_and_add(formato_id, lista, tabla, nombre, sci=None)` — create a new **approved** catalog
  row exactly like `lista_import`'s "crear" (`es_aprobado=true, estado='aprobado'`; especies get
  `nombre_cientifico` or `'Pendiente'`; set `apta_carnada=true` when `lista == 'carnada'`), then
  `add_opcion`. Never merges — same homonym policy as the import tool.
- Every write emits a `_log` audit entry mirroring the import tool's.

### UI (`render_lista_editor(formato_id, campo, key_prefix) -> str | None`)

Rendered inside `_campo_dialog` where the read-only info box sits today (form_builder.py:1112–1114),
only when the field resolves to a catalog table. Returns the chosen lista name (or None), which the
dialog's normal **Guardar** writes into the field's `lista` key (round-trips already work —
`_FIELD_COLS` carries `lista` since the Phase 5 fix).

- **Attach control**: selectbox «Lista curada» = «— sin lista —» + the form's existing lists whose
  tabla matches this field's catalog + «➕ Nueva lista…» (text input; default = the field's
  etiqueta slug, normalized lowercase, e.g. «Especie objetivo» → `especie_objetivo`).
  Caption: attaching/detaching only reaches the tablet when the form is **published**.
- **Options editor** (when a lista is set): expander «📑 Opciones de la lista "X" (N)»:
  - `st.data_editor`: nombre (read-only), científico (read-only, especies only), **importancia**
    (editable int), **quitar** (checkbox). One button «Guardar cambios en la lista» applies
    importancia updates + removals in batch.
  - Add row: search text input → matches selectbox → «Añadir»; when nothing matches, offer
    «Crear "…" y añadir» (with a científico input for especies).
  - Plain-Spanish note: option edits are **live on the tablet after its next sync** (no publish);
    warning when the attached list has 0 options (the técnico would see an empty picker).
  - Pointer to 📑 Listas del formulario for bulk CSV updates.

### Integration & semantics

- Detach = «— sin lista —» → the `lista` key is dropped from the field definition on Guardar;
  `lista_opcion` rows are untouched (lists may be shared by several fields/forms).
- Two clocks, stated in the UI: field-definition changes (attach/detach) take effect on publish;
  option changes are immediate (tablet re-mirrors `lista_opcion` on sync).
- 📑 Listas del formulario mode is unchanged.

### Errors & safety

- All writes wrapped in `console_ui.friendly_error`.
- Homonym safety: search results display científico so same-common-name species are
  distinguishable; create-and-add always creates, never merges.
- Console uses the service DSN (no RLS impact); audit trail via `_log` as elsewhere.

### Testing

- Data-layer round-trip against **dev** (override `DATABASE_URL`/`SUPABASE_*` per the handoff
  convention; throwaway formato + rows): attach-new → add existing → create-and-add → set
  importancia → remove → detach leaves rows → cleanup.
- Standard AppTest smoke (app boots as ADMINISTRADOR, Formularios mode renders, no exception).
  Streamlit dialogs aren't reachable from AppTest → dialog interaction verified manually in the
  running console against dev.
