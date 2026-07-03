"""
Console login gate (AppDashboardSpec/15 #3). Supabase Auth password grant + a
`rol` check: ADMINISTRADOR → all modes, ANALISTA → export only. The console keeps
its privileged DB connection for operations behind this gate (the decided
"login-gated service connection").

Bootstrap escape: if NO active ADMINISTRADOR exists yet, the console is open
(initial setup) so you can create the first admin — otherwise you'd lock yourself
out before any admin exists.
"""
from __future__ import annotations

import requests
import streamlit as st

from form_builder import _q
from console_config import SUPABASE_URL, SUPABASE_ANON_KEY

CONSOLE_ROLES = ("ADMINISTRADOR", "ANALISTA")


def _password_grant(email: str, password: str) -> dict:
    r = requests.post(f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
                      headers={"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"},
                      json={"email": email, "password": password}, timeout=20)
    if r.status_code >= 300:
        raise RuntimeError("Credenciales inválidas.")
    return r.json()


def _rol_of(uid: str):
    rows = _q("SELECT rol::text AS rol, nombre FROM usuario WHERE id=%s AND activo", (uid,))
    return (rows[0]["rol"], rows[0]["nombre"]) if rows else (None, None)


def _admins_exist() -> bool:
    try:
        return _q("SELECT count(*) AS n FROM usuario WHERE rol='ADMINISTRADOR' AND activo")[0]["n"] > 0
    except Exception:  # noqa: BLE001
        return True   # fail safe: if we can't check, require a login


def require_login() -> tuple[str, str]:
    """Return (rol, nombre). Renders a login form and st.stop()s if not authed."""
    if st.session_state.get("auth_rol"):
        return st.session_state["auth_rol"], st.session_state.get("auth_nombre", "")

    if not _admins_exist():
        st.session_state["auth_rol"] = "ADMINISTRADOR"
        st.session_state["auth_nombre"] = "(configuración inicial)"
        st.warning("Sin administradores aún — consola abierta para crear el primer admin (👤 Usuarios).")
        return "ADMINISTRADOR", "(configuración inicial)"

    st.title("🔐 Consola de monitoreo")
    st.caption("Inicia sesión con tu correo y contraseña.")
    with st.popover("❓ ¿Quién puede entrar?"):
        from users_admin import ROLES_MD
        st.markdown(ROLES_MD)
        st.caption("Si no tienes cuenta, pídesela a un administrador.")
    email = st.text_input("Correo", key="login_email")
    pw = st.text_input("Contraseña", key="login_pass", type="password")
    if st.button("Entrar", type="primary", disabled=not (email and pw), key="login_btn"):
        try:
            data = _password_grant(email.strip(), pw)
            rol, nombre = _rol_of(data["user"]["id"])
            if rol not in CONSOLE_ROLES:
                st.error("Esta cuenta no tiene acceso a la consola (se requiere ADMINISTRADOR o ANALISTA).")
            else:
                st.session_state["auth_rol"] = rol
                st.session_state["auth_nombre"] = nombre
                st.rerun()
        except Exception as e:  # noqa: BLE001
            st.error(f"No se pudo iniciar sesión: {e}")
    st.stop()


def logout_button():
    # Plain button, no confirm: a stray click only costs a re-login, and the
    # popover confirm rendered unreadably on the Tide sidebar.
    if st.sidebar.button("🚪 Salir", key="console_logout", use_container_width=True):
        for k in ("auth_rol", "auth_nombre"):
            st.session_state.pop(k, None)
        st.rerun()
