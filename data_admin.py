"""
Data admin — full-field edit/delete on captured *data* rows (faenas + children).

Where ✏️ Catálogos (catalog_admin.py) edits the reference tables (cat_*), this
mode is the admin's editor for the operational data: faena and its child tables
(capturas, mediciones, artes, gastos…). It reuses catalog_admin's introspection
and write layer wholesale — every data table here has a plain `id` UUID primary
key — and adds what data tables need that catalogs don't:

  * a **filter-based** row picker (data tables have no `nombre` column, and
    faena/medicion have 100k+ rows, so we never list-all or count(*));
  * FK columns that point at a *nameless* table (a child's `faena_id`) are edited
    as raw UUIDs instead of a name selectbox.

Scope: edit + delete existing rows only (no insert, no bulk). Deletes are FK-safe
(blocked while referenced). Composite-PK tables (tecnico_comunidad) are out of
scope. Every change writes a cambio_catalogo audit row attributed to the admin.
"""
from __future__ import annotations

import datetime

import streamlit as st

from form_builder import _q
from catalog_admin import (
    column_meta, fk_options, fk_search_options, load_row, save_row, delete_row,
    _col_label, _col_help, _name_col, FK_CAP,
)
from proposals_review import dependents_detail

# Data tables with a single `id` UUID PK (verified). tecnico_comunidad (composite
# PK) is intentionally excluded.
DATA_TABLES: dict[str, str] = {
    "faena":                  "Faenas",
    "captura":                "Capturas",
    "medicion":               "Mediciones",
    "faena_arte":             "Artes de pesca (por faena)",
    "faena_especie_objetivo": "Especies objetivo (por faena)",
    "carnada":                "Carnadas",
    "interaccion_etp":        "Interacciones ETP",
    "gasto":                  "Gastos",
    "aportacion_imss":        "Aportaciones IMSS",
    "recurso_ahorro":         "Recursos de ahorro",
    "valor_campo_faena":      "Valores de campo (formulario)",
}

CAP = 300


@st.cache_data(ttl=300, show_spinner=False)
def display_col(ref_table: str) -> str | None:
    """The ref table's name column if it actually exists, else None. Drives the
    FK «name selectbox vs raw UUID» choice — a child's faena_id points at a table
    with no name column, so it falls back to a UUID text input."""
    nc = _name_col(ref_table)
    exists = _q("""SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name=%s AND column_name=%s""",
                (ref_table, nc))
    return nc if exists else None


@st.cache_data(ttl=300, show_spinner=False)
def _generated_cols(tabla: str) -> set[str]:
    return {r["column_name"] for r in _q(
        """SELECT column_name FROM information_schema.columns
           WHERE table_schema='public' AND table_name=%s
             AND (is_generated='ALWAYS' OR is_identity='YES')""", (tabla,))}


@st.cache_data(ttl=300, show_spinner=False)
def _date_cols(tabla: str) -> list[str]:
    return [r["column_name"] for r in _q(
        """SELECT column_name FROM information_schema.columns
           WHERE table_schema='public' AND table_name=%s
             AND data_type IN ('date','timestamp with time zone','timestamp without time zone')
           ORDER BY ordinal_position""", (tabla,))]


def data_meta(tabla: str) -> list[dict]:
    """column_meta with generated/identity columns forced read-only. Returns
    fresh dicts so the cached column_meta list is never mutated."""
    gen = _generated_cols(tabla)
    out = []
    for m in column_meta(tabla):
        mm = dict(m)
        if mm["name"] in gen:
            mm["kind"] = "ro"
        out.append(mm)
    return out


def _row_label(tabla: str, r: dict) -> str:
    """Short human handle for a data row (audit log + dialog header)."""
    rid = str(r.get("id", ""))
    fecha = r.get("fecha")
    return f"{DATA_TABLES.get(tabla, tabla)} · {fecha} · {rid[:8]}" if fecha else \
           f"{DATA_TABLES.get(tabla, tabla)} · {rid[:8]}"


