"""
📑 Listas curadas por formato (AppDashboardSpec/16) — import a clean, form-specific
option list (CSV) into `lista_opcion`, so the capture app's picker draws a strict
curated subset instead of the messy full catalog.

Matching (reuse-&-clean, but SAFE — no blind merges):
  - **cat_especie**: match on the (common name + scientific name) pair, normalized.
    A common name alone is ambiguous — the DB holds homonyms (e.g. "Bonito" =
    *Caranx caballus* AND *Sarda chiliensis*), so we NEVER merge by common name. A
    pair-match → link (rename strings to the clean version, id preserved so historical
    faena FK refs survive). No pair-match → create a new APPROVED species. When the
    curated scientific name is blank we fall back to common-name match (link the lone
    match, else flag ambiguous, else create).
  - **cat_pescador** (no scientific discriminator): single normalized-name match →
    link/rename; multiple → link one + flag (same-name fishers may be different
    people — never merge); none → create.
Then upsert `lista_opcion` with `importancia`. The pescadores list also resolves/
creates each cooperativa and sets `cat_pescador.cooperativa_id`.

Reuses the form_builder DB layer + catalog_admin audit helpers.
"""
from __future__ import annotations

import unicodedata
import uuid

import pandas as pd
import streamlit as st

from form_builder import _q, _exec, _log, list_formatos

PRESETS = {
    "especies":   {"tabla": "cat_especie",  "carnada": False, "importancia": True,  "cooperativa": False},
    "carnada":    {"tabla": "cat_especie",  "carnada": True,  "importancia": False, "cooperativa": False},
    "pescadores": {"tabla": "cat_pescador", "carnada": False, "importancia": False, "cooperativa": True},
}
NAME_COL = {"cat_especie": "nombre_comun"}   # else 'nombre'


def _name_col(tabla: str) -> str:
    return NAME_COL.get(tabla, "nombre")


def _norm(s) -> str:
    """Mirror the capture app's norm(): NFD + strip diacritics + lower + strip."""
    s = unicodedata.normalize("NFD", str(s or ""))
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn").strip().lower()


# ---- catalog indexes (built once per apply/dry-run; catalog is small) ----
def _especie_maps():
    pair, common = {}, {}
    for r in _q("SELECT id::text AS id, nombre_comun AS n, nombre_cientifico AS sci FROM cat_especie"):
        pair[(_norm(r["n"]), _norm(r["sci"]))] = r
        common.setdefault(_norm(r["n"]), []).append(r)
    return pair, common


def _pescador_map():
    m: dict[str, list] = {}
    for r in _q("SELECT id::text AS id, nombre AS n FROM cat_pescador"):
        m.setdefault(_norm(r["n"]), []).append(r)
    return m


def _classify_especie(pair, common, name, sci):
    """→ (accion, id|None, current_name|None). accion ∈ crear|enlazar|renombrar|ambiguo."""
    if sci:
        row = pair.get((_norm(name), _norm(sci)))
        if row:
            return ("enlazar" if row["n"] == name and row["sci"] == sci else "renombrar"), row["id"], row["n"]
        # no exact pair; reuse a same-common-name row whose sci is still 'Pendiente'
        # (the incomplete version of this species) instead of creating a near-dup.
        pend = [r for r in common.get(_norm(name), []) if r["sci"] == "Pendiente"]
        if len(pend) == 1:
            return ("enlazar" if pend[0]["n"] == name else "renombrar"), pend[0]["id"], pend[0]["n"]
        return "crear", None, None                       # distinct species (name may exist w/ other sci)
    ms = common.get(_norm(name), [])
    if not ms:
        return "crear", None, None
    if len(ms) == 1:
        return ("enlazar" if ms[0]["n"] == name else "renombrar"), ms[0]["id"], ms[0]["n"]
    pend = [r for r in ms if r["sci"] == "Pendiente"]     # prefer the placeholder-sci row
    row = pend[0] if len(pend) == 1 else ms[0]
    return "ambiguo", row["id"], row["n"]


