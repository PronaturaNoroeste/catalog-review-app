"""
Form Builder (M2) — author, version & publish dynamic form-definitions.

The admin console's second mode (the first is catalog dedup review in app.py).
This is a *bounded structured editor* (AppDashboardSpec/08 §5): editable tables +
a JSON escape-hatch + validation + live preview + publish→immutable version.
It writes the same form-definition JSON the capture app renders and the
`crear_faena_completa` RPC routes (see Planning/supabase, seed/boca_alamo_form.json).

Governance firewall (OD-22): core fields bind only to EXISTING fisheries columns,
discovered live from the schema (`load_bindable_core`). Admins can add custom
fields and reconfigure presentation/validation, but cannot invent core columns.

DB access: reads DATABASE_URL from the environment or a local .env (see
candidate paths in `_dsn`). The dev project is the same one the supabase repo targets.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st

try:
    import psycopg2
except ImportError:  # surfaced in the UI if missing
    psycopg2 = None

BASE_DIR = Path(__file__).parent

# Fisheries tables a field may bind to (the "core" lane). Order = nominal form flow.
CORE_TABLES = [
    "faena", "faena_especie_objetivo", "faena_arte", "captura",
    "medicion", "carnada", "interaccion_etp", "gasto",
]

# Columns never offered for binding (audit / system / migration plumbing).
SYSTEM_COLS = {
    "id", "faena_id", "created_at", "updated_at", "created_by", "synced_at",
    "device_id", "auth_uid", "formato_origen_id", "formulario_id",
    "formulario_version", "legacy_id", "codigo_formato",
    "latitud_legacy", "longitud_legacy", "es_historico",
}

TIPOS = [
    "texto", "entero", "decimal", "fecha", "hora", "catalogo",
    "seleccion_unica", "multiseleccion", "bool", "geo", "foto",
]
BIND_TIPOS = ["core", "custom", "ui"]


# =====================================================================
# DB layer
# =====================================================================
def _dsn() -> str | None:
    """DATABASE_URL from env or a .env (console dir, then the supabase repo)."""
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    for p in (BASE_DIR / ".env",
              BASE_DIR.parent / "Planning" / "supabase" / ".env"):
        if p.exists():
            for raw in p.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if line and not line.startswith("#") and line.startswith("DATABASE_URL"):
                    return line.split("=", 1)[1].strip().strip("'").strip('"')
    return None


@st.cache_resource(show_spinner=False)
def get_conn():
    if psycopg2 is None:
        raise RuntimeError("psycopg2 no está instalado (pip install psycopg2-binary).")
    dsn = _dsn()
    if not dsn:
        raise RuntimeError("DATABASE_URL no configurado (env o .env). Ver supabase/TODO.md.")
    if "sslmode=" not in dsn:
        dsn += ("&" if "?" in dsn else "?") + "sslmode=require"
    conn = psycopg2.connect(dsn, connect_timeout=20)
    conn.autocommit = True
    return conn


def _q(sql, args=None):
    cur = get_conn().cursor()
    # Pass params only when present: with an empty tuple psycopg2 still tries to
    # interpolate literal '%' (e.g. LIKE 'cat\_%') and raises "tuple index out of range".
    if args:
        cur.execute(sql, args)
    else:
        cur.execute(sql)
    rows = cur.fetchall()
    cols = [c[0] for c in cur.description]
    cur.close()
    return [dict(zip(cols, r)) for r in rows]


def _exec(sql: str, args=()):
    """Write statement on the shared (autocommit) connection."""
    cur = get_conn().cursor()
    cur.execute(sql, args)
    cur.close()


def _log(tabla: str, rid: str, accion: str, detalle: dict):
    """cambio_catalogo audit row — every console write action records one."""
    _exec("""INSERT INTO cambio_catalogo (tabla, registro_id, accion, detalle, usuario_id)
             VALUES (%s,%s,%s,%s::jsonb,NULL)""",
          (tabla, rid, accion, json.dumps(detalle, ensure_ascii=False, default=str)))


@st.cache_data(ttl=300, show_spinner=False)
def load_bindable_core() -> dict:
    """Introspect the fisheries tables → {"table.column": {label, tipo, catalogo?}}.

    The curated bindable list IS the schema (minus system cols): admins bind to
    real columns only. FK→cat_* columns become `catalogo` fields; enums become
    seleccion_unica; the rest map by data type.
    """
    cols = _q("""
        SELECT table_name, column_name, data_type, udt_name
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name = ANY(%s)
        ORDER BY table_name, ordinal_position
    """, (CORE_TABLES,))
    # FK map: which (table,column) references which cat_* table
    fks = _q("""
        SELECT tc.table_name, kcu.column_name, ccu.table_name AS ref_table
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema
        WHERE tc.constraint_type='FOREIGN KEY' AND tc.table_schema='public'
          AND tc.table_name = ANY(%s)
    """, (CORE_TABLES,))
    fkmap = {(f["table_name"], f["column_name"]): f["ref_table"] for f in fks}

    reg: dict = {}
    for c in cols:
        t, col = c["table_name"], c["column_name"]
        if col in SYSTEM_COLS:
            continue
        ref = fkmap.get((t, col))
        if ref and ref.startswith("cat_"):
            tipo, catalogo = "catalogo", ref
        else:
            dt, udt = c["data_type"], c["udt_name"]
            catalogo = None
            if dt == "date":
                tipo = "fecha"
            elif dt in ("integer", "smallint", "bigint"):
                tipo = "entero"
            elif dt in ("numeric", "double precision", "real"):
                tipo = "decimal"
            elif dt == "boolean":
                tipo = "bool"
            elif dt == "USER-DEFINED":   # enum
                tipo = "seleccion_unica"
            else:
                tipo = "texto"
        entry = {"label": f"{t}.{col}", "tipo": tipo}
        if catalogo:
            entry["catalogo"] = catalogo
        reg[f"{t}.{col}"] = entry
    return reg


@st.cache_data(ttl=300, show_spinner=False)
def list_formatos() -> list[dict]:
    return _q("SELECT id::text, codigo, nombre FROM cat_formato_origen ORDER BY codigo")


def list_formularios() -> list[dict]:
    return _q("""
        SELECT f.id::text, f.nombre, f.version, f.estado, fo.codigo AS formato,
               f.formato_origen_id::text, f.published_at
        FROM formulario f JOIN cat_formato_origen fo ON fo.id = f.formato_origen_id
        ORDER BY fo.codigo, f.version DESC
    """)


def load_formulario(fid: str) -> dict | None:
    rows = _q("""SELECT id::text, nombre, version, estado, formato_origen_id::text,
                        definicion, constantes
                 FROM formulario WHERE id=%s""", (fid,))
    return rows[0] if rows else None


def save_borrador(fid: str | None, nombre: str, formato_id: str, version: int,
                  definicion: dict, constantes: dict) -> str:
    """Upsert a borrador. Refuses to touch a published row (immutability)."""
    defn_j = json.dumps(definicion, ensure_ascii=False)
    cons_j = json.dumps(constantes, ensure_ascii=False)
    cur = get_conn().cursor()
    if fid:
        cur.execute("SELECT estado FROM formulario WHERE id=%s", (fid,))
        row = cur.fetchone()
        if row and row[0] == "publicado":
            raise RuntimeError("Esta versión está publicada (inmutable). Crea una nueva versión.")
        cur.execute("""UPDATE formulario SET nombre=%s, definicion=%s, constantes=%s
                       WHERE id=%s""", (nombre, defn_j, cons_j, fid))
        out = fid
    else:
        cur.execute("""INSERT INTO formulario
                       (nombre, formato_origen_id, version, estado, definicion, constantes, created_by)
                       VALUES (%s,%s,%s,'borrador',%s,%s,'console') RETURNING id::text""",
                    (nombre, formato_id, version, defn_j, cons_j))
        out = cur.fetchone()[0]
    cur.close()
    return out


def publish(fid: str) -> None:
    cur = get_conn().cursor()
    cur.execute("UPDATE formulario SET estado='publicado', published_at=now() WHERE id=%s", (fid,))
    cur.close()


def next_version(formato_id: str) -> int:
    rows = _q("SELECT COALESCE(MAX(version),0)+1 AS v FROM formulario WHERE formato_origen_id=%s",
              (formato_id,))
    return rows[0]["v"]


def new_version_from(fid: str) -> str:
    """Clone a (usually published) form into a fresh borrador at the next version."""
    f = load_formulario(fid)
    if not f:
        raise RuntimeError("Formulario no encontrado.")
    v = next_version(f["formato_origen_id"])
    return save_borrador(None, f["nombre"], f["formato_origen_id"], v,
                         f["definicion"], f["constantes"] or {})


# =====================================================================
# Pure validation (no Streamlit / DB — unit-testable)
# =====================================================================
def validate_definition(definicion: dict, constantes: dict, bindable: dict) -> tuple[list, list]:
    """Return (errores, advertencias). Errores block publish; advertencias don't."""
    errores: list[str] = []
    advert: list[str] = []
    secciones = definicion.get("secciones")
    if not isinstance(secciones, list) or not secciones:
        return (["La definición no tiene secciones."], [])

    sec_keys, field_keys, all_fields = set(), set(), {}
    for si, s in enumerate(secciones):
        sk = s.get("key")
        loc = f"sección «{sk or si}»"
        if not sk:
            errores.append(f"{loc}: falta 'key'.")
        elif sk in sec_keys:
            errores.append(f"{loc}: 'key' duplicada.")
        else:
            sec_keys.add(sk)
        if not s.get("titulo"):
            advert.append(f"{loc}: sin 'titulo'.")
        if s.get("repetible") and not s.get("entidad"):
            errores.append(f"{loc}: 'repetible' requiere 'entidad' (tabla hija).")
        campos = s.get("campos") or []
        if not campos:
            advert.append(f"{loc}: sin campos.")
        for ci, c in enumerate(campos):
            ck = c.get("key")
            floc = f"{loc}, campo «{ck or ci}»"
            if not ck:
                errores.append(f"{floc}: falta 'key'.")
            elif ck in field_keys:
                errores.append(f"{floc}: 'key' duplicada en el formulario.")
            else:
                field_keys.add(ck)
                all_fields[ck] = c
            if not c.get("label"):
                advert.append(f"{floc}: sin 'label'.")
            tipo = c.get("tipo")
            if tipo not in TIPOS:
                errores.append(f"{floc}: 'tipo'='{tipo}' no válido.")
            b = c.get("binding") or {}
            bt = b.get("tipo")
            if bt not in BIND_TIPOS:
                errores.append(f"{floc}: binding.tipo='{bt}' no válido (core|custom|ui).")
            if bt == "core":
                col = b.get("columna")
                if not col:
                    errores.append(f"{floc}: binding core sin 'columna'.")
                elif col not in bindable:
                    errores.append(f"{floc}: columna '{col}' no es un campo core válido "
                                   f"(firewall de gobernanza).")
            if tipo == "catalogo" and not (b.get("catalogo")):
                advert.append(f"{floc}: tipo catálogo sin 'catalogo' (tabla cat_*).")
            if tipo in ("seleccion_unica", "multiseleccion") and not c.get("opciones"):
                advert.append(f"{floc}: {tipo} sin 'opciones'.")

    # cross-references resolve to real field keys
    for ck, c in all_fields.items():
        for prop in ("visible_si", "filtrado_por"):
            ref = (c.get(prop) or {}).get("campo")
            if ref and ref not in field_keys:
                errores.append(f"campo «{ck}»: {prop}.campo='{ref}' no existe.")
    for s in secciones:
        ref = (s.get("visible_si") or {}).get("campo")
        if ref and ref not in field_keys:
            errores.append(f"sección «{s.get('key')}»: visible_si.campo='{ref}' no existe.")

    for k in constantes or {}:
        col = k.split(".", 1)[-1] if "." in k else k
        if k not in bindable and not k.endswith("tipo_registro"):
            advert.append(f"constante '{k}': no es un campo core conocido (¿typo?).")
    return errores, advert


