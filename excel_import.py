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