def _classify_pescador(idx, name):
    ms = idx.get(_norm(name), [])
    if not ms:
        return "crear", None, None
    if len(ms) == 1:
        return ("enlazar" if ms[0]["n"] == name else "renombrar"), ms[0]["id"], ms[0]["n"]
    return "ambiguo", ms[0]["id"], ms[0]["n"]             # same-name fishers → link first, flag


# ---- cooperativa resolution (pescadores) ----
def _coop_index() -> dict[str, str]:
    return {_norm(r["nombre"]): r["id"] for r in _q("SELECT id::text AS id, nombre FROM cat_cooperativa")}


def _resolve_coop(name, idx: dict) -> str | None:
    if not name or not str(name).strip():
        return None
    key = _norm(name)
    if key in idx:
        return idx[key]
    cid = str(uuid.uuid4())
    _exec("INSERT INTO cat_cooperativa (id, nombre, es_aprobado) VALUES (%s,%s,true)", (cid, str(name).strip()))
    idx[key] = cid
    _log("cat_cooperativa", cid, "crear", {"nombre": str(name).strip(), "origen": "lista"})
    return cid


# ---- apply one classified row ----
def _apply_row(tabla, lista, carnada, formato_id, name, sci, importancia, accion, rid, cur_name, coop_id):
    nc = _name_col(tabla)
    if accion == "crear":
        rid = str(uuid.uuid4())
        cols, vals = ["id", nc, "es_aprobado", "estado"], [rid, name, True, "aprobado"]
        if tabla == "cat_especie":
            cols += ["nombre_cientifico", "apta_carnada"]
            vals += [(sci or "Pendiente"), bool(carnada)]
        _exec(f'INSERT INTO public."{tabla}" ({", ".join(cols)}) VALUES ({", ".join(["%s"] * len(vals))})', vals)
        _log(tabla, rid, "crear", {"nombre": name, "origen": "lista"})
    elif accion == "renombrar":
        _exec(f'UPDATE public."{tabla}" SET {nc}=%s WHERE id=%s', (name, rid))
        _log(tabla, rid, "editar", {"campo": nc, "antes": cur_name, "despues": name})
    # 'enlazar' / 'ambiguo' → link the existing id as-is

    if tabla == "cat_especie" and carnada:
        _exec("UPDATE cat_especie SET apta_carnada=true WHERE id=%s", (rid,))
    if tabla == "cat_especie" and sci and accion != "crear":
        _exec("UPDATE cat_especie SET nombre_cientifico=%s WHERE id=%s AND nombre_cientifico='Pendiente'", (sci, rid))
    if tabla == "cat_pescador" and coop_id:
        try:
            _exec("UPDATE cat_pescador SET cooperativa_id=%s WHERE id=%s", (coop_id, rid))
        except Exception:  # noqa: BLE001  UNIQUE(nombre,cooperativa_id) — leave as-is
            pass

    _exec("""INSERT INTO lista_opcion (formato_origen_id, lista, tabla, registro_id, importancia)
             VALUES (%s,%s,%s,%s,%s)
             ON CONFLICT (formato_origen_id, lista, registro_id) DO UPDATE SET importancia=EXCLUDED.importancia""",
          (formato_id, lista, tabla, rid, int(importancia or 0)))


