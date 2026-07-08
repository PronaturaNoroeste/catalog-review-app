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
