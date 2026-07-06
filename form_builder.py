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

import copy
import json
import os
import unicodedata
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

# Friendly Spanish names for the core (schema) columns, so the admin never sees a
# raw `medicion.peso_gr`. Curated once (readability is the point); `_core_label`
# derives a clean name for any column not listed (e.g. a future schema addition).
CORE_LABELS = {
    # captura
    "captura.captura_kg": "Kg capturados", "captura.categoria_tamano": "Categoría de tamaño",
    "captura.especie_id": "Especie", "captura.num_organismos": "Número de organismos",
    "captura.observaciones": "Observaciones", "captura.precio_kg": "Precio por kg",
    "captura.presentacion": "Presentación", "captura.tipo_captura": "Tipo de captura",
    # carnada
    "carnada.arte_pesca_id": "Arte de pesca de la carnada", "carnada.especie_id": "Especie de carnada",
    "carnada.kg_aprox": "Kg aproximados", "carnada.nombre_libre": "Nombre de la carnada (libre)",
    "carnada.origen": "Origen de la carnada", "carnada.sitio_libre": "Lugar (libre)",
    "carnada.sitio_pesca_carnada_id": "Sitio de pesca de la carnada",
    # faena
    "faena.area_pesca_id": "Área de pesca", "faena.capitan_id": "Capitán",
    "faena.comunidad_id": "Comunidad", "faena.cooperativa_id": "Cooperativa",
    "faena.corriente": "Corriente", "faena.dias_efectivos_pesca": "Días efectivos de pesca",
    "faena.dias_jornada": "Días de jornada", "faena.embarcacion_id": "Embarcación",
    "faena.encargado_lugar": "Encargado del lugar", "faena.estado_tiempo": "Estado del tiempo",
    "faena.fecha": "Fecha", "faena.gasolina_lts": "Gasolina (litros)",
    "faena.hora_llegada": "Hora de llegada", "faena.hora_salida": "Hora de salida",
    "faena.luna_id": "Luna", "faena.marca_motor": "Marca del motor", "faena.marea_id": "Marea",
    "faena.motor_hp": "Motor (HP)", "faena.num_pescadores": "Número de pescadores",
    "faena.observaciones": "Observaciones", "faena.profundidad_max_brazas": "Profundidad máxima (brazas)",
    "faena.profundidad_min_brazas": "Profundidad mínima (brazas)", "faena.region_id": "Región",
    "faena.sitio_pesca_id": "Sitio de pesca", "faena.tecnico_id": "Técnico",
    "faena.tiempo_efectivo_pesca_h": "Tiempo efectivo de pesca (horas)",
    "faena.tipo_fondo_id": "Tipo de fondo", "faena.tipo_registro": "Tipo de registro",
    "faena.viento_id": "Viento", "faena.zona_pesca_id": "Zona de pesca",
    # faena_arte
    "faena_arte.ancho_anzuelo": "Ancho del anzuelo", "faena_arte.ancho_boca_pulg": "Ancho de boca (pulgadas)",
    "faena_arte.anzuelos_trabajando": "Anzuelos trabajando", "faena_arte.caida_m": "Caída (m)",
    "faena_arte.calibre_piola": "Calibre de piola", "faena_arte.largo_anzuelo": "Largo del anzuelo",
    "faena_arte.longitud_m": "Longitud (m)", "faena_arte.luz_malla_pulg": "Luz de malla (pulgadas)",
    "faena_arte.material": "Material", "faena_arte.metodo": "Método",
    "faena_arte.num_artes": "Número de artes", "faena_arte.num_lances": "Número de lances",
    "faena_arte.numero_anzuelo": "Número de anzuelo", "faena_arte.observaciones": "Observaciones",
    "faena_arte.tiempo_remojo_h": "Tiempo de remojo (horas)", "faena_arte.tipo_anzuelo_id": "Tipo de anzuelo",
    "faena_arte.tipo_arte_id": "Arte de pesca", "faena_arte.tipo_operacion_id": "Tipo de operación",
    # faena_especie_objetivo
    "faena_especie_objetivo.especie_id": "Especie objetivo",
    # gasto
    "gasto.cantidad": "Cantidad", "gasto.descripcion": "Descripción",
    "gasto.monto_total": "Monto total", "gasto.precio_unitario": "Precio unitario",
    "gasto.tipo_gasto_id": "Concepto (tipo de gasto)",
    # interaccion_etp
    "interaccion_etp.cantidad": "Cantidad", "interaccion_etp.especie_id": "Especie (PAP)",
    "interaccion_etp.observaciones": "Observaciones", "interaccion_etp.tipo_interaccion_id": "Tipo de interacción",
    # medicion
    "medicion.ancho_anzuelo": "Ancho del anzuelo", "medicion.captura_id": "Captura asociada",
    "medicion.especie_id": "Especie", "medicion.largo_anzuelo": "Largo del anzuelo",
    "medicion.longitud_furcal_cm": "Longitud furcal (cm)", "medicion.longitud_sospechosa": "Longitud sospechosa",
    "medicion.longitud_total_cm": "Longitud total (cm)", "medicion.madurez_nikolsky": "Madurez (Nikolsky)",
    "medicion.numero_anzuelo": "Número de anzuelo", "medicion.observaciones": "Observaciones",
    "medicion.peso_gonada_gr": "Peso de gónada (g)", "medicion.peso_gr": "Peso (g)",
    "medicion.procesado": "Procesado", "medicion.sexo": "Sexo",
    "medicion.tipo_anzuelo_id": "Tipo de anzuelo",
}

_UNIT_SUFFIX = {"cm": "(cm)", "gr": "(g)", "kg": "(kg)", "lts": "(litros)", "h": "(horas)",
                "m": "(m)", "pulg": "(pulgadas)", "hp": "(HP)", "brazas": "(brazas)"}


