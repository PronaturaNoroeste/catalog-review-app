"""
🔧 Constructor de descargas — combine tables for export without SQL (R2).

A guided join builder: pick a base entity, add related catalog columns (as names,
one-to-one LEFT JOINs) and related child records (one-to-many, as a **resumen**
count/sum that keeps one row per base, or as **detalle** that expands to one row per
child). Relationships are discovered from the schema's foreign keys, so every table /
column identifier is real — no free-text SQL, filters would be parameterized.

Complements the curated quick-datasets in export_data.py (kept as presets).
"""
from __future__ import annotations

import datetime as _dt

import pandas as pd
import streamlit as st

from form_builder import _q, get_conn, ENTIDAD_LABELS, _core_label

# Base data entities you can build a download around (not catalogs / audit tables).
BASE_ENTITIES = ["faena", "captura", "medicion", "faena_arte", "carnada",
                 "interaccion_etp", "gasto", "faena_especie_objetivo"]

_NAME_COL = {"cat_especie": "nombre_comun", "cat_formato_origen": "codigo"}
_NUMERIC = ("integer", "bigint", "numeric", "double precision", "real", "smallint")
MODE_LABELS = {"resumen": "Resumen (conteo / suma)", "detalle": "Detalle (una fila por registro)"}


def _label(t: str) -> str:
    return ENTIDAD_LABELS.get(t, t)


@st.cache_data(ttl=300, show_spinner=False)
def catalog_parents(base: str) -> list[dict]:
    """base's FK columns that point at a cat_* table → one-to-one 'add the name' joins."""
    rows = _q("""
        SELECT kcu.column_name AS fk_col, ccu.table_name AS ref
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema
        WHERE tc.constraint_type='FOREIGN KEY' AND tc.table_schema='public'
          AND tc.table_name=%s AND ccu.column_name='id'
        ORDER BY kcu.column_name
    """, (base,))
    out = []
    for r in rows:
        if r["ref"].startswith("cat_"):
            out.append({"fk_col": r["fk_col"], "ref": r["ref"],
                        "namecol": _NAME_COL.get(r["ref"], "nombre"),
                        "label": _core_label(f"{base}.{r['fk_col']}")})
    return out


@st.cache_data(ttl=300, show_spinner=False)
def child_relations(base: str) -> list[dict]:
    """Data tables whose FK points at base.id → one-to-many children."""
    rows = _q("""
        SELECT tc.table_name AS t, kcu.column_name AS c
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema
        WHERE tc.constraint_type='FOREIGN KEY' AND tc.table_schema='public'
          AND ccu.table_name=%s AND ccu.column_name='id'
        ORDER BY tc.table_name
    """, (base,))
    seen, out = set(), []
    for r in rows:
        if r["t"] in BASE_ENTITIES and r["t"] != base and r["t"] not in seen:
            seen.add(r["t"])
            out.append({"table": r["t"], "fk_col": r["c"], "label": _label(r["t"])})
    return out


@st.cache_data(ttl=300, show_spinner=False)
def columns_of(table: str, numeric_only: bool = False) -> list[str]:
    q = ("SELECT column_name FROM information_schema.columns "
         "WHERE table_schema='public' AND table_name=%s")
    args: tuple = (table,)
    if numeric_only:
        q += " AND data_type = ANY(%s)"
        args = (table, list(_NUMERIC))
    return [r["column_name"] for r in _q(q + " ORDER BY ordinal_position", args)]


