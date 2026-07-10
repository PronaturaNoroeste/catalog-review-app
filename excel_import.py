"""📥 Importar Excel — bulk load of Anexo 2 production workbooks (R5).

A 4-step wizard (subir → mapear catálogos → previsualizar → confirmar) that loads
Masivos/Bitácoras rows into faena + children. Orchestration + UI only; parsing lives
in import_formats, catalog resolution in catalog_resolver, insertion in import_writer.
"""
from __future__ import annotations
import streamlit as st

import import_formats as IF
import catalog_resolver as R

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
    import openpyxl
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
            if kind == "new":
                mapping[(catalog, raw)] = ("__NEW__", raw)
            elif kind == "desc":
                mapping[(catalog, raw)] = ("__DESC__", catalog)
            else:
                mapping[(catalog, raw)] = val
    st.caption(f"{unresolved} valor(es) por confirmar. Especies se resuelven por par común+científico "
               "en la vista previa.")
    c1, c2 = st.columns(2)
    if c1.button("← Volver"):
        st.session_state["imp_step"] = 0; st.rerun()
    if c2.button("Previsualizar →", type="primary"):
        st.session_state["imp_step"] = 2; st.rerun()


def _step3_preview():
    st.info("Paso 3 en construcción.")          # replaced in Task 8


def _step4_commit():
    st.info("Paso 4 en construcción.")          # replaced in Task 8