def _display_df(rows: list[dict], meta: list[dict]) -> "pd.DataFrame":
    """Human grid of data rows: id (short), FK ids resolved to names when the ref
    has one (else a short UUID), booleans as checkmarks."""
    import pandas as pd
    fk_names = {m["name"]: {o["id"]: o["nombre"] for o in fk_options(m["fk"])}
                for m in meta if m["kind"] == "fk" and display_col(m["fk"])}
    out = []
    for r in rows:
        d = {"id": str(r.get("id", ""))[:8]}
        for m in meta:
            n = m["name"]
            if n == "id":
                continue
            v = r.get(n)
            if m["kind"] == "fk":
                if n in fk_names:
                    v = fk_names[n].get(str(v), "") if v is not None else ""
                else:
                    v = str(v)[:8] if v is not None else ""
            elif m["kind"] == "bool":
                v = "✓" if v else ""
            elif isinstance(v, (datetime.date, datetime.datetime)):
                # raw date/timestamp objects in an object-dtype column crash pyarrow's
                # Arrow conversion (st.dataframe) — render as text like every other
                # non-fk/bool column instead.
                v = str(v)
            # else: leave numeric/text as-is (None stays None so a nullable numeric
            # column keeps a single type — mixing "" with ints breaks Arrow).
            d[_col_label(n)] = v
        out.append(d)
    return pd.DataFrame(out)