def _core_label(key: str) -> str:
    """Friendly Spanish name for a `table.column` core key (curated, else derived)."""
    if key in CORE_LABELS:
        return CORE_LABELS[key]
    col = key.split(".", 1)[-1]
    if col.endswith("_id"):
        col = col[:-3]
    parts = [p for p in col.split("_") if p]
    unit = ""
    if parts and parts[-1] in _UNIT_SUFFIX:
        unit = " " + _UNIT_SUFFIX[parts[-1]]
        parts = parts[:-1]
    text = " ".join(parts).strip()
    text = (text[:1].upper() + text[1:]) if text else col
    return (text + unit).strip()


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
    # enum labels per (table,column) — so a core seleccion field knows its choices
    enums = _q("""
        SELECT c.table_name, c.column_name, e.enumlabel AS lbl
        FROM information_schema.columns c
        JOIN pg_type t ON t.typname = c.udt_name
        JOIN pg_enum e ON e.enumtypid = t.oid
        WHERE c.table_schema='public' AND c.table_name = ANY(%s)
        ORDER BY e.enumsortorder
    """, (CORE_TABLES,))
    enummap: dict = {}
    for e in enums:
        enummap.setdefault((e["table_name"], e["column_name"]), []).append(e["lbl"])

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
        key = f"{t}.{col}"
        entry = {"label": key, "friendly": _core_label(key), "tipo": tipo}
        if catalogo:
            entry["catalogo"] = catalogo
        if tipo == "seleccion_unica" and enummap.get((t, col)):
            entry["opciones"] = enummap[(t, col)]
        reg[key] = entry
    return reg


@st.cache_data(ttl=300, show_spinner=False)
def list_formatos() -> list[dict]:
    return _q("SELECT id::text, codigo, nombre FROM cat_formato_origen ORDER BY codigo")


@st.cache_data(ttl=300, show_spinner=False)
def formatos_en_uso() -> list[dict]:
    """Formats the app actually uses (they have forms or curated lists) — the
    other cat_formato_origen rows are historical imports and only clutter pickers."""
    return _q("""
        SELECT fo.id::text, fo.codigo, fo.nombre
        FROM cat_formato_origen fo
        WHERE EXISTS (SELECT 1 FROM formulario f WHERE f.formato_origen_id = fo.id)
           OR EXISTS (SELECT 1 FROM lista_opcion lo WHERE lo.formato_origen_id = fo.id)
        ORDER BY fo.codigo
    """)


_CAT_NAME_COL = {"cat_especie": "nombre_comun", "cat_formato_origen": "codigo"}


@st.cache_data(ttl=300, show_spinner=False)
def _cat_options(tabla: str) -> list[dict]:
    """[{id, nombre}] for a cat_* table — resolves UUIDs to names in the wizard.
    Kept local so form_builder stays a dependency-free base module."""
    nc = _CAT_NAME_COL.get(tabla, "nombre")
    try:
        return _q(f'SELECT id::text AS id, {nc} AS nombre FROM public."{tabla}" '
                  f'ORDER BY {nc} LIMIT 1000')
    except Exception:  # noqa: BLE001 — unknown/edge catalog: fall back to no names
        return []


def _cat_label_map(tabla: str) -> dict:
    return {o["id"]: o["nombre"] for o in _cat_options(tabla)}


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

    # a core column is a unique sink — two fields writing it corrupt the data
    seen_cols: dict = {}
    for ck, c in all_fields.items():
        b = c.get("binding") or {}
        if b.get("tipo") == "core" and b.get("columna"):
            col = b["columna"]
            if col in seen_cols:
                errores.append(f"campo «{ck}»: el dato del sistema '{col}' ya lo usa el "
                               f"campo «{seen_cols[col]}» (no se puede repetir).")
            else:
                seen_cols[col] = ck

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
# Editor <-> dataframe (de)serialization (pure).
# NOTE: no longer used by the UI (the wizard edits the campo dicts directly,
# preserving unknown keys); kept because round-trip tests exercise them.
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
    if isinstance(defn, str):
        defn = json.loads(defn or "{}")
    return {"id": f["id"], "nombre": f["nombre"], "formato_id": f["formato_origen_id"],
            "version": f["version"], "estado": f["estado"],
            "secciones": defn.get("secciones", []), "constantes": f.get("constantes") or {}}


def _template_work(src_id: str) -> dict:
    """A fresh borrador seeded with another form's structure (deep-copied), so the
    source is never mutated. Version recomputed for the source's formato."""
    f = load_formulario(src_id)
    defn = f.get("definicion") or {}
    if isinstance(defn, str):
        defn = json.loads(defn or "{}")
    return {"id": None, "nombre": f"{f['nombre']} (copia)",
            "formato_id": f["formato_origen_id"], "version": next_version(f["formato_origen_id"]),
            "estado": "borrador", "secciones": copy.deepcopy(defn.get("secciones", [])),
            "constantes": copy.deepcopy(f.get("constantes") or {})}


# =====================================================================
# Wizard (plan R2 Phase D): ① Datos → ② Secciones → ③ Campos → ④ Publicar.
# Section/field dialogs edit the definition dicts DIRECTLY (no DataFrame
# round-trip), so unknown keys are preserved by construction — the class of
# bug that once dropped lista/permite_proponer cannot recur here.
# =====================================================================
PASOS = ["① Datos", "② Secciones", "③ Campos", "④ Revisar y publicar"]