# =====================================================================
# UI
# =====================================================================
def render_lista_import():
    st.title("📑 Listas curadas por formato")
    st.caption("Sube la lista limpia de opciones de un formulario (CSV). El catálogo se reutiliza y "
               "limpia por NOMBRE+CIENTÍFICO (nunca fusiona homónimos); las opciones del formulario "
               "salen de aquí. Ver AppDashboardSpec/16.")

    try:
        formatos = list_formatos()
    except Exception as e:  # noqa: BLE001
        st.error(f"No se pudo conectar a la base de datos: {e}"); return

    c1, c2 = st.columns(2)
    fmap = {f["id"]: f["codigo"] for f in formatos}
    formato_id = c1.selectbox("Formulario (formato)", list(fmap), format_func=lambda i: fmap[i], key="li_fmt")
    lista = c2.selectbox("Lista", list(PRESETS), key="li_lista")
    cfg = PRESETS[lista]; tabla = cfg["tabla"]
    st.caption(f"Destino: **{tabla}**" + (" · marca apta_carnada" if cfg["carnada"] else ""))

    up = st.file_uploader("CSV de la lista", type=["csv"], key="li_csv")
    if not up:
        st.info("Sube un CSV (p.ej. Especies_BA.csv, Carnada_BA.csv, Pescadores_BA.csv).")
        return
    try:
        df = pd.read_csv(up).fillna("")
    except Exception as e:  # noqa: BLE001
        st.error(f"No se pudo leer el CSV: {e}"); return
    st.caption(f"{len(df)} filas · columnas: {', '.join(df.columns)}")

    cols = list(df.columns)
    m1, m2, m3, m4 = st.columns(4)
    col_name = m1.selectbox("Columna nombre", cols, key="li_name")
    col_sci = (m2.selectbox("Nombre científico", ["—"] + cols, key="li_sci")
               if tabla == "cat_especie" else "—")
    col_imp = m3.selectbox("Importancia", ["—"] + cols, key="li_imp") if cfg["importancia"] else "—"
    col_coop = m4.selectbox("Cooperativa", ["—"] + cols, key="li_coop") if cfg["cooperativa"] else "—"

    rows = []
    for _, r in df.iterrows():
        nm = str(r[col_name]).strip()
        if not nm:
            continue
        rows.append({"nombre": nm,
                     "sci": str(r[col_sci]).strip() if col_sci != "—" else "",
                     "imp": r[col_imp] if col_imp != "—" else 0,
                     "coop": str(r[col_coop]).strip() if col_coop != "—" else ""})

    # ---- classify (dry-run) ----
    if tabla == "cat_especie":
        pair, common = _especie_maps()
        classify = lambda r: _classify_especie(pair, common, r["nombre"], r["sci"])
    else:
        pmap = _pescador_map()
        classify = lambda r: _classify_pescador(pmap, r["nombre"])

    prev, counts = [], {"crear": 0, "enlazar": 0, "renombrar": 0, "ambiguo": 0}
    for r in rows:
        accion, rid, cur = classify(r)
        r["_c"] = (accion, rid, cur)
        counts[accion] += 1
        prev.append({"nombre": r["nombre"], "científico": r["sci"], "acción": accion,
                     "actual": cur or "", "coop": r["coop"], "imp": r["imp"]})

    st.subheader("Vista previa")
    m = st.columns(4)
    m[0].metric("Crear", counts["crear"]); m[1].metric("Enlazar", counts["enlazar"])
    m[2].metric("Renombrar", counts["renombrar"]); m[3].metric("Ambiguo", counts["ambiguo"])
    if counts["ambiguo"]:
        st.warning(f"{counts['ambiguo']} fila(s) ambiguas (varios registros con el mismo nombre) — se "
                   "enlaza uno; revísalas.")
    st.dataframe(pd.DataFrame(prev), use_container_width=True, height=300)

    st.divider()
    if st.button(f"✅ Aplicar {len(rows)} opciones a «{lista}»", type="primary", key="li_apply"):
        coop_idx = _coop_index() if cfg["cooperativa"] else {}
        prog = st.progress(0.0)
        done = {"crear": 0, "enlazar": 0, "renombrar": 0, "ambiguo": 0}
        for i, r in enumerate(rows):
            accion, rid, cur = r["_c"]
            coop_id = _resolve_coop(r["coop"], coop_idx) if cfg["cooperativa"] else None
            try:
                _apply_row(tabla, lista, cfg["carnada"], formato_id, r["nombre"], r["sci"], r["imp"],
                           accion, rid, cur, coop_id)
                done[accion] += 1
            except Exception as e:  # noqa: BLE001
                st.warning(f"«{r['nombre']}»: {e}")
            prog.progress((i + 1) / max(len(rows), 1))
        total = _q("SELECT count(*) AS n FROM lista_opcion WHERE formato_origen_id=%s AND lista=%s",
                   (formato_id, lista))[0]["n"]
        st.success(f"Aplicado a «{lista}»: {done}. Total en la lista: {total}.")