# =====================================================================
# Editor <-> dataframe (de)serialization (pure)
# =====================================================================
_FIELD_COLS = ["key", "label", "tipo", "requerido", "autocompletar",
               "bind_tipo", "bind_columna", "bind_catalogo",
               "lista", "permite_proponer", "permite_otro_texto",
               "opciones", "visible_si", "filtrado_por", "validacion",
               "opciones_prioritarias", "ayuda"]


def fields_to_df(campos: list[dict]) -> pd.DataFrame:
    rows = []
    for c in campos:
        b = c.get("binding") or {}
        rows.append({
            "key": c.get("key", ""), "label": c.get("label", ""),
            "tipo": c.get("tipo", "texto"), "requerido": bool(c.get("requerido", False)),
            "autocompletar": bool(c.get("autocompletar", False)),
            "bind_tipo": b.get("tipo", "core"), "bind_columna": b.get("columna", ""),
            "bind_catalogo": b.get("catalogo", ""),
            "lista": c.get("lista", ""),
            "permite_proponer": bool(c.get("permite_proponer", False)),
            "permite_otro_texto": bool(c.get("permite_otro_texto", False)),
            "opciones": _j(c.get("opciones")), "visible_si": _j(c.get("visible_si")),
            "filtrado_por": _j(c.get("filtrado_por")), "validacion": _j(c.get("validacion")),
            "opciones_prioritarias": _j(c.get("opciones_prioritarias")),
            "ayuda": c.get("ayuda", ""),
        })
    return pd.DataFrame(rows, columns=_FIELD_COLS)