TIPO_LABELS = {
    "texto": "Texto", "entero": "Número entero", "decimal": "Número decimal",
    "fecha": "Fecha", "hora": "Hora", "catalogo": "Catálogo (lista de nombres)",
    "seleccion_unica": "Selección única", "multiseleccion": "Selección múltiple",
    "bool": "Sí / No", "geo": "Ubicación (GPS)", "foto": "Foto",
}
BIND_LABELS = {
    "core": "Dato del sistema (se guarda en la base)",
    "custom": "Personalizado (dato extra)",
    "ui": "Solo interfaz (no se guarda)",
}
ENTIDAD_LABELS = {
    "faena": "Faena (viaje)", "faena_especie_objetivo": "Especies objetivo",
    "faena_arte": "Artes de pesca", "captura": "Capturas", "medicion": "Mediciones",
    "carnada": "Carnada", "interaccion_etp": "Interacciones ETP", "gasto": "Gastos",
}

# Condition operators (visible_si), Spanish labels. "in" and >/< are offered only
# when the referenced field supports them (a value list / a numeric field).
OP_LABELS = {"==": "es igual a", "!=": "no es igual a", "es uno de": "es uno de",
             ">": "mayor que", "<": "menor que", "in": "es uno de"}


def _field_is_numeric(campo: dict) -> bool:
    return campo.get("tipo") in ("entero", "decimal")


def _field_choices(campo: dict, bindable: dict) -> list | None:
    """A referenced field's possible (valor, etiqueta) values, or None for free input.

    Priority: explicit opciones on the campo → catalog names → core-enum labels →
    Sí/No for bool. Numeric/text/date fields return None (free value input)."""
    ops = campo.get("opciones")
    if ops:
        out = []
        for o in ops:
            if isinstance(o, dict):
                out.append((o.get("valor"), o.get("label") or str(o.get("valor"))))
            else:
                out.append((o, str(o)))
        return out
    b = campo.get("binding") or {}
    if campo.get("tipo") == "catalogo":
        cat = b.get("catalogo") or bindable.get(b.get("columna") or "", {}).get("catalogo")
        if cat:
            return [(o["id"], o["nombre"]) for o in _cat_options(cat)]
    if b.get("tipo") == "core" and bindable.get(b.get("columna") or "", {}).get("opciones"):
        return [(v, str(v)) for v in bindable[b["columna"]]["opciones"]]
    if campo.get("tipo") == "bool":
        return [(True, "Sí"), (False, "No")]
    return None


def _ops_for(campo: dict, bindable: dict) -> list[tuple[str, str]]:
    """(op_code, label) comparisons valid against the referenced field."""
    out = [("==", OP_LABELS["=="]), ("!=", OP_LABELS["!="])]
    if _field_choices(campo, bindable) is not None:
        out.append(("in", OP_LABELS["in"]))
    if _field_is_numeric(campo):
        out += [(">", OP_LABELS[">"]), ("<", OP_LABELS["<"])]
    return out


