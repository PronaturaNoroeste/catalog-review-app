"""
Catalog admin — full-field CRUD on catalog rows (M3 / OD-17).

The proposal queue (proposals_review.py) handles field-proposed entries
(approve/reject/merge). This mode is the admin's general editor: pick any cat_*
table, search a row, edit any field (FK-aware selects, enums, booleans), or
create / delete rows. Deletes are FK-safe (blocked while referenced). Every
change writes a cambio_catalogo audit row (C1 lightweight change log).

Reuses the form_builder DB layer + proposals_review.referencing_columns.
"""
from __future__ import annotations

import uuid

import streamlit as st

from form_builder import _q, _exec, _log
from proposals_review import dependents_detail

# Columns shown read-only (identity / audit plumbing).
SYSTEM_RO = {"id", "created_at", "updated_at", "propuesto_por", "propuesto_at"}
NAME_COL = {"cat_especie": "nombre_comun", "cat_formato_origen": "codigo"}

# Human labels + optional help for the columns that appear across cat_* tables.
COLUMN_LABELS: dict[str, tuple[str, str | None]] = {
    "nombre":             ("Nombre", None),
    "nombre_comun":       ("Nombre común", "Como se conoce localmente (p. ej. Bonito)."),
    "nombre_cientifico":  ("Nombre científico", "Género y especie (p. ej. Sarda chiliensis)."),
    "es_aprobado":        ("Aprobado", "Solo lo aprobado aparece en los catálogos oficiales."),
    "estado":             ("Estado", "pendiente → aprobado / rechazado / fusionado."),
    "apta_carnada":       ("Apta como carnada", "La especie puede ofrecerse en la lista de carnada."),
    "cooperativa_id":     ("Cooperativa", None),
    "region_id":          ("Región", None),
    "zona_pesca_id":      ("Zona de pesca", None),
    "area_pesca_id":      ("Área de pesca", None),
    "codigo":             ("Código", None),
    "descripcion":        ("Descripción", None),
    "activo":             ("Activo", None),
    "limite":             ("Límite", None),
    "es_etp":             ("Especie ETP", "Especie protegida (tortugas, mamíferos, aves…)."),
    "grupo_taxonomico":   ("Grupo taxonómico", None),
    "iniciales":          ("Iniciales", None),
    "longitud_maxima_cm": ("Longitud máxima (cm)", "Tallas mayores a esto se marcan como sospechosas."),
    "rfc":                ("RFC", None),
    "tipo_lugar_muestreo": ("Tipo de lugar de muestreo", None),
    "ubicacion":          ("Ubicación", None),
    "id":                 ("ID", None),
    "created_at":         ("Creado el", None),
    "updated_at":         ("Actualizado el", None),
    "propuesto_por":      ("Propuesto por (sesión)", None),
    "propuesto_at":       ("Propuesto el", None),
}


def _col_label(name: str) -> str:
    if name in COLUMN_LABELS:
        return COLUMN_LABELS[name][0]
    return name.removesuffix("_id").replace("_", " ").capitalize()


def _col_help(name: str, nullable: bool) -> str | None:
    h = COLUMN_LABELS.get(name, (None, None))[1]
    if not nullable:
        return ("Obligatorio. " + h) if h else "Obligatorio."
    return h


def _name_col(tabla: str) -> str:
    return NAME_COL.get(tabla, "nombre")


@st.cache_data(ttl=300, show_spinner=False)
def editable_tables() -> list[str]:
    return [r["table_name"] for r in _q(
        """SELECT table_name FROM information_schema.tables
           WHERE table_schema='public' AND table_name LIKE 'cat\\_%' ORDER BY table_name""")]


@st.cache_data(ttl=300, show_spinner=False)
def _enum_values(udt: str) -> list[str]:
    return [r["v"] for r in _q(
        """SELECT e.enumlabel AS v FROM pg_enum e JOIN pg_type t ON t.oid=e.enumtypid
           WHERE t.typname=%s ORDER BY e.enumsortorder""", (udt,))]


@st.cache_data(ttl=300, show_spinner=False)
def column_meta(tabla: str) -> list[dict]:
    cols = _q("""SELECT column_name, data_type, udt_name, is_nullable
                 FROM information_schema.columns
                 WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position""", (tabla,))
    fks = _q("""SELECT kcu.column_name AS c, ccu.table_name AS ref
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name=kcu.constraint_name AND tc.table_schema=kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                  ON tc.constraint_name=ccu.constraint_name AND tc.table_schema=ccu.table_schema
                WHERE tc.constraint_type='FOREIGN KEY' AND tc.table_schema='public'
                  AND tc.table_name=%s""", (tabla,))
    fkmap = {f["c"]: f["ref"] for f in fks}
    out = []
    for c in cols:
        name, dt = c["column_name"], c["data_type"]
        m = {"name": name, "nullable": c["is_nullable"] == "YES"}
        if name in SYSTEM_RO:
            m["kind"] = "ro"
        elif name in fkmap:
            m["kind"], m["fk"] = "fk", fkmap[name]
        elif dt == "USER-DEFINED":
            m["kind"], m["enum"] = "enum", _enum_values(c["udt_name"])
        elif dt == "boolean":
            m["kind"] = "bool"
        elif dt in ("integer", "smallint", "bigint", "numeric", "double precision", "real"):
            m["kind"], m["int"] = "num", dt in ("integer", "smallint", "bigint")
        else:
            m["kind"] = "text"
        out.append(m)
    return out


