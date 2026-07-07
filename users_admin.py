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

from form_builder import get_conn, _q, _log
from console_config import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

ROLES = ["TECNICO", "ADMINISTRADOR", "ANALISTA"]
_NEW_TEC = "__new__"   # sentinel: "create a new cat_tecnico" option in the técnico picker

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


def reset_password(uid: str, new_password: str):
    """Admin-set a new password for an existing auth user (GoTrue admin API)."""
    r = requests.put(f"{SUPABASE_URL}/auth/v1/admin/users/{uid}", headers=_svc_headers(),
                     json={"password": new_password}, timeout=20)
    if r.status_code >= 300:
        try:
            msg = r.json().get("msg") or r.json().get("error_description") or r.text
        except Exception:  # noqa: BLE001
            msg = r.text
        raise RuntimeError(f"{r.status_code}: {msg}")
    _log("usuario", uid, "reset_password", {})


def _exec(sql: str, args=()):
    cur = get_conn().cursor()
    cur.execute(sql, args)
    cur.close()


def create_tecnico(nombre: str) -> str:
    """Insert a new approved cat_tecnico and return its id (used from the alta de usuario)."""
    rows = _q("INSERT INTO cat_tecnico (nombre, es_aprobado) VALUES (%s, true) RETURNING id::text AS id",
              (nombre.strip(),))
    tid = rows[0]["id"]
    _log("cat_tecnico", tid, "crear", {"nombre": nombre.strip(), "origen": "alta_usuario"})
    _tecnicos.clear()
    return tid


def create_usuario(uid, nombre, email, rol, tecnico_id, region_id, created_by=None):
    _exec("""INSERT INTO usuario (id, nombre, email, rol, tecnico_id, region_id, activo, created_by)
             VALUES (%s,%s,%s,%s,%s,%s,true,%s)
             ON CONFLICT (id) DO UPDATE SET nombre=excluded.nombre, email=excluded.email,
               rol=excluded.rol, tecnico_id=excluded.tecnico_id, region_id=excluded.region_id, activo=true""",
          (uid, nombre, email, rol, tecnico_id, region_id, created_by))


def list_usuarios():
    return _q("""SELECT u.id::text AS id, u.nombre, u.email, u.rol::text AS rol, u.activo,
                        u.tecnico_id::text AS tecnico_id, t.nombre AS tecnico
                 FROM usuario u LEFT JOIN cat_tecnico t ON t.id = u.tecnico_id
                 ORDER BY u.activo DESC, u.rol, u.nombre""")


def set_activo(uid: str, activo: bool):
    _exec("UPDATE usuario SET activo=%s WHERE id=%s", (activo, uid))
    _log("usuario", uid, "activar" if activo else "desactivar", {})


def set_rol(uid: str, rol: str, tecnico_id):
    """Change a user's role. tecnico_id is kept only for TECNICO (NULL otherwise)."""
    _exec("UPDATE usuario SET rol=%s, tecnico_id=%s WHERE id=%s",
          (rol, tecnico_id if rol == "TECNICO" else None, uid))
    _log("usuario", uid, "cambiar_rol", {"rol": rol})


@st.cache_data(ttl=120, show_spinner=False)
def _tecnicos():
    return _q("SELECT id::text AS id, nombre FROM cat_tecnico WHERE es_aprobado ORDER BY nombre")


@st.cache_data(ttl=300, show_spinner=False)
def _regiones():
    return _q("SELECT id::text AS id, nombre FROM cat_region ORDER BY nombre")


def _tec_picker(tmap: dict, key: str, current=None, allow_new: bool = True):
    """Técnico selectbox (+ optional 'create new'). Returns (tecnico_id, new_name_or_None)."""
    opts = ([None] + ([_NEW_TEC] if allow_new else []) + list(tmap))
    idx = opts.index(current) if current in opts else 0

    def _fmt(i):
        if i is None:
            return "—"
        if i == _NEW_TEC:
            return "➕ Crear nuevo técnico…"
        return tmap.get(i, i)

    sel = st.selectbox("Técnico (cat_tecnico)", opts, index=idx, format_func=_fmt, key=key)
    if sel == _NEW_TEC:
        return None, st.text_input("Nombre del nuevo técnico", key=f"{key}_new")
    return sel, None