def _slug(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn").lower()
    out = "".join(ch if ch.isalnum() else "_" for ch in s).strip("_")
    while "__" in out:
        out = out.replace("__", "_")
    return out or "campo"


def _set_or_pop(d: dict, k: str, v):
    """Write a managed key only when it has a value — empty/False keys stay out
    of the JSON, and keys we don't manage are never touched."""
    if v in (None, "", False, [], {}):
        d.pop(k, None)
    else:
        d[k] = v


def _dlg_nonce() -> int:
    """Fresh widget-key namespace per dialog opening (dialog widgets would
    otherwise show stale values when reopening the same item)."""
    st.session_state["fb_dlg"] = st.session_state.get("fb_dlg", 0) + 1
    return st.session_state["fb_dlg"]


# ---- pure builders (no Streamlit): what the dialogs write back ------
def build_seccion(s: dict, v: dict) -> dict:
    """New section dict from dialog values; unknown keys of `s` are preserved."""
    out = dict(s)
    out["key"] = (v.get("key") or "").strip() or _slug(v.get("titulo", ""))
    _set_or_pop(out, "titulo", (v.get("titulo") or "").strip())
    out.setdefault("campos", [])
    _set_or_pop(out, "entidad", v.get("entidad"))
    _set_or_pop(out, "repetible", bool(v.get("repetible")))
    _set_or_pop(out, "boton_agregar",
                (v.get("boton_agregar") or "").strip() if v.get("repetible") else "")
    min_v = int(v.get("min") or 0)
    if min_v or "min" in s:   # keep an explicit min:0 the definition already had
        out["min"] = min_v
    else:
        out.pop("min", None)
    _set_or_pop(out, "visible_si", _pj(v.get("visible_si_raw")))
    return out


def build_campo(c: dict, v: dict, bindable: dict) -> dict:
    """New campo dict from dialog values; unknown keys of `c` (incl. `lista`)
    are preserved — the curated-list wiring can't be dropped by construction."""
    out = dict(c)
    out["key"] = (v.get("key") or "").strip() or _slug(v.get("label", ""))
    _set_or_pop(out, "label", (v.get("label") or "").strip())
    out["tipo"] = v["tipo"]
    _set_or_pop(out, "requerido", bool(v.get("requerido")))
    _set_or_pop(out, "autocompletar", bool(v.get("autocompletar")))
    _set_or_pop(out, "ayuda", (v.get("ayuda") or "").strip())
    nb = dict(c.get("binding") or {})
    nb["tipo"] = v["bind_tipo"]
    col = (v.get("bind_columna") or "").strip()
    _set_or_pop(nb, "columna", col if v["bind_tipo"] == "core" else "")
    if v["bind_tipo"] == "core" and col in bindable and bindable[col].get("catalogo"):
        nb["catalogo"] = nb.get("catalogo") or bindable[col]["catalogo"]
    elif v["tipo"] == "catalogo":
        _set_or_pop(nb, "catalogo", v.get("catalogo"))
    out["binding"] = nb
    if v.get("flags_managed"):
        _set_or_pop(out, "permite_proponer", bool(v.get("permite_proponer")))
        _set_or_pop(out, "permite_otro_texto", bool(v.get("permite_otro_texto")))
    if v.get("opciones_simple") is not None:
        _set_or_pop(out, "opciones", v["opciones_simple"])
    # structured editors pass already-parsed values (visible_si, validacion…)
    for prop_name, val in (v.get("managed") or {}).items():
        _set_or_pop(out, prop_name, val)
    for prop_name, raw in (v.get("adv") or {}).items():
        _set_or_pop(out, prop_name, _pj(raw))
    return out


def _all_field_keys(work: dict, skip: dict | None = None) -> set:
    """Every campo `key` in the form (optionally excluding one campo object)."""
    return {c.get("key") for s in work["secciones"] for c in (s.get("campos") or [])
            if c is not skip}


def _unique_key(base: str, taken: set) -> str:
    """`base`, else base_2/base_3… until it isn't already in `taken`."""
    base = base or "campo"
    if base not in taken:
        return base
    i = 2
    while f"{base}_{i}" in taken:
        i += 1
    return f"{base}_{i}"


def _add_core_field(work: dict, sec: dict, key: str, bindable: dict):
    """Append a core-bound campo for schema column `key` with friendly defaults."""
    entry = bindable[key]
    kv = _unique_key(_slug(entry["friendly"]), _all_field_keys(work))
    v = {"key": kv, "label": entry["friendly"], "tipo": entry["tipo"],
         "requerido": False, "autocompletar": False, "ayuda": "",
         "bind_tipo": "core", "bind_columna": key, "catalogo": entry.get("catalogo", ""),
         "flags_managed": False, "permite_proponer": None, "permite_otro_texto": None,
         "opciones_simple": None, "adv": {}}
    sec.setdefault("campos", []).append(build_campo({}, v, bindable))


def _unbind_core(c: dict):
    """A copy can't reuse a core column (unique sink) → make it a custom field."""
    b = c.get("binding") or {}
    if b.get("tipo") == "core" and b.get("columna"):
        c["binding"] = {"tipo": "custom"}


def _dup_campo(work: dict, campos: list, i: int) -> bool:
    """Insert a deep copy of campo i right after it; return True if it was unbound."""
    new = copy.deepcopy(campos[i])
    new["key"] = _unique_key(_slug(new.get("label") or new.get("key")), _all_field_keys(work))
    new["label"] = f"{new.get('label') or new.get('key') or 'Campo'} (copia)"
    was_core = (new.get("binding") or {}).get("tipo") == "core" and (new.get("binding") or {}).get("columna")
    _unbind_core(new)
    campos.insert(i + 1, new)
    return bool(was_core)


def _dup_seccion(work: dict, i: int):
    """Insert a deep copy of section i right after it (fresh keys; core fields unbound)."""
    secs = work["secciones"]
    new = copy.deepcopy(secs[i])
    sec_keys = {s.get("key") for s in secs}
    new["key"] = _unique_key(_slug(new.get("titulo") or new.get("key")), sec_keys)
    new["titulo"] = f"{new.get('titulo') or new.get('key') or 'Sección'} (copia)"
    taken = _all_field_keys(work)
    for c in new.get("campos") or []:
        c["key"] = _unique_key(_slug(c.get("label") or c.get("key")), taken)
        taken.add(c["key"])
        _unbind_core(c)
    secs.insert(i + 1, new)


# ---- paso ① Datos ---------------------------------------------------
def _paso_datos(work: dict, published: bool, formatos: list[dict]):
    c1, c2, c3 = st.columns([3, 2, 1])
    work["nombre"] = c1.text_input("Nombre del formulario", work["nombre"], key="fb_nombre",
                                   disabled=published)
    fmt_ids = [f["id"] for f in formatos]
    fmt_label = {f["id"]: f"{f['codigo']} — {f['nombre']}" for f in formatos}
    cur_fmt = work["formato_id"] if work["formato_id"] in fmt_ids else (fmt_ids[0] if fmt_ids else None)
    if fmt_ids:
        work["formato_id"] = c2.selectbox(
            "Formato / región", fmt_ids, index=fmt_ids.index(cur_fmt) if cur_fmt else 0,
            format_func=lambda i: fmt_label.get(i, i), key="fb_formato",
            disabled=published or work["id"] is not None)
    c2.checkbox("Mostrar formatos históricos", key="fb_hist",
                help="Formatos de datos importados; solo si vas a crear un formulario nuevo "
                     "para uno de ellos.")
    c3.metric("Versión", work["version"])

    with st.expander("⚙️ Avanzado: constantes del formulario (JSON)"):
        st.caption("Valores fijos que la tableta llena sola (región, zona, tipo de registro…).")
        cons_raw = st.text_area("Constantes (JSON)",
                                json.dumps(work["constantes"], ensure_ascii=False, indent=2),
                                height=120, key="fb_constantes", disabled=published,
                                label_visibility="collapsed")
        try:
            work["constantes"] = json.loads(cons_raw) if cons_raw.strip() else {}
            st.session_state["fb_cons_err"] = None
        except ValueError as e:
            st.session_state["fb_cons_err"] = str(e)
            st.error(f"JSON inválido — {e}")


# ---- paso ② Secciones -----------------------------------------------
@st.dialog("Sección del formulario")
def _sec_dialog(work: dict, idx: int | None):
    from console_ui import confirm_button
    s = {} if idx is None else work["secciones"][idx]
    k = f"fbsd_{st.session_state.get('fb_dlg', 0)}"
    titulo = st.text_input("Título (lo que ve el técnico)", s.get("titulo", ""), key=f"{k}_t")
    ents = [""] + CORE_TABLES
    entidad = st.selectbox(
        "Dónde guarda sus datos", ents,
        index=ents.index(s.get("entidad", "")) if s.get("entidad", "") in ents else 0,
        format_func=lambda e: "— (solo interfaz) —" if e == "" else ENTIDAD_LABELS.get(e, e),
        key=f"{k}_e")
    repet = st.checkbox("Repetible — el técnico puede agregar varias (p. ej. una por especie)",
                        value=bool(s.get("repetible")), key=f"{k}_r")
    boton = s.get("boton_agregar", "")
    if repet:
        boton = st.text_input("Texto del botón para agregar otra", boton, key=f"{k}_b",
                              placeholder="p. ej. + Agregar captura")
    with st.expander("⚙️ Avanzado"):
        key_in = st.text_input("Clave interna", s.get("key") or _slug(titulo), key=f"{k}_k",
                               help="Identificador técnico; no lo cambies en un formulario en uso.")
        min_in = st.number_input("Mínimo de registros (si es repetible)", min_value=0,
                                 value=int(s.get("min") or 0), key=f"{k}_m")
        vis_raw = st.text_area("Visible solo si… (JSON)", _j(s.get("visible_si")), key=f"{k}_v",
                               help='Ej.: {"campo": "hubo_pesca", "valor": true}')
    if st.button("💾 Guardar sección", key=f"{k}_save", type="primary", width="stretch"):
        if not (titulo.strip() or key_in.strip()):
            st.error("Ponle un título a la sección.")
        else:
            out = build_seccion(s, {"key": key_in, "titulo": titulo, "entidad": entidad,
                                    "repetible": repet, "boton_agregar": boton,
                                    "min": min_in, "visible_si_raw": vis_raw})
            if idx is None:
                work["secciones"].append(out)
            else:
                work["secciones"][idx] = out
            st.rerun()
    if idx is not None:
        st.divider()
        ncamp = len(s.get("campos") or [])
        if ncamp:
            st.caption(f"⚠️ Esta sección tiene {ncamp} campo(s); se eliminan con ella.")
        if confirm_button("🗑️ Eliminar sección", key=f"{k}_del"):
            del work["secciones"][idx]
            st.rerun()


def _paso_secciones(work: dict, published: bool):
    secs = work["secciones"]
    if not secs:
        st.info("Este formulario aún no tiene secciones — agrega la primera.")
    for i, s in enumerate(secs):
        with st.container(border=True):
            c = st.columns([5, 0.7, 0.7, 0.7, 1.1], vertical_alignment="center")
            ent = ENTIDAD_LABELS.get(s.get("entidad", ""), s.get("entidad", ""))
            bits = [b for b in (ent, f"{len(s.get('campos') or [])} campo(s)",
                                "🔁 repetible" if s.get("repetible") else "") if b]
            c[0].markdown(f"**{s.get('titulo') or s.get('key')}**  \n{' · '.join(bits)}")
            if c[1].button("⧉", key=f"fbs_dup_{i}", disabled=published,
                           help="Duplicar esta sección con sus campos", width="stretch"):
                from console_ui import flash
                _dup_seccion(work, i)
                flash("Sección duplicada (los datos del sistema quedan sin vincular).", "⧉")
                st.rerun()
            if c[2].button("↑", key=f"fbs_up_{i}", disabled=published or i == 0,
                           width="stretch"):
                secs[i - 1], secs[i] = secs[i], secs[i - 1]
                st.rerun()
            if c[3].button("↓", key=f"fbs_dn_{i}", disabled=published or i == len(secs) - 1,
                           width="stretch"):
                secs[i + 1], secs[i] = secs[i], secs[i + 1]
                st.rerun()
            if c[4].button("✏️ Editar", key=f"fbs_ed_{i}", disabled=published,
                           width="stretch"):
                _dlg_nonce()
                _sec_dialog(work, i)
    if st.button("➕ Agregar sección", key="fbs_add", disabled=published):
        _dlg_nonce()
        _sec_dialog(work, None)


# ---- paso ③ Campos --------------------------------------------------
@st.dialog("Campo del formulario", width="large")
def _campo_dialog(work: dict, sec: dict, idx: int | None, bindable: dict):
    from console_ui import confirm_button
    c = {} if idx is None else sec["campos"][idx]
    k = f"fbcd_{st.session_state.get('fb_dlg', 0)}"

    label = st.text_input("Etiqueta (lo que ve el técnico)", c.get("label", ""), key=f"{k}_l")
    tipo = st.selectbox("Tipo de dato", TIPOS,
                        index=TIPOS.index(c.get("tipo", "texto")) if c.get("tipo", "texto") in TIPOS else 0,
                        format_func=lambda t: TIPO_LABELS.get(t, t), key=f"{k}_tp")
    cc = st.columns(2)
    req = cc[0].checkbox("Obligatorio", value=bool(c.get("requerido")), key=f"{k}_rq")
    auto = cc[1].checkbox("Autocompletar con el valor anterior",
                          value=bool(c.get("autocompletar")), key=f"{k}_au")
    ayuda = st.text_input("Texto de ayuda (opcional)", c.get("ayuda", ""), key=f"{k}_ay")

    st.divider()
    b = dict(c.get("binding") or {})
    bt = st.radio("Origen del dato", BIND_TIPOS,
                  index=BIND_TIPOS.index(b.get("tipo", "core")) if b.get("tipo", "core") in BIND_TIPOS else 0,
                  format_func=lambda x: BIND_LABELS.get(x, x), horizontal=True, key=f"{k}_bt")
    col = b.get("columna", "")
    if bt == "core":
        bind_cols = [""] + sorted(bindable.keys(), key=lambda x: bindable[x]["friendly"])
        col = st.selectbox("Dato del sistema", bind_cols,
                           index=bind_cols.index(col) if col in bind_cols else 0,
                           format_func=lambda x: "— elige un dato —" if x == ""
                           else bindable.get(x, {}).get("friendly", x),
                           key=f"{k}_bc",
                           help="A qué dato real del monitoreo corresponde este campo.")
        if col and bindable.get(col, {}).get("catalogo"):
            st.caption(f"Catálogo asociado: `{bindable[col]['catalogo']}`")

    cat_sel = b.get("catalogo", "")
    if tipo == "catalogo" and not (bt == "core" and bindable.get(col, {}).get("catalogo")):
        cat_tables = sorted({v["catalogo"] for v in bindable.values() if v.get("catalogo")})
        cat_opts = [""] + cat_tables
        cat_sel = st.selectbox("Catálogo de nombres", cat_opts,
                               index=cat_opts.index(cat_sel) if cat_sel in cat_opts else 0,
                               key=f"{k}_cat")

    flags_managed = tipo in ("catalogo", "seleccion_unica", "multiseleccion")
    prop = otro = None
    if flags_managed:
        if c.get("lista"):
            st.info(f"📑 Este campo usa la lista curada **«{c['lista']}»**. Sus opciones se "
                    "administran en **📑 Listas del formulario**, no aquí.")
        fc = st.columns(2)
        prop = fc[0].checkbox("El técnico puede proponer nombres nuevos",
                              value=bool(c.get("permite_proponer")), key=f"{k}_pp")
        otro = fc[1].checkbox("Permite escribir «otro» (texto libre)",
                              value=bool(c.get("permite_otro_texto")), key=f"{k}_ot")

    opciones_simple = None
    if tipo in ("seleccion_unica", "multiseleccion"):
        cur_opts = c.get("opciones") or []
        if all(isinstance(o, str) for o in cur_opts):
            txt = st.text_area("Opciones (una por línea)", "\n".join(cur_opts), key=f"{k}_op")
            opciones_simple = [ln.strip() for ln in txt.splitlines() if ln.strip()]
        else:
            st.caption("Las opciones de este campo tienen formato avanzado — edítalas en ⚙️ Avanzado.")

    # ---- reglas del valor (validación mín/máx) — sólo números ----------
    managed: dict = {}
    val_cur = c.get("validacion") or {}
    val_structured = tipo in ("entero", "decimal") and isinstance(val_cur, dict) \
        and set(val_cur) <= {"min", "max"}
    if val_structured:
        st.divider()
        st.markdown("**Reglas del valor** (opcional)")
        is_int = tipo == "entero"

        def _numbox(colobj, label, curv, kk):
            if is_int:
                return int(colobj.number_input(label, value=int(curv), step=1, key=kk))
            fx = float(colobj.number_input(label, value=float(curv), step=0.01,
                                           format="%g", key=kk))
            return int(fx) if fx == int(fx) else fx  # keep whole decimals as ints (v8 parity)

        vc = st.columns(2)
        use_min = vc[0].checkbox("Poner un mínimo", value="min" in val_cur, key=f"{k}_vmin_on")
        use_max = vc[1].checkbox("Poner un máximo", value="max" in val_cur, key=f"{k}_vmax_on")
        newval: dict = {}
        if use_min:
            newval["min"] = _numbox(vc[0], "Valor mínimo", val_cur.get("min", 0), f"{k}_vmin")
        if use_max:
            newval["max"] = _numbox(vc[1], "Valor máximo", val_cur.get("max", 0), f"{k}_vmax")
        if use_min and use_max and newval["max"] < newval["min"]:
            st.warning("El máximo es menor que el mínimo.")
        managed["validacion"] = newval  # {} → _set_or_pop removes the key

    with st.expander("⚙️ Avanzado"):
        key_in = st.text_input("Clave interna", c.get("key") or _slug(label), key=f"{k}_k",
                               help="Identificador técnico; no lo cambies en un formulario en uso.")
        adv: dict = {}
        adv_props = ["visible_si", "filtrado_por", "opciones_prioritarias"]
        if not val_structured:   # exotic/non-numeric validación stays editable as JSON
            adv_props.append("validacion")
        if opciones_simple is None and tipo in ("seleccion_unica", "multiseleccion"):
            adv_props = ["opciones"] + adv_props
        for prop_name in adv_props:
            adv[prop_name] = st.text_area(f"{prop_name} (JSON)", _j(c.get(prop_name)),
                                          key=f"{k}_{prop_name}")

    if st.button("💾 Guardar campo", key=f"{k}_save", type="primary", width="stretch"):
        key_val = key_in.strip() or _slug(label)
        otros_keys = set()
        for s2 in work["secciones"]:
            for i2, c2 in enumerate(s2.get("campos") or []):
                if s2 is sec and idx is not None and i2 == idx:
                    continue
                otros_keys.add(c2.get("key"))
        if not label.strip():
            st.error("Ponle una etiqueta al campo.")
        elif key_val in otros_keys:
            st.error(f"Ya existe otro campo con la clave «{key_val}» — cambia la clave en ⚙️ Avanzado.")
        else:
            out = build_campo(c, {"key": key_val, "label": label, "tipo": tipo,
                                  "requerido": req, "autocompletar": auto, "ayuda": ayuda,
                                  "bind_tipo": bt, "bind_columna": col, "catalogo": cat_sel,
                                  "flags_managed": flags_managed, "permite_proponer": prop,
                                  "permite_otro_texto": otro, "opciones_simple": opciones_simple,
                                  "managed": managed, "adv": adv}, bindable)
            if idx is None:
                sec["campos"].append(out)
            else:
                sec["campos"][idx] = out
            st.rerun()

    if idx is not None:
        st.divider()
        if confirm_button("🗑️ Eliminar campo", key=f"{k}_del"):
            del sec["campos"][idx]
            st.rerun()


def _paso_campos(work: dict, published: bool, bindable: dict):
    from console_ui import flash
    secs = work["secciones"]
    if not secs:
        st.info("Primero crea una sección en el paso ② Secciones.")
        return
    titles = [s.get("titulo") or s.get("key") for s in secs]
    idxs = list(range(len(secs)))
    pick = st.segmented_control("Sección", idxs, format_func=lambda i: titles[i],
                                key="fb_sec_pick", default=0)
    if pick is None or pick not in idxs:
        pick = 0
    sec = secs[pick]
    ent = sec.get("entidad", "")
    campos = sec.setdefault("campos", [])

    # ---- biblioteca de datos: pick a known data point to add ---------
    if not published:
        used = {(c.get("binding") or {}).get("columna") for s in secs
                for c in (s.get("campos") or [])
                if (c.get("binding") or {}).get("tipo") == "core"}
        with st.container(border=True):
            st.markdown("**➕ Agregar un dato del monitoreo**")
            if not ent:
                st.caption("Esta sección no guarda datos del sistema (solo interfaz). "
                           "Usa «dato personalizado» más abajo.")
            else:
                q = st.text_input("🔎 Buscar dato", key=f"fb_lib_q_{pick}",
                                  placeholder="p. ej. peso, longitud, especie…",
                                  label_visibility="collapsed")
                ql = q.strip().lower()
                avail = [k for k in sorted(bindable, key=lambda x: bindable[x]["friendly"])
                         if k.split(".")[0] == ent and k not in used
                         and (ql in bindable[k]["friendly"].lower() if ql else True)]
                if avail:
                    st.caption("Toca un dato para agregarlo al formulario:")
                    ncol = 3
                    cols = st.columns(ncol)
                    for i, k in enumerate(avail):
                        if cols[i % ncol].button(f"＋ {bindable[k]['friendly']}",
                                                 key=f"fbadd_{pick}_{k}", width="stretch"):
                            _add_core_field(work, sec, k, bindable)
                            flash(f"Agregado: {bindable[k]['friendly']}")
                            st.rerun()
                else:
                    st.caption("No hay más datos disponibles para esta búsqueda."
                               if ql else "Ya agregaste todos los datos de esta sección.")
            if st.button("➕ Agregar dato personalizado (avanzado)",
                         key=f"fbc_add_{pick}", width="stretch"):
                _dlg_nonce()
                _campo_dialog(work, sec, None, bindable)

    # ---- campos ya en el formulario ---------------------------------
    st.markdown("**En el formulario:**")
    if not campos:
        st.info("Esta sección aún no tiene campos — agrega el primero arriba.")
    for i, c in enumerate(campos):
        with st.container(border=True):
            cc = st.columns([5, 0.7, 0.7, 0.7, 1.1], vertical_alignment="center")
            badges = [TIPO_LABELS.get(c.get("tipo"), c.get("tipo"))]
            if c.get("requerido"):
                badges.append("✳️ obligatorio")
            if c.get("lista"):
                badges.append(f"📑 lista «{c['lista']}»")
            if c.get("permite_proponer"):
                badges.append("➕ proponer")
            if c.get("visible_si"):
                badges.append("👁️ condicional")
            cc[0].markdown(f"**{c.get('label') or c.get('key')}**  \n{' · '.join(badges)}")
            if cc[1].button("⧉", key=f"fbc_{pick}_dup_{i}", disabled=published,
                            help="Duplicar este campo", width="stretch"):
                if _dup_campo(work, campos, i):
                    flash("Copia creada como dato personalizado (un dato del sistema no se "
                          "puede repetir).", "⧉")
                else:
                    flash("Campo duplicado.", "⧉")
                st.rerun()
            if cc[2].button("↑", key=f"fbc_{pick}_up_{i}", disabled=published or i == 0,
                            width="stretch"):
                campos[i - 1], campos[i] = campos[i], campos[i - 1]
                st.rerun()
            if cc[3].button("↓", key=f"fbc_{pick}_dn_{i}",
                            disabled=published or i == len(campos) - 1, width="stretch"):
                campos[i + 1], campos[i] = campos[i], campos[i + 1]
                st.rerun()
            if cc[4].button("✏️ Editar", key=f"fbc_{pick}_ed_{i}", disabled=published,
                            width="stretch"):
                _dlg_nonce()
                _campo_dialog(work, sec, i, bindable)

    # ---- vista previa en vivo de esta sección -----------------------
    st.divider()
    st.markdown("##### 👁️ Así lo verá el técnico")
    render_preview({"secciones": [sec]}, {})


# ---- paso ④ Revisar y publicar --------------------------------------
def _paso_revisar(work: dict, published: bool, bindable: dict):
    from console_ui import friendly_error, flash
    definicion = {"secciones": work["secciones"]}
    errores, advert = validate_definition(definicion, work["constantes"], bindable)
    cons_err = st.session_state.get("fb_cons_err")
    if cons_err:
        errores = [f"Constantes JSON inválido: {cons_err}"] + errores
    a1, a2 = st.columns(2)
    if errores:
        a1.error(f"{len(errores)} error(es) — corrígelos antes de publicar")
    else:
        a1.success("Válido ✓")
    if advert:
        a2.warning(f"{len(advert)} advertencia(s)")
    with st.expander("🔎 Detalle de la validación", expanded=bool(errores)):
        for e in errores:
            st.markdown(f"- ❌ {e}")
        for w in advert:
            st.markdown(f"- ⚠️ {w}")
        if not errores and not advert:
            st.caption("Sin problemas.")

    st.divider()
    st.markdown("##### 👁️ Vista previa (lo que verá el técnico)")
    render_preview(definicion, work["constantes"])

    st.divider()
    if work["id"] is None and not published:
        st.caption("Guarda el borrador (💾 abajo) antes de publicar.")
    pub_disabled = published or bool(errores) or work["id"] is None
    if st.button("🚀 Publicar esta versión", key="fb_publish", type="primary",
                 disabled=pub_disabled,
                 help="Publicar vuelve la versión inmutable; la tableta usa la última publicada."):
        try:
            publish(work["id"])
            st.session_state["fb_loaded"] = None
            flash("Formulario publicado (la versión queda inmutable).", "🚀")
            st.rerun()
        except Exception as e:  # noqa: BLE001
            st.error(f"No se pudo publicar: {friendly_error(e)}")


def render_form_builder():
    from console_ui import page_header, friendly_error, flash
    page_header(
        "🛠️ Formularios",
        "Edita y publica las versiones del formulario que llena el técnico en la tableta.",
        help_md=(
            "Trabaja en 4 pasos:\n\n"
            "1. **① Datos** — nombre y formato del formulario.\n"
            "2. **② Secciones** — las pantallas del formulario (Datos del viaje, Capturas…).\n"
            "3. **③ Campos** — qué se captura en cada sección; edita cada campo con ✏️.\n"
            "4. **④ Revisar y publicar** — validación, vista previa y 🚀 Publicar.\n\n"
            "Una versión **publicada** no se puede tocar: crea una **🌱 Nueva versión**. "
            "Guarda tu borrador con 💾 (siempre visible abajo)."
        ),
    )

    try:
        bindable = load_bindable_core()
        # live formats by default; the toggle (rendered below) exposes historical ones
        formatos = list_formatos() if st.session_state.get("fb_hist") else formatos_en_uso()
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

    # a new form can start blank or be seeded from an existing one (plantilla)
    tpl = "__blank__"
    if sel == "__new__" and formularios:
        tpl_opts = ["__blank__"] + [f["id"] for f in formularios]

        def _tpl_label(o):
            if o == "__blank__":
                return "En blanco"
            f = by_id.get(o)
            return f"Copiar de: [{f['formato']}] {f['nombre']} · v{f['version']}" if f else str(o)

        tpl = st.selectbox("Basar en", tpl_opts, format_func=_tpl_label, key="fb_tpl",
                           help="Empieza desde cero o copia todas las secciones y campos de "
                                "otro formulario para no armarlo de nuevo.")

    # load the chosen form into the working copy once per selection/template change
    marker = (sel, tpl)
    if st.session_state.get("fb_loaded") != marker:
        if sel == "__new__":
            st.session_state["fb_work"] = _blank_work() if tpl == "__blank__" else _template_work(tpl)
        else:
            st.session_state["fb_work"] = _load_into_work(load_formulario(sel))
        st.session_state["fb_loaded"] = marker
        # drop Paso ① widget state so the boxes re-init from the new work (else a
        # keyed text_input keeps its old value and overwrites the seeded one)
        for _wk in ("fb_nombre", "fb_formato", "fb_constantes"):
            st.session_state.pop(_wk, None)
    work = st.session_state["fb_work"]
    published = work["estado"] == "publicado"

    if published:
        w1, w2 = st.columns([3, 1], vertical_alignment="center")
        w1.warning("Esta versión está **publicada** (inmutable). Usa **Nueva versión** para editarla.")
        if w2.button("🌱 Nueva versión", key="fb_newver", width="stretch"):
            try:
                nid = new_version_from(work["id"])
                st.session_state["fb_loaded"] = None
                st.session_state["fb_sel"] = nid
                flash("Nueva versión creada como borrador.", "🌱")
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"No se pudo crear la versión: {friendly_error(e)}")

    # ---- wizard -----------------------------------------------------
    paso = st.segmented_control("Paso", PASOS, key="fb_step", default=PASOS[0],
                                label_visibility="collapsed")
    paso = paso if paso in PASOS else PASOS[0]

    if paso == PASOS[0]:
        _paso_datos(work, published, formatos)
    elif paso == PASOS[1]:
        _paso_secciones(work, published)
    elif paso == PASOS[2]:
        _paso_campos(work, published, bindable)
    else:
        _paso_revisar(work, published, bindable)

    # ---- footer: save is always at hand -----------------------------
    st.divider()
    cons_err = st.session_state.get("fb_cons_err")
    f1, f2 = st.columns([3, 1], vertical_alignment="center")
    f1.caption("✅ Versión publicada — solo lectura. Usa «Nueva versión» para editar."
               if published else
               "📝 Borrador — guarda tus cambios antes de salir. Publica en el paso ④.")
    save_disabled = published or not work["nombre"].strip() or bool(cons_err)
    if f2.button("💾 Guardar borrador", key="fb_save", disabled=save_disabled,
                 width="stretch"):
        try:
            fid = save_borrador(work["id"], work["nombre"], work["formato_id"],
                                work["version"], {"secciones": work["secciones"]},
                                work["constantes"])
            work["id"] = fid
            # land on the saved form (so a new/plantilla draft doesn't reset to blank)
            st.session_state["fb_sel"] = fid
            st.session_state["fb_loaded"] = None  # force reload list/state next run
            flash("Borrador guardado.", "💾")
            st.rerun()
        except Exception as e:  # noqa: BLE001
            st.error(f"No se pudo guardar: {friendly_error(e)}")



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