def df_to_fields(df: pd.DataFrame) -> list[dict]:
    campos = []
    for _, r in df.iterrows():
        key = (r.get("key") or "").strip()
        if not key:
            continue
        c: dict = {"key": key, "label": (r.get("label") or "").strip(),
                   "tipo": r.get("tipo") or "texto"}
        if bool(r.get("requerido")):
            c["requerido"] = True
        if bool(r.get("autocompletar")):
            c["autocompletar"] = True
        if r.get("ayuda"):
            c["ayuda"] = r["ayuda"]
        # curated-list wiring — dropping these breaks the tablet picker (doc 16)
        if (r.get("lista") or "").strip():
            c["lista"] = r["lista"].strip()
        if bool(r.get("permite_proponer")):
            c["permite_proponer"] = True
        if bool(r.get("permite_otro_texto")):
            c["permite_otro_texto"] = True
        b: dict = {"tipo": r.get("bind_tipo") or "core"}
        if (r.get("bind_columna") or "").strip():
            b["columna"] = r["bind_columna"].strip()
        if (r.get("bind_catalogo") or "").strip():
            b["catalogo"] = r["bind_catalogo"].strip()
        c["binding"] = b
        for prop in ("opciones", "visible_si", "filtrado_por", "validacion", "opciones_prioritarias"):
            val = _pj(r.get(prop))
            if val not in (None, "", [], {}):
                c[prop] = val
        campos.append(c)
    return campos