def render_users_admin():
    from console_ui import page_header, friendly_error, empty_state, flash
    page_header(
        "👤 Usuarios",
        "Crea cuentas y decide quién entra a la consola y a la tableta.",
        help_md=(
            "1. Llena nombre, correo y contraseña, y elige el **rol**.\n"
            "2. Un **técnico** se vincula a su nombre del catálogo para que el "
            "formulario de la tableta salga prellenado (puedes **crear el técnico aquí mismo**).\n"
            "3. Con **⚙️ Gestionar** cambias el rol, restableces la contraseña o desactivas a alguien.\n\n"
            + ROLES_MD
        ),
    )
    if not SUPABASE_SERVICE_ROLE_KEY:
        st.error("Falta SUPABASE_SERVICE_ROLE_KEY en catalog-review-app/.env (clave service_role).")
        return

    tecs = _tecnicos(); tmap = {t["id"]: t["nombre"] for t in tecs}
    regs = _regiones(); rmap = {r["id"]: r["nombre"] for r in regs}
    n = st.session_state.get("ua_nonce", 0)   # bumped on success → fresh (cleared) form widgets

    with st.expander("➕ Crear cuenta", expanded=True):
        c1, c2 = st.columns(2)
        nombre = c1.text_input("Nombre", key=f"ua_nombre_{n}")
        email = c2.text_input("Correo", key=f"ua_email_{n}", placeholder="juan@bocaalamo.local")
        c3, c4 = st.columns(2)
        password = c3.text_input("Contraseña", key=f"ua_pass_{n}", type="password")
        rol = c4.selectbox("Rol", ROLES, key=f"ua_rol_{n}")
        with c4.popover("❓ ¿Qué puede hacer cada rol?"):
            st.markdown(ROLES_MD)
        tecnico_id, new_tec = None, None
        if rol == "TECNICO":
            tecnico_id, new_tec = _tec_picker(tmap, key=f"ua_tec_{n}")
        region_id = st.selectbox("Región (opcional)", [None] + list(rmap),
                                 format_func=lambda i: "Todas" if i is None else rmap.get(i, i),
                                 key=f"ua_reg_{n}")
        needs_tec = rol == "TECNICO" and not tecnico_id and not (new_tec and new_tec.strip())
        disabled = not (nombre.strip() and email.strip() and password) or needs_tec
        if needs_tec:
            st.caption("Un técnico debe vincularse a un cat_tecnico (elige uno o crea uno nuevo).")
        if st.button("Crear cuenta", type="primary", disabled=disabled, key="ua_create"):
            try:
                tid = tecnico_id
                if rol == "TECNICO" and new_tec and new_tec.strip():
                    tid = create_tecnico(new_tec)
                uid = create_auth_user(email.strip(), password)
                create_usuario(uid, nombre.strip(), email.strip().lower(), rol, tid, region_id)
                st.session_state["ua_nonce"] = n + 1   # clear the form
                flash(f"Cuenta creada: {nombre} ({rol}).")
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
            c = st.columns([3, 2, 2, 2], vertical_alignment="center")
            estado = "" if u["activo"] else "  ·  🚫 inactivo"
            c[0].markdown(f"**{u['nombre']}**{estado}  \n`{u['email'] or '—'}`")
            c[1].markdown(u["rol"])
            c[2].markdown(f"téc: {u['tecnico'] or '—'}")
            with c[3]:
                with st.popover("⚙️ Gestionar", width="stretch"):
                    _manage_account(u, tmap, friendly_error, flash)


def _manage_account(u, tmap, friendly_error, flash):
    uid = u["id"]
    # --- activate / deactivate ---
    if u["activo"]:
        if st.button("🚫 Desactivar", key=f"de_{uid}", width="stretch"):
            set_activo(uid, False); flash(f"Cuenta de {u['nombre']} desactivada.", "🚫"); st.rerun()
    else:
        if st.button("✅ Activar", key=f"ac_{uid}", width="stretch"):
            set_activo(uid, True); flash(f"Cuenta de {u['nombre']} activada."); st.rerun()

    # --- change role ---
    st.divider()
    st.caption("Cambiar rol")
    newrol = st.selectbox("Rol", ROLES, index=ROLES.index(u["rol"]) if u["rol"] in ROLES else 0,
                          key=f"rol_{uid}", label_visibility="collapsed")
    newtec, newtec_name = u.get("tecnico_id"), None
    if newrol == "TECNICO":
        newtec, newtec_name = _tec_picker(tmap, key=f"roltec_{uid}", current=u.get("tecnico_id"))
    if st.button("Guardar rol", key=f"chr_{uid}", width="stretch"):
        try:
            tid = newtec
            if newrol == "TECNICO" and newtec_name and newtec_name.strip():
                tid = create_tecnico(newtec_name)
            if newrol == "TECNICO" and not tid:
                st.error("Un técnico debe vincularse a un cat_tecnico.")
            else:
                set_rol(uid, newrol, tid)
                flash(f"Rol de {u['nombre']} cambiado a {newrol}."); st.rerun()
        except Exception as e:  # noqa: BLE001
            st.error(friendly_error(e))

    # --- reset password ---
    st.divider()
    st.caption("Restablecer contraseña")
    npw = st.text_input("Nueva contraseña", type="password", key=f"pw_{uid}",
                        label_visibility="collapsed", placeholder="Nueva contraseña")
    if st.button("Restablecer", key=f"rpw_{uid}", width="stretch", disabled=not npw):
        try:
            reset_password(uid, npw)
            flash(f"Contraseña de {u['nombre']} restablecida.", "🔑"); st.rerun()
        except Exception as e:  # noqa: BLE001
            st.error(friendly_error(e))
