"""
👤 Usuarios (M-users Phase 1, AppDashboardSpec/15) — admins create & manage accounts.

Creates the `auth.users` row via the GoTrue **admin API** (service-role key,
server-side) + the `usuario` profile in the DB. Técnicos are linked to a
`cat_tecnico` row so the capture app prefills `faena.tecnico_id`. Replaces the
manual dashboard+SQL account setup.
"""
from __future__ import annotations

import requests
import streamlit as st

from form_builder import get_conn, _q
from console_config import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

ROLES = ["TECNICO", "ADMINISTRADOR", "ANALISTA"]

ROLES_MD = (
    "- **TECNICO** — captura faenas en la tableta; no entra a esta consola.\n"
    "- **ADMINISTRADOR** — usa toda la consola: catálogos, propuestas, formularios, "
    "usuarios y descargas.\n"
    "- **ANALISTA** — solo puede **descargar datos** para analizarlos."
)


def _svc_headers() -> dict:
    k = SUPABASE_SERVICE_ROLE_KEY
    return {"apikey": k, "Authorization": f"Bearer {k}", "Content-Type": "application/json"}


def create_auth_user(email: str, password: str) -> str:
    """Create a pre-confirmed auth user; return its id."""
    r = requests.post(f"{SUPABASE_URL}/auth/v1/admin/users", headers=_svc_headers(),
                      json={"email": email, "password": password, "email_confirm": True}, timeout=20)
    if r.status_code >= 300:
        try:
            msg = r.json().get("msg") or r.json().get("error_description") or r.text
        except Exception:  # noqa: BLE001
            msg = r.text
        raise RuntimeError(f"{r.status_code}: {msg}")
    return r.json()["id"]


def _exec(sql: str, args=()):
    cur = get_conn().cursor()
    cur.execute(sql, args)
    cur.close()


def create_usuario(uid, nombre, email, rol, tecnico_id, region_id, created_by=None):
    _exec("""INSERT INTO usuario (id, nombre, email, rol, tecnico_id, region_id, activo, created_by)
             VALUES (%s,%s,%s,%s,%s,%s,true,%s)
             ON CONFLICT (id) DO UPDATE SET nombre=excluded.nombre, email=excluded.email,
               rol=excluded.rol, tecnico_id=excluded.tecnico_id, region_id=excluded.region_id, activo=true""",
          (uid, nombre, email, rol, tecnico_id, region_id, created_by))


def list_usuarios():
    return _q("""SELECT u.id::text AS id, u.nombre, u.email, u.rol::text AS rol, u.activo,
                        t.nombre AS tecnico
                 FROM usuario u LEFT JOIN cat_tecnico t ON t.id = u.tecnico_id
                 ORDER BY u.activo DESC, u.rol, u.nombre""")


def set_activo(uid: str, activo: bool):
    _exec("UPDATE usuario SET activo=%s WHERE id=%s", (activo, uid))


@st.cache_data(ttl=120, show_spinner=False)
def _tecnicos():
    return _q("SELECT id::text AS id, nombre FROM cat_tecnico WHERE es_aprobado ORDER BY nombre")


@st.cache_data(ttl=300, show_spinner=False)
def _regiones():
    return _q("SELECT id::text AS id, nombre FROM cat_region ORDER BY nombre")


def render_users_admin():
    from console_ui import page_header, friendly_error, empty_state
    page_header(
        "👤 Usuarios",
        "Crea cuentas y decide quién entra a la consola y a la tableta.",
        help_md=(
            "1. Llena nombre, correo y contraseña, y elige el **rol**.\n"
            "2. Un **técnico** se vincula a su nombre del catálogo para que el "
            "formulario de la tableta salga prellenado.\n"
            "3. Para quitar el acceso a alguien usa **Desactivar** (se puede reactivar "
            "después).\n\n" + ROLES_MD
        ),
    )
    if not SUPABASE_SERVICE_ROLE_KEY:
        st.error("Falta SUPABASE_SERVICE_ROLE_KEY en catalog-review-app/.env (clave service_role).")
        return

    tecs = _tecnicos(); tmap = {t["id"]: t["nombre"] for t in tecs}
    regs = _regiones(); rmap = {r["id"]: r["nombre"] for r in regs}

    with st.expander("➕ Crear cuenta", expanded=True):
        c1, c2 = st.columns(2)
        nombre = c1.text_input("Nombre", key="ua_nombre")
        email = c2.text_input("Correo", key="ua_email", placeholder="juan@bocaalamo.local")
        c3, c4 = st.columns(2)
        password = c3.text_input("Contraseña", key="ua_pass", type="password")
        rol = c4.selectbox("Rol", ROLES, key="ua_rol")
        with c4.popover("❓ ¿Qué puede hacer cada rol?"):
            st.markdown(ROLES_MD)
        tecnico_id = None
        if rol == "TECNICO":
            tecnico_id = st.selectbox("Técnico (cat_tecnico)", [None] + list(tmap),
                                      format_func=lambda i: "—" if i is None else tmap.get(i, i), key="ua_tec")
        region_id = st.selectbox("Región (opcional)", [None] + list(rmap),
                                 format_func=lambda i: "Todas" if i is None else rmap.get(i, i), key="ua_reg")
        needs_tec = rol == "TECNICO" and not tecnico_id
        disabled = not (nombre.strip() and email.strip() and password) or needs_tec
        if needs_tec:
            st.caption("Un técnico debe vincularse a un cat_tecnico.")
        if st.button("Crear cuenta", type="primary", disabled=disabled, key="ua_create"):
            try:
                uid = create_auth_user(email.strip(), password)
                create_usuario(uid, nombre.strip(), email.strip().lower(), rol, tecnico_id, region_id)
                st.success(f"Cuenta creada: {nombre} ({rol}).")
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"No se pudo crear: {friendly_error(e)}")

    st.subheader("Cuentas")
    rows = list_usuarios()
    if not rows:
        empty_state("Aún no hay cuentas. Crea la primera con «➕ Crear cuenta».", "👥")
        return
    st.caption(f"{len(rows)} cuenta(s).")
    for u in rows:
        with st.container(border=True):
            c = st.columns([3, 2, 2, 2])
            c[0].markdown(f"**{u['nombre']}**  \n`{u['email'] or '—'}`")
            c[1].markdown(u["rol"])
            c[2].markdown(f"téc: {u['tecnico'] or '—'}")
            with c[3]:
                if u["activo"]:
                    if st.button("Desactivar", key=f"de_{u['id']}", use_container_width=True):
                        set_activo(u["id"], False); st.rerun()
                else:
                    st.caption("inactivo")
                    if st.button("Activar", key=f"ac_{u['id']}", use_container_width=True):
                        set_activo(u["id"], True); st.rerun()