def _j(v) -> str:
    return "" if v in (None, "", [], {}) else json.dumps(v, ensure_ascii=False)


def _pj(s):
    if s is None or (isinstance(s, str) and not s.strip()):
        return None
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return s   # leave raw; validation will not crash, just won't match


_SEC_COLS = ["key", "titulo", "entidad", "repetible", "min", "boton_agregar", "visible_si"]


def _secs_to_df(secs: list[dict]) -> pd.DataFrame:
    rows = [{
        "key": s.get("key", ""), "titulo": s.get("titulo", ""),
        "entidad": s.get("entidad", ""), "repetible": bool(s.get("repetible", False)),
        "min": s.get("min", None), "boton_agregar": s.get("boton_agregar", ""),
        "visible_si": _j(s.get("visible_si")),
    } for s in secs]
    return pd.DataFrame(rows, columns=_SEC_COLS)


# =====================================================================
# UI
# =====================================================================
def _blank_work() -> dict:
    return {"id": None, "nombre": "", "formato_id": None, "version": 1, "estado": "borrador",
            "secciones": [{"key": "generales", "titulo": "Datos del viaje",
                           "entidad": "faena", "campos": []}],
            "constantes": {}}


def _load_into_work(f: dict) -> dict:
    defn = f.get("definicion") or {}
    return {"id": f["id"], "nombre": f["nombre"], "formato_id": f["formato_origen_id"],
            "version": f["version"], "estado": f["estado"],
            "secciones": defn.get("secciones", []), "constantes": f.get("constantes") or {}}