FK_CAP = 5000


@st.cache_data(ttl=120, show_spinner=False)
def fk_options(ref_table: str) -> list[dict]:
    nc = _name_col(ref_table)
    return _q(f'SELECT id::text AS id, {nc} AS nombre FROM public."{ref_table}" ORDER BY {nc} LIMIT %s',
              (FK_CAP,))


def fk_search_options(ref_table: str, q: str, cur_val) -> list[dict]:
    """Filtered options for an oversized FK catalog; keeps the current value visible."""
    nc = _name_col(ref_table)
    opts = _q(f'SELECT id::text AS id, {nc} AS nombre FROM public."{ref_table}" '
              f'WHERE {nc} ILIKE %s ORDER BY {nc} LIMIT 200', (f"%{q.strip()}%",))
    if cur_val and cur_val not in {o["id"] for o in opts}:
        opts = _q(f'SELECT id::text AS id, {nc} AS nombre FROM public."{ref_table}" WHERE id=%s',
                  (cur_val,)) + opts
    return opts


def search_rows(tabla: str, q: str) -> list[dict]:
    nc = _name_col(tabla)
    if q.strip():
        return _q(f'SELECT id::text AS id, {nc} AS nombre FROM public."{tabla}" '
                  f'WHERE {nc} ILIKE %s ORDER BY {nc} LIMIT 200', (f"%{q.strip()}%",))
    return _q(f'SELECT id::text AS id, {nc} AS nombre FROM public."{tabla}" ORDER BY {nc} LIMIT 200')


def load_row(tabla: str, rid: str) -> dict:
    return _q(f'SELECT * FROM public."{tabla}" WHERE id=%s', (rid,))[0]


def save_row(tabla: str, meta: list[dict], rid: str | None, values: dict) -> str:
    """Insert (rid is None) or update; log each field change to cambio_catalogo."""
    editable = [m["name"] for m in meta if m["kind"] != "ro"]
    if rid is None:
        new_id = str(uuid.uuid4())
        cols = ["id"] + [c for c in editable if values.get(c) is not None]
        vals = [new_id] + [values[c] for c in editable if values.get(c) is not None]
        collist = ", ".join('"' + c + '"' for c in cols)
        ph = ", ".join(["%s"] * len(vals))
        _exec(f'INSERT INTO public."{tabla}" ({collist}) VALUES ({ph})', vals)
        _log(tabla, new_id, "crear", {c: values.get(c) for c in editable if values.get(c) is not None})
        return new_id
    # update: only changed columns
    cur = load_row(tabla, rid)
    changed = {c: values.get(c) for c in editable if values.get(c) != cur.get(c)}
    if not changed:
        return rid
    sets = ", ".join(f'"{c}"=%s' for c in changed)
    _exec(f'UPDATE public."{tabla}" SET {sets} WHERE id=%s', list(changed.values()) + [rid])
    for c, v in changed.items():
        _log(tabla, rid, "editar", {"campo": c, "antes": cur.get(c), "despues": v})
    return rid


def delete_row(tabla: str, rid: str, nombre: str):
    _exec(f'DELETE FROM public."{tabla}" WHERE id=%s', (rid,))
    _log(tabla, rid, "eliminar", {"nombre": nombre})


