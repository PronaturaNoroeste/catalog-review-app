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

# Tablas de vocabulario cerrado, sin flujo de aprobación (mismo conjunto que
# SIN_APROBACION en la app de captura, catalogMirror.ts) — no tienen columna estado.
SIN_APROBACION = {
    "cat_tipo_gasto", "cat_tipo_interaccion_etp",
    "cat_tipo_viento", "cat_tipo_luna", "cat_tipo_marea", "cat_region", "cat_formato_origen",
}


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
    """Rows whose name (or científico) contains `q`, accent- and
    case-insensitive. Filters in Python with _norm — the exact normalization
    the import tool and the tablet use; catalogs are small enough to scan
    (lista_import builds full in-memory maps the same way). Restricted to
    estado='aprobado' rows: the tablet mirrors approved rows only, so an
    unapproved option would silently vanish from the picker. Closed-vocabulary
    catalogs (SIN_APROBACION) have no estado column, so all their rows qualify."""
    if not (q or "").strip():
        return []
    nc = _name_col(tabla)
    sci = ", nombre_cientifico AS cientifico" if tabla == "cat_especie" else ""
    where = "" if tabla in SIN_APROBACION else " WHERE estado='aprobado'"
    rows = _q(f'SELECT id::text AS id, {nc} AS nombre{sci} FROM public."{tabla}"'
              f"{where}")
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

    lista_actual = st.session_state.get(f"{key}_pin", "") or lista_actual

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
        if lista in existentes:
            st.info(f"«{lista}» ya existe para este formato — el campo compartirá esa lista.")
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
                        else:
                            imp = row["importancia"]
                            imp = (orig[rid]["importancia"] if pd.isna(imp)
                                   else int(imp))
                            if imp != orig[rid]["importancia"]:
                                set_importancia(formato_id, lista, rid, imp)
                    st.session_state[f"{key}_pin"] = lista
                    st.rerun(scope="fragment")
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
                        st.session_state[f"{key}_pin"] = lista
                        st.rerun(scope="fragment")
                    except Exception as e:  # noqa: BLE001
                        st.error(friendly_error(e))
            else:
                st.caption("Sin coincidencias en el catálogo.")
            if tabla not in SIN_APROBACION:
                sci_in = (st.text_input("Nombre científico (opcional, para crear)",
                                        key=f"{key}_sci") if es_especie else None)
                if st.button(f"🆕 Crear «{q.strip()}» y añadir", key=f"{key}_new",
                             help="Crea un registro nuevo aprobado en el catálogo — "
                                  "nunca fusiona con los existentes."):
                    try:
                        create_and_add(formato_id, lista, tabla, q.strip(), sci_in)
                        st.session_state[f"{key}_pin"] = lista
                        st.rerun(scope="fragment")
                    except Exception as e:  # noqa: BLE001
                        st.error(friendly_error(e))
    return lista