def build_query(base: str, parents: list[dict], children: list[dict], limit: int) -> str:
    """Assemble the SQL. All identifiers come from schema discovery (safe to quote)."""
    sel = ['b.*']
    frm = [f'public."{base}" b']
    for i, p in enumerate(parents):
        a = f"p{i}"
        frm.append(f'LEFT JOIN public."{p["ref"]}" {a} ON {a}.id = b."{p["fk_col"]}"')
        sel.append(f'{a}."{p["namecol"]}" AS "{p["label"]}"')
    si = 0
    for ch in children:
        if ch["mode"] == "resumen":
            a = f"s{si}"; si += 1
            gsel = [f'"{ch["fk_col"]}" AS bid', 'count(*) AS n']
            if ch.get("sum_col"):
                gsel.append(f'sum("{ch["sum_col"]}") AS s')
            sub = f'(SELECT {", ".join(gsel)} FROM public."{ch["table"]}" GROUP BY "{ch["fk_col"]}") {a}'
            frm.append(f'LEFT JOIN {sub} ON {a}.bid = b.id')
            sel.append(f'{a}.n AS "n_{ch["label"]}"')
            if ch.get("sum_col"):
                sel.append(f'{a}.s AS "{ch["label"]}_{ch["sum_col"]}"')
        else:  # detalle (expands rows) — at most one, enforced in the UI
            frm.append(f'LEFT JOIN public."{ch["table"]}" d ON d."{ch["fk_col"]}" = b.id')
            for col in ch.get("columns", []):
                sel.append(f'd."{col}" AS "{ch["label"]}_{col}"')
    sql = f'SELECT {", ".join(sel)} FROM ' + " ".join(frm)
    if limit and limit > 0:
        sql += f" LIMIT {int(limit)}"
    return sql


def render_builder(render_results):
    st.caption("Arma tu propia descarga combinando una tabla principal con sus datos "
               "relacionados. El sistema conoce las relaciones — tú solo eliges qué incluir.")
    base = st.selectbox("Tabla principal", BASE_ENTITIES, format_func=_label, key="jb_base")

    parents = catalog_parents(base)
    children = child_relations(base)

    chosen_parents = []
    if parents:
        st.markdown("**➕ Columnas de catálogos relacionados** (se añaden como nombres)")
        cols = st.columns(3)
        for i, p in enumerate(parents):
            if cols[i % 3].checkbox(p["label"], key=f"jb_p_{base}_{p['fk_col']}"):
                chosen_parents.append(p)

    chosen_children = []
    if children:
        st.markdown("**➕ Registros relacionados** (uno a muchos)")
        for ch in children:
            with st.container(border=True):
                c = st.columns([3, 3, 4], vertical_alignment="center")
                on = c[0].checkbox(ch["label"], key=f"jb_c_{base}_{ch['table']}")
                if not on:
                    continue
                mode = c[1].radio("Cómo", list(MODE_LABELS), format_func=lambda m: MODE_LABELS[m],
                                  key=f"jb_m_{base}_{ch['table']}")
                spec = {"table": ch["table"], "fk_col": ch["fk_col"],
                        "label": ch["label"], "mode": mode}
                if mode == "resumen":
                    nums = columns_of(ch["table"], numeric_only=True)
                    spec["sum_col"] = c[2].selectbox(
                        "Sumar (opcional)", [None] + nums,
                        format_func=lambda x: "— solo contar —" if x is None else x,
                        key=f"jb_s_{base}_{ch['table']}")
                else:
                    allc = [x for x in columns_of(ch["table"]) if x not in ("id", ch["fk_col"])]
                    spec["columns"] = c[2].multiselect("Columnas a incluir", allc,
                                                       default=allc[:6],
                                                       key=f"jb_dc_{base}_{ch['table']}")
                chosen_children.append(spec)

    limit = st.number_input("Límite de filas (0 = sin límite — cuidado con tablas grandes)",
                            min_value=0, value=5000, step=1000, key="jb_limit")

    n_det = sum(1 for c in chosen_children if c["mode"] == "detalle")
    if n_det > 1:
        st.error("Solo puedes usar **Detalle** en una tabla hija a la vez (evita multiplicar "
                 "las filas). Deja las demás en **Resumen**.")
    st.caption("La tabla principal se descarga con todas sus columnas; los catálogos añaden "
               "nombres y las tablas hijas su conteo/suma (o el detalle).")

    if st.button("🔍 Generar vista previa", key="jb_run", type="primary", disabled=n_det > 1):
        sql = build_query(base, chosen_parents, chosen_children, int(limit))
        try:
            cur = get_conn().cursor()
            cur.execute(sql)
            df = pd.DataFrame(cur.fetchall(), columns=[c[0] for c in cur.description])
            cur.close()
            st.session_state["jb_df"] = df
            st.session_state["jb_name"] = f"{base}_combinado_{_dt.date.today().isoformat()}"
        except Exception as e:  # noqa: BLE001
            st.session_state.pop("jb_df", None)
            st.error(f"Error en la consulta: {e}")

    df = st.session_state.get("jb_df")
    if df is not None:
        render_results(df, st.session_state.get("jb_name", "combinado"))
