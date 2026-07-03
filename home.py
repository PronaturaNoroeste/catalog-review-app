"""
🏠 Inicio — landing screen + grouped sidebar navigation (plan.md Phase 1).

The home screen orients a non-technical admin: a greeting, cards with the
pending work (propuestas de campo, duplicados por revisar, borradores de
formulario) and quick-action buttons that jump to the right mode.

The sidebar nav replaces the old single radio with grouped buttons
(REVISAR / CONFIGURAR / DATOS). Labels stay static — no live badges — so the
widgets never desync across reruns (see the dup_catalog note in app.py).
"""
from __future__ import annotations

import streamlit as st

# mode id -> (label, group). Group None = ungrouped (Inicio).
NAV = [
    ("inicio",       "🏠 Inicio",                None),
    ("catalogos",    "🔎 Duplicados",            "REVISAR"),
    ("propuestas",   "📥 Propuestas de campo",   "REVISAR"),
    ("editar",       "✏️ Catálogos",             "CONFIGURAR"),
    ("formularios",  "🛠️ Formularios",           "CONFIGURAR"),
    ("listas",       "📑 Listas del formulario", "CONFIGURAR"),
    ("usuarios",     "👤 Usuarios",              "CONFIGURAR"),
    ("exportar",     "📤 Descargar datos",       "DATOS"),
]
ANALISTA_MODES = {"inicio", "exportar"}


def modes_for(rol: str) -> list[str]:
    if rol == "ADMINISTRADOR":
        return [m for m, _, _ in NAV]
    return [m for m, _, _ in NAV if m in ANALISTA_MODES]


def render_sidebar_nav(rol: str) -> str:
    """Grouped button nav. Persists the choice in session_state['console_mode']."""
    allowed = modes_for(rol)
    cur = st.session_state.get("console_mode") or "inicio"
    if cur not in allowed:
        cur = "inicio"
        st.session_state["console_mode"] = cur

    last_group = None
    for mode, label, group in NAV:
        if mode not in allowed:
            continue
        if group != last_group and group is not None:
            st.sidebar.caption(group)
        last_group = group
        if st.sidebar.button(label, key=f"nav_{mode}", use_container_width=True,
                             type="primary" if mode == cur else "secondary"):
            st.session_state["console_mode"] = mode
            st.rerun()
    return cur


# ---------------------------------------------------------------------------
# Pending-work counts (each safe on its own: a failure shows "—", not a crash)
# ---------------------------------------------------------------------------
def _count_propuestas() -> int:
    from proposals_review import proposable_tables
    from form_builder import _q
    total = 0
    for t in proposable_tables():
        total += _q(f'SELECT count(*) AS n FROM public."{t}" WHERE estado=\'pendiente\'')[0]["n"]
    return total


def _count_duplicados() -> int:
    """Undecided flagged pairs across the catalog CSVs (dedup review)."""
    import app as _app
    pending = 0
    for t in _app.NAME_COLS:
        if not (_app.EXPORT_DIR / f"{t}.csv").exists():
            continue
        done, total = _app.progress(_app.table_pairs(t), _app.load_decisions(t))
        pending += total - done
    return pending


def _count_borradores() -> int:
    from form_builder import _q
    return _q("SELECT count(*) AS n FROM formulario WHERE estado='borrador'")[0]["n"]


def _card(col, titulo: str, count, desc: str, boton: str, mode: str, icon: str):
    with col.container(border=True):
        st.markdown(f"#### {icon} {titulo}")
        st.metric(titulo, "—" if count is None else count, label_visibility="collapsed")
        st.caption(desc)
        if st.button(boton, key=f"home_go_{mode}", use_container_width=True,
                     type="primary" if isinstance(count, int) and count > 0 else "secondary"):
            st.session_state["console_mode"] = mode
            st.rerun()


def render_home(rol: str):
    nombre = st.session_state.get("auth_nombre") or ""
    st.title(f"Hola{', ' + nombre if nombre else ''} 👋")

    if rol != "ADMINISTRADOR":
        st.caption("Desde aquí puedes descargar los datos del monitoreo para analizarlos.")
        with st.container(border=True):
            st.markdown("#### 📤 Descargar datos")
            st.caption("Extrae mediciones, capturas, faenas o interacciones ETP a un archivo "
                       "CSV para abrirlo en Excel o R.")
            if st.button("Ir a Descargar datos", key="home_go_exportar", type="primary"):
                st.session_state["console_mode"] = "exportar"
                st.rerun()
        return

    st.caption("Este es el trabajo pendiente. Entra a cada sección con el botón, "
               "o usa el menú de la izquierda.")

    counts = {}
    errs = []
    for name, fn in (("propuestas", _count_propuestas),
                     ("duplicados", _count_duplicados),
                     ("borradores", _count_borradores)):
        try:
            counts[name] = fn()
        except Exception as e:  # noqa: BLE001
            counts[name] = None
            errs.append(str(e))
    if errs:
        st.warning("No se pudo consultar la base de datos para algunos contadores. "
                   "Revisa la conexión (.env).")

    c1, c2, c3 = st.columns(3)
    _card(c1, "Propuestas de campo", counts["propuestas"],
          "Nombres nuevos que los técnicos propusieron desde la tableta y "
          "esperan tu aprobación.",
          "Revisar propuestas", "propuestas", "📥")
    _card(c2, "Duplicados por revisar", counts["duplicados"],
          "Pares de nombres del catálogo que se parecen y falta decidir si son "
          "el mismo registro.",
          "Revisar duplicados", "catalogos", "🔎")
    _card(c3, "Formularios en borrador", counts["borradores"],
          "Versiones de formulario guardadas pero aún no publicadas para la tableta.",
          "Abrir formularios", "formularios", "🛠️")

    st.divider()
    st.markdown("##### ¿Qué hace cada sección?")
    st.markdown(
        "- **🔎 Duplicados** — limpiar el catálogo: decidir si dos nombres parecidos son lo mismo.\n"
        "- **📥 Propuestas de campo** — aprobar, rechazar o fusionar los nombres que proponen los técnicos.\n"
        "- **✏️ Catálogos** — corregir o dar de alta entradas de los catálogos (especies, pescadores…).\n"
        "- **🛠️ Formularios** — editar y publicar las versiones del formulario de la tableta.\n"
        "- **📑 Listas del formulario** — subir las listas limpias de opciones que ve el técnico.\n"
        "- **👤 Usuarios** — crear cuentas y administrar quién entra a la consola y a la tableta.\n"
        "- **📤 Descargar datos** — extraer los datos a CSV para analizarlos en Excel o R."
    )
