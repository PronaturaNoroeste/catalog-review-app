"""
Shared UI helpers for the admin console — plain-Spanish guidance, friendly
errors, two-step confirmations and empty states. Every mode uses these so the
console speaks one language (see plan.md Phase 0).
"""
from __future__ import annotations

import streamlit as st


def page_header(title: str, subtitle: str, help_md: str | None = None):
    """Title + one-line explanation + an optional «¿Qué es esto?» popover
    with plain-Spanish steps (2–4 bullets max, written for a non-developer)."""
    st.title(title)
    if help_md:
        c1, c2 = st.columns([5, 1])
        c1.caption(subtitle)
        with c2.popover("❓ ¿Qué es esto?", width="stretch"):
            st.markdown(help_md)
    else:
        st.caption(subtitle)


def friendly_error(e: Exception) -> str:
    """Map database errors to plain Spanish so the admin never sees raw Postgres."""
    try:
        from psycopg2 import errors as pgerrors
    except ImportError:
        return str(e)
    if isinstance(e, pgerrors.UniqueViolation):
        return ("Ya existe un registro con ese valor. Revisa si ya está en la lista "
                "antes de crear otro.")
    if isinstance(e, pgerrors.ForeignKeyViolation):
        return ("Está en uso por otros registros (faenas u otras tablas), así que no se "
                "puede guardar o eliminar de esta forma.")
    if isinstance(e, pgerrors.NotNullViolation):
        return "Falta un campo obligatorio. Llena todos los campos marcados con *."
    if isinstance(e, pgerrors.StringDataRightTruncation):
        return "El texto es demasiado largo para ese campo."
    return str(e)


def confirm_button(label: str, key: str, help: str | None = None) -> bool:
    """Two-step confirm for destructive actions: marcar «Confirmar» + botón.
    Returns True only when the button is pressed with the checkbox marked."""
    ok = st.checkbox("Confirmar", key=f"{key}_confirm", help=help)
    return st.button(label, key=key, disabled=not ok,
                     help=None if ok else "Marca «Confirmar» primero.")


def flash(msg: str, icon: str = "✅"):
    """Queue a toast that survives the st.rerun() after a save. A plain
    st.success() followed by st.rerun() never gets seen — use this instead."""
    st.session_state["_flash"] = (msg, icon)


def show_flash():
    """Render the queued toast (called once at the top of every run, in main())."""
    f = st.session_state.pop("_flash", None)
    if f:
        try:
            st.toast(f[0], icon=f[1])
        except Exception:  # noqa: BLE001 — a bad/invalid icon must never brick the whole app
            st.toast(f[0])


def empty_state(msg: str, icon: str = "✅"):
    """Friendly «no hay nada pendiente» block."""
    with st.container(border=True):
        st.markdown(
            f"<div style='text-align:center;padding:16px 0 4px;font-size:2.2rem'>{icon}</div>"
            f"<div style='text-align:center;color:#6b6760;padding-bottom:16px'>{msg}</div>",
            unsafe_allow_html=True,
        )