def render_form_builder():
    from console_ui import page_header, friendly_error
    page_header(
        "🛠️ Formularios",
        "Edita y publica las versiones del formulario que llena el técnico en la tableta.",
        help_md=(
            "1. Elige un formulario (o «➕ Nuevo») — cada uno tiene **versiones**.\n"
            "2. Una versión **publicada** no se puede tocar: crea una **Nueva versión** "
            "para editarla.\n"
            "3. Edita secciones y campos, revisa la **validación** y la **vista previa**.\n"
            "4. **💾 Guardar borrador** mientras trabajas; **🚀 Publicar** cuando esté listo "
            "(la tableta usa la última versión publicada)."
        ),
    )

    try:
        bindable = load_bindable_core()
        formatos = list_formatos()
        formularios = list_formularios()
    except Exception as e:  # noqa: BLE001
        st.error(f"No se pudo conectar a la base de datos: {e}")
        st.info("Configura DATABASE_URL (env o .env). Ver Planning/supabase/TODO.md.")
        return

    # ---- pick / new -------------------------------------------------
    opts = ["__new__"] + [f["id"] for f in formularios]
    by_id = {f["id"]: f for f in formularios}

    def _label(o):
        if o == "__new__":
            return "➕ Nuevo formulario"
        f = by_id.get(o)
        if not f:
            return str(o)
        chip = {"borrador": "📝", "publicado": "✅", "archivado": "🗄️"}.get(f["estado"], "")
        return f"{chip} [{f['formato']}] {f['nombre']} · v{f['version']} ({f['estado']})"

    sel = st.selectbox("Formulario", opts, format_func=_label, key="fb_sel")

    # load the chosen form into the working copy once per selection change
    if st.session_state.get("fb_loaded") != sel:
        if sel == "__new__":
            st.session_state["fb_work"] = _blank_work()
        else:
            st.session_state["fb_work"] = _load_into_work(load_formulario(sel))
        st.session_state["fb_loaded"] = sel
    work = st.session_state["fb_work"]
    published = work["estado"] == "publicado"

    if published:
        st.warning("Esta versión está **publicada** (inmutable). Usa **Nueva versión** para editarla.")

    # ---- metadata ---------------------------------------------------
    c1, c2, c3 = st.columns([3, 2, 1])
    work["nombre"] = c1.text_input("Nombre", work["nombre"], key="fb_nombre", disabled=published)
    fmt_ids = [f["id"] for f in formatos]
    fmt_label = {f["id"]: f"{f['codigo']} — {f['nombre']}" for f in formatos}
    cur_fmt = work["formato_id"] if work["formato_id"] in fmt_ids else (fmt_ids[0] if fmt_ids else None)
    work["formato_id"] = c2.selectbox(
        "Formato / región", fmt_ids, index=fmt_ids.index(cur_fmt) if cur_fmt else 0,
        format_func=lambda i: fmt_label.get(i, i), key="fb_formato",
        disabled=published or work["id"] is not None)
    c3.metric("Versión", work["version"])

    cons_raw = st.text_area("Constantes (JSON) — valores fijos del formulario (region/zona/tipo)",
                            json.dumps(work["constantes"], ensure_ascii=False, indent=2),
                            height=90, key="fb_constantes", disabled=published)
    try:
        work["constantes"] = json.loads(cons_raw) if cons_raw.strip() else {}
        cons_err = None
    except ValueError as e:
        cons_err = str(e)
        st.error(f"Constantes: JSON inválido — {e}")

    # ---- sections (structure) --------------------------------------
    st.subheader("Secciones")
    sec_df = st.data_editor(
        _secs_to_df(work["secciones"]), key="fb_secs",
        num_rows="fixed" if published else "dynamic", use_container_width=True, hide_index=True,
        disabled=published,
        column_config={
            "key": st.column_config.TextColumn("key", required=True),
            "titulo": st.column_config.TextColumn("título"),
            "entidad": st.column_config.SelectboxColumn("entidad (tabla)", options=[""] + CORE_TABLES),
            "repetible": st.column_config.CheckboxColumn("repetible"),
            "min": st.column_config.NumberColumn("min", min_value=0, step=1),
            "boton_agregar": st.column_config.TextColumn("botón agregar"),
            "visible_si": st.column_config.TextColumn("visible_si (JSON)"),
        })

    # rebuild section list from the editor, carrying campos over by key
    prev_campos = {s.get("key"): s.get("campos", []) for s in work["secciones"]}
    new_secs = []
    for _, r in sec_df.iterrows():
        k = (r.get("key") or "").strip()
        if not k:
            continue
        s: dict = {"key": k, "titulo": (r.get("titulo") or "").strip(),
                   "campos": prev_campos.get(k, [])}
        if (r.get("entidad") or "").strip():
            s["entidad"] = r["entidad"].strip()
        if bool(r.get("repetible")):
            s["repetible"] = True
        if r.get("min") is not None and not pd.isna(r.get("min")):
            s["min"] = int(r["min"])
        if (r.get("boton_agregar") or "").strip():
            s["boton_agregar"] = r["boton_agregar"].strip()
        vs = _pj(r.get("visible_si"))
        if vs:
            s["visible_si"] = vs
        new_secs.append(s)
    work["secciones"] = new_secs

    # ---- fields of one section -------------------------------------
    if new_secs:
        st.subheader("Campos de la sección")
        sec_keys = [s["key"] for s in new_secs]
        active = st.selectbox("Sección a editar", sec_keys, key="fb_active_sec")
        sec = next(s for s in new_secs if s["key"] == active)
        bind_cols = [""] + sorted(bindable.keys())
        cat_tables = [""] + sorted({v["catalogo"] for v in bindable.values() if v.get("catalogo")})

        f_df = st.data_editor(
            fields_to_df(sec["campos"]), key=f"fb_fields_{active}",
            num_rows="fixed" if published else "dynamic", use_container_width=True, hide_index=True,
            disabled=published,
            column_config={
                "key": st.column_config.TextColumn("key", required=True),
                "label": st.column_config.TextColumn("label", width="medium"),
                "tipo": st.column_config.SelectboxColumn("tipo", options=TIPOS),
                "requerido": st.column_config.CheckboxColumn("req."),
                "autocompletar": st.column_config.CheckboxColumn("autocompl."),
                "bind_tipo": st.column_config.SelectboxColumn("binding", options=BIND_TIPOS),
                "bind_columna": st.column_config.SelectboxColumn("columna core", options=bind_cols, width="medium"),
                "bind_catalogo": st.column_config.SelectboxColumn("catálogo", options=cat_tables),
                "lista": st.column_config.TextColumn(
                    "lista curada 🔒", disabled=True,
                    help="Lista curada de opciones (se administra en 📑 Listas del formulario)."),
                "permite_proponer": st.column_config.CheckboxColumn(
                    "proponer", help="El técnico puede proponer nombres fuera de la lista."),
                "permite_otro_texto": st.column_config.CheckboxColumn(
                    "otro texto", help="Permite escribir un valor libre («otro»)."),
                "opciones": st.column_config.TextColumn("opciones (JSON)"),
                "visible_si": st.column_config.TextColumn("visible_si (JSON)"),
                "filtrado_por": st.column_config.TextColumn("filtrado_por (JSON)"),
                "validacion": st.column_config.TextColumn("validación (JSON)"),
                "opciones_prioritarias": st.column_config.TextColumn("prioritarias (JSON)"),
                "ayuda": st.column_config.TextColumn("ayuda"),
            })
        sec["campos"] = df_to_fields(f_df)
        listados = [f"**{c.get('label') or c['key']}** → `{c['lista']}`"
                    for c in sec["campos"] if c.get("lista")]
        if listados:
            st.caption("📑 Con lista curada: " + " · ".join(listados) +
                       ". Las opciones de estas listas se administran en "
                       "**📑 Listas del formulario** (no aquí).")
        # auto-fill catalogo from the bindable registry when a core column is chosen
        for c in sec["campos"]:
            b = c.get("binding", {})
            if b.get("tipo") == "core" and b.get("columna") in bindable:
                meta = bindable[b["columna"]]
                if meta["tipo"] == "catalogo" and not b.get("catalogo"):
                    b["catalogo"] = meta["catalogo"]

    definicion = {"secciones": work["secciones"]}
    errores, advert = validate_definition(definicion, work["constantes"], bindable)
    if cons_err:
        errores = [f"Constantes JSON inválido: {cons_err}"] + errores

    # ---- status + actions ------------------------------------------
    st.divider()
    a1, a2, a3, a4 = st.columns(4)
    if errores:
        a1.error(f"{len(errores)} error(es)")
    else:
        a1.success("Válido ✓")
    if advert:
        a2.warning(f"{len(advert)} advertencia(s)")

    with st.expander("🔎 Validación", expanded=bool(errores)):
        for e in errores:
            st.markdown(f"- ❌ {e}")
        for w in advert:
            st.markdown(f"- ⚠️ {w}")
        if not errores and not advert:
            st.caption("Sin problemas.")

    save_disabled = published or not work["nombre"].strip() or cons_err is not None
    if a3.button("💾 Guardar borrador", key="fb_save", disabled=save_disabled, use_container_width=True):
        try:
            fid = save_borrador(work["id"], work["nombre"], work["formato_id"],
                                work["version"], definicion, work["constantes"])
            work["id"] = fid
            st.session_state["fb_loaded"] = None  # force reload list/state next run
            st.success("Borrador guardado.")
            st.rerun()
        except Exception as e:  # noqa: BLE001
            st.error(f"No se pudo guardar: {friendly_error(e)}")

    pub_disabled = published or bool(errores) or work["id"] is None
    if a4.button("🚀 Publicar", key="fb_publish", disabled=pub_disabled, use_container_width=True,
                 help="Guarda primero. Publicar vuelve la versión inmutable."):
        try:
            publish(work["id"])
            st.session_state["fb_loaded"] = None
            st.success("Formulario publicado (inmutable).")
            st.rerun()
        except Exception as e:  # noqa: BLE001
            st.error(f"No se pudo publicar: {friendly_error(e)}")

    if published:
        if st.button("🌱 Nueva versión (editable)", key="fb_newver"):
            try:
                nid = new_version_from(work["id"])
                st.session_state["fb_loaded"] = None
                st.session_state["fb_sel"] = nid
                st.success("Nueva versión creada como borrador.")
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"No se pudo crear la versión: {friendly_error(e)}")

    # ---- preview ----------------------------------------------------
    st.divider()
    with st.expander("👁️ Vista previa", expanded=False):
        render_preview(definicion, work["constantes"])