# =====================================================================
# UI
# =====================================================================
def render_data_admin():
    from console_ui import page_header, friendly_error, confirm_button, flash, empty_state
    page_header(
        "✏️ Registros (datos)",
        "Corrige o elimina registros capturados (faenas y sus datos asociados).",
        help_md=(
            "Esta sección edita los **datos del monitoreo** (no los catálogos).\n\n"
            "1. Elige la **tabla** y **busca** el registro por id o por un filtro "
            "(p. ej. capturas de una faena, faenas de una comunidad o por fecha).\n"
            "2. Marca ☑️ la fila, corrige los campos y pulsa **💾 Guardar**.\n"
            "3. Un registro usado por otros **no se puede eliminar**. Eliminar una "
            "**faena** borra también sus capturas, mediciones y demás datos.\n\n"
            "Cada cambio queda registrado en la bitácora, con tu nombre."
        ),
    )
    st.warning("⚠️ Aquí editas datos reales del monitoreo. Los cambios son inmediatos "
               "y no se pueden deshacer.", icon="⚠️")

    try:
        _date_cols("faena")  # cheap connectivity probe
    except Exception as e:  # noqa: BLE001
        st.error(f"No se pudo conectar a la base de datos: {e}")
        return

    tabla = st.selectbox("Tabla", list(DATA_TABLES), key="da_tabla",
                         format_func=lambda t: DATA_TABLES[t])
    meta = data_meta(tabla)
    date_cols = _date_cols(tabla)
    has_created = "created_at" in date_cols
    fk_cols = [m for m in meta if m["kind"] == "fk"]

    # ---- filter picker (no name column on data tables) ----
    filtros: dict[str, str] = {"__id__": "Id exacto (UUID)"}
    for m in fk_cols:
        filtros[f"fk:{m['name']}"] = _col_label(m["name"])
    for c in date_cols:
        filtros[f"date:{c}"] = f"{_col_label(c)} (rango de fechas)"

    fkey = st.selectbox("Buscar por", list(filtros), key=f"da_filtro_{tabla}",
                        format_func=lambda k: filtros[k])

    clause, args, ready = "", [], False
    if fkey == "__id__":
        rid_in = st.text_input("Id (UUID)", key=f"da_id_{tabla}",
                               placeholder="pega el id del registro…").strip()
        if rid_in:
            clause, args, ready = "id=%s", [rid_in], True
    elif fkey.startswith("fk:"):
        col = fkey[3:]
        ref = next(m["fk"] for m in fk_cols if m["name"] == col)
        dc = display_col(ref)
        if dc:
            q2 = st.text_input(f"Buscar {_col_label(col).lower()}", key=f"da_fkq_{tabla}_{col}")
            opts = fk_search_options(ref, q2, None)
            omap = {o["id"]: o["nombre"] for o in opts}
            chosen = st.selectbox(_col_label(col), [None] + [o["id"] for o in opts],
                                  format_func=lambda i: "— elige —" if i is None else omap.get(i, i),
                                  key=f"da_fk_{tabla}_{col}")
            if chosen:
                clause, args, ready = f'"{col}"=%s', [chosen], True
        else:
            v = st.text_input(f"{_col_label(col)} (UUID)", key=f"da_fkid_{tabla}_{col}",
                              placeholder="pega el id…").strip()
            if v:
                clause, args, ready = f'"{col}"=%s', [v], True
    elif fkey.startswith("date:"):
        col = fkey[5:]
        c1, c2 = st.columns(2)
        d1 = c1.date_input("Desde", value=None, key=f"da_d1_{tabla}_{col}")
        d2 = c2.date_input("Hasta", value=None, key=f"da_d2_{tabla}_{col}")
        if d1 and d2:
            clause, args, ready = f'"{col}"::date BETWEEN %s AND %s', [d1, d2], True

    order = "created_at DESC" if has_created else "id"
    if ready:
        rows = _q(f'SELECT * FROM public."{tabla}" WHERE {clause} ORDER BY {order} LIMIT %s',
                  args + [CAP])
    elif has_created:
        rows = _q(f'SELECT * FROM public."{tabla}" ORDER BY {order} LIMIT %s', [CAP])
    else:
        empty_state("Elige un filtro o busca por id para ver registros de esta tabla.", "🔎")
        return

    if not rows:
        empty_state("Ningún registro coincide con la búsqueda.", "🔍")
        return

    ids = [str(r["id"]) for r in rows]
    labels = {str(r["id"]): _row_label(tabla, r) for r in rows}
    st.caption(f"Mostrando hasta **{len(rows)}** registro(s) (máx. {CAP}) — afina el filtro "
               "para acotar. Marca la casilla ☑️ de una fila para editarla.")

    nonce = st.session_state.setdefault("da_nonce", 0)
    ev = st.dataframe(
        _display_df(rows, meta), key=f"da_tbl_{tabla}_{nonce}",
        selection_mode="single-row", on_select="rerun",
        hide_index=True, width="stretch", height=400)

    @st.dialog(f"✏️ {DATA_TABLES.get(tabla, tabla)}", width="large")
    def edit_dialog(rid: str):
        current = load_row(tabla, rid)
        st.caption(f"Editando: **{labels.get(rid, rid)}**")
        values: dict = {}
        for m in meta:
            name, kind = m["name"], m["kind"]
            if kind == "ro":
                continue
            cur_val = current.get(name)
            label = _col_label(name) + ("" if m.get("nullable", True) else " *")
            helptxt = _col_help(name, m.get("nullable", True))
            wkey = f"dad_{tabla}_{rid}_{name}"
            if kind == "fk":
                ref = m["fk"]
                if display_col(ref) is None:
                    # FK to a nameless table (e.g. a child's faena_id) → raw UUID
                    v = st.text_input(f"{label} (UUID)",
                                      value="" if cur_val is None else str(cur_val),
                                      key=wkey, help=helptxt)
                    values[name] = v if v.strip() != "" else None
                    continue
                opts = fk_options(ref)
                if len(opts) >= FK_CAP:
                    q2 = st.text_input(f"Buscar {_col_label(name).lower()}", key=f"{wkey}_q",
                                       help="Este catálogo es muy grande; escribe para buscar.")
                    opts = fk_search_options(ref, q2, cur_val)
                omap = {o["id"]: o["nombre"] for o in opts}
                opt_ids = [None] + [o["id"] for o in opts]
                idx = opt_ids.index(cur_val) if cur_val in opt_ids else 0
                values[name] = st.selectbox(
                    label, opt_ids, index=idx,
                    format_func=lambda i, mm=omap: "— (vacío) —" if i is None else mm.get(i, i),
                    key=wkey, help=helptxt)
            elif kind == "enum":
                opt_ids = ([None] if m["nullable"] else []) + m["enum"]
                idx = opt_ids.index(cur_val) if cur_val in opt_ids else 0
                values[name] = st.selectbox(label, opt_ids, index=idx,
                                            format_func=lambda v: "— (vacío) —" if v is None else v,
                                            key=wkey, help=helptxt)
            elif kind == "bool":
                values[name] = st.checkbox(label, value=bool(cur_val), key=wkey, help=helptxt)
            elif kind == "num":
                v = st.text_input(label, value="" if cur_val is None else str(cur_val),
                                  key=wkey, help=helptxt)
                if v.strip() == "":
                    values[name] = None
                else:
                    try:
                        values[name] = int(v) if m.get("int") else float(v)
                    except ValueError:
                        values[name] = cur_val
                        st.caption(f"⚠️ «{v}» no es un número válido para {_col_label(name)}.")
            else:
                v = st.text_input(label, value="" if cur_val is None else str(cur_val),
                                  key=wkey, help=helptxt)
                values[name] = v if v.strip() != "" else None

        ro_meta = [m for m in meta if m["kind"] == "ro"]
        if ro_meta:
            with st.expander("🔧 Datos del sistema (solo lectura)"):
                for m in ro_meta:
                    cv = current.get(m["name"])
                    st.text_input(_col_label(m["name"]),
                                  value=str(cv) if cv is not None else "",
                                  disabled=True, key=f"dad_{tabla}_{rid}_{m['name']}")

        if st.button("💾 Guardar", key=f"dad_save_{rid}", type="primary", width="stretch"):
            missing = [_col_label(m["name"]) for m in meta
                       if m["kind"] != "ro" and not m.get("nullable")
                       and values.get(m["name"]) in (None, "")]
            if missing:
                st.error("Faltan campos obligatorios: " + ", ".join(missing))
            else:
                try:
                    save_row(tabla, meta, rid, values)
                    st.session_state["da_nonce"] += 1
                    st.session_state["da_open_rid"] = None
                    flash("Cambios guardados.")
                    st.rerun()
                except Exception as e:  # noqa: BLE001
                    st.error(friendly_error(e))

        st.divider()
        detail = dependents_detail(tabla, rid)
        if detail:
            dep = sum(n for _, n in detail)
            st.info(f"🔒 Este registro está en uso por **{dep}** registro(s): " +
                    " · ".join(f"{n} en `{t}`" for t, n in detail) +
                    ". No se puede eliminar directamente.")
        else:
            casc = " Al eliminar una faena se borran también sus capturas, mediciones y demás " \
                   "datos asociados." if tabla == "faena" else ""
            if confirm_button("🗑️ Eliminar", key=f"dad_del_{rid}",
                              help="Elimina el registro de forma definitiva." + casc):
                try:
                    delete_row(tabla, rid, labels.get(rid) or rid)
                    st.session_state["da_nonce"] += 1
                    st.session_state["da_open_rid"] = None
                    flash("Registro eliminado.", "🗑️")
                    st.rerun()
                except Exception as e:  # noqa: BLE001
                    st.error(friendly_error(e))

    sel = ev.selection.rows
    if sel:
        rid = ids[sel[0]]
        if st.session_state.get("da_open_rid") != rid:
            st.session_state["da_open_rid"] = rid
            edit_dialog(rid)
    else:
        st.session_state["da_open_rid"] = None