# =====================================================================
# UI
# =====================================================================
def render_catalog_admin():
    from console_ui import page_header, friendly_error, confirm_button, flash
    page_header(
        "✏️ Catálogos",
        "Corrige o da de alta entradas de los catálogos (especies, pescadores, sitios…).",
        help_md=(
            "1. Elige el **catálogo** y busca la entrada por nombre.\n"
            "2. Corrige los campos y pulsa **💾 Guardar** (o elige «➕ Nueva entrada» "
            "para dar de alta).\n"
            "3. Una entrada usada por registros de pesca **no se puede eliminar** — para "
            "unir dos entradas repetidas usa **📥 Propuestas de campo → Fusionar**.\n\n"
            "Cada cambio queda registrado en la bitácora."
        ),
    )

    try:
        tablas = editable_tables()
    except Exception as e:  # noqa: BLE001
        st.error(f"No se pudo conectar a la base de datos: {e}")
        st.info("Configura DATABASE_URL (env o .env). Ver Planning/supabase/TODO.md.")
        return

    from app import TABLE_LABELS
    tabla = st.selectbox("Catálogo", tablas, key="ca_tabla",
                         format_func=lambda t: TABLE_LABELS.get(
                             t, t.removeprefix("cat_").replace("_", " ").capitalize()))
    meta = column_meta(tabla)
    q = st.text_input("Buscar", key="ca_q", placeholder="nombre…")
    rows = search_rows(tabla, q)
    rmap = {r["id"]: r["nombre"] for r in rows}

    NEW = "__new__"
    pick = st.selectbox(
        f"Registro  ({len(rows)} encontrados)", [NEW] + [r["id"] for r in rows],
        format_func=lambda i: "➕ Nueva entrada" if i == NEW else (rmap.get(i) or i), key="ca_row")
    is_new = pick == NEW
    current = {} if is_new else load_row(tabla, pick)

    st.divider()

    # Oversized FK catalogs can't ship every option to a selectbox: give those a
    # live search box (outside the form so it filters while typing).
    fk_query: dict[str, str] = {}
    for m in meta:
        if m["kind"] == "fk" and len(fk_options(m["fk"])) >= FK_CAP:
            st.warning(f"El catálogo de «{_col_label(m['name'])}» es muy grande para "
                       "mostrarlo completo — escribe para buscar la entrada.")
            fk_query[m["name"]] = st.text_input(
                f"Buscar {_col_label(m['name']).lower()}", key=f"ca_fkq_{tabla}_{m['name']}")

    values: dict = {}
    with st.form(key=f"ca_form_{tabla}_{pick}"):
        ro_meta = [m for m in meta if m["kind"] == "ro"]
        for m in meta:
            name, kind = m["name"], m["kind"]
            if kind == "ro":
                continue
            cur_val = current.get(name)
            label = _col_label(name) + ("" if m.get("nullable", True) else " *")
            helptxt = _col_help(name, m.get("nullable", True))
            if kind == "fk":
                if name in fk_query:
                    opts = fk_search_options(m["fk"], fk_query[name], cur_val)
                else:
                    opts = fk_options(m["fk"])
                omap = {o["id"]: o["nombre"] for o in opts}
                ids = [None] + [o["id"] for o in opts]
                idx = ids.index(cur_val) if cur_val in ids else 0
                values[name] = st.selectbox(
                    label, ids, index=idx,
                    format_func=lambda i, mm=omap: "— (vacío) —" if i is None else mm.get(i, i),
                    key=f"ca_{name}", help=helptxt)
            elif kind == "enum":
                ids = ([None] if m["nullable"] else []) + m["enum"]
                idx = ids.index(cur_val) if cur_val in ids else 0
                values[name] = st.selectbox(label, ids, index=idx,
                                            format_func=lambda v: "— (vacío) —" if v is None else v,
                                            key=f"ca_{name}", help=helptxt)
            elif kind == "bool":
                values[name] = st.checkbox(label, value=bool(cur_val), key=f"ca_{name}", help=helptxt)
            elif kind == "num":
                v = st.text_input(label, value="" if cur_val is None else str(cur_val),
                                  key=f"ca_{name}", help=helptxt)
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
                                  key=f"ca_{name}", help=helptxt)
                values[name] = v if v.strip() != "" else None
        if not is_new and ro_meta:
            with st.expander("🔧 Datos del sistema (solo lectura)"):
                for m in ro_meta:
                    cur_val = current.get(m["name"])
                    st.text_input(_col_label(m["name"]),
                                  value=str(cur_val) if cur_val is not None else "",
                                  disabled=True, key=f"ca_{m['name']}")
        submitted = st.form_submit_button("💾 Guardar", use_container_width=True)

    if submitted:
        # required-field check (NOT NULL editable cols)
        missing = [_col_label(m["name"]) for m in meta
                   if m["kind"] not in ("ro",) and not m.get("nullable")
                   and values.get(m["name"]) in (None, "")]
        if missing:
            st.error("Faltan campos obligatorios: " + ", ".join(missing))
        else:
            try:
                rid = save_row(tabla, meta, None if is_new else pick, values)
                flash("Entrada creada." if is_new else "Cambios guardados.")
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(friendly_error(e))

    if not is_new:
        st.divider()
        detail = dependents_detail(tabla, pick)
        if detail:
            dep = sum(n for _, n in detail)
            st.info(f"🔒 Esta entrada está en uso por **{dep}** registro(s): " +
                    " · ".join(f"{n} en `{t}`" for t, n in detail) +
                    ". No se puede eliminar. Para consolidar dos entradas repetidas, usa "
                    "**📥 Propuestas de campo → Fusionar**.")
        else:
            if confirm_button("🗑️ Eliminar", key=f"ca_del_{pick}",
                              help="Elimina la entrada de forma definitiva."):
                try:
                    delete_row(tabla, pick, rmap.get(pick) or pick)
                    flash("Entrada eliminada.", "🗑️")
                    st.rerun()
                except Exception as e:  # noqa: BLE001
                    st.error(friendly_error(e))