def render_preview(definicion: dict, constantes: dict):
    if constantes:
        st.caption("Constantes (prellenadas): " +
                   ", ".join(f"`{k}`" for k in constantes))
    for s in definicion.get("secciones", []):
        flags = []
        if s.get("repetible"):
            flags.append("🔁 repetible")
        if s.get("visible_si"):
            v = s["visible_si"]
            flags.append(f"👁️ si {v.get('campo')} {v.get('op','==')} {v.get('valor')}")
        st.markdown(f"#### {s.get('titulo', s.get('key'))}  " +
                    (f"<span style='color:#888;font-size:0.8em'>{' · '.join(flags)}</span>"
                     if flags else ""), unsafe_allow_html=True)
        for c in s.get("campos", []):
            req = " *" if c.get("requerido") else ""
            b = c.get("binding", {})
            tag = b.get("tipo", "")
            dest = b.get("columna") or (b.get("catalogo") and f"cat→{b['catalogo']}") or tag
            cond = ""
            if c.get("visible_si"):
                v = c["visible_si"]
                cond = f"  · 👁️ si {v.get('campo')} {v.get('op','==')} {v.get('valor')}"
            st.markdown(f"- **{c.get('label') or c.get('key')}**{req}  "
                        f"`{c.get('tipo')}`  <span style='color:#aaa'>→ {dest}</span>{cond}",
                        unsafe_allow_html=True)
