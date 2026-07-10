"""
Data export for R (M3 / OD-19) — the dashboard's #1 stated purpose: a place to pull
filtered fisheries data for analysis in R. NOT a visualization tool.

Filtered CSV / Parquet download with a pre-download "heads-up" preview, honoring the
data-honesty rules from AppDashboardSpec/02:
  - tipo_registro MASIVO vs BITACORA is a *mutually-exclusive* selector and the column
    always rides along so R can segregate — they must never be summed together.
  - the ~136K orphan mediciones (faena_id NULL) are biologically valid size data but
    have no trip context: a toggle includes them for species-only (medición) export and
    any trip-context filter naturally drops them.
  - longitud_sospechosa (per-species outlier flag) is excluded by default — wired here,
    active once the flag column exists (item D).

Reuses the form_builder DB layer (same DATABASE_URL).
"""
from __future__ import annotations

import datetime as _dt
import io

import pandas as pd
import streamlit as st

from form_builder import get_conn, _q

try:
    import pyarrow  # noqa: F401  (df.to_parquet backend)
    HAS_PARQUET = True
except ImportError:
    HAS_PARQUET = False


# ---------------------------------------------------------------------
# Dataset definitions: base FROM/JOINs, SELECT, and which filters apply.
# Catalog FKs are resolved to readable names (R wants names, not UUIDs).
# ---------------------------------------------------------------------
_FAENA_CTX = """
  LEFT JOIN faena f               ON f.id  = {base}.faena_id
  LEFT JOIN cat_region r          ON r.id  = f.region_id
  LEFT JOIN cat_zona_pesca z      ON z.id  = f.zona_pesca_id
  LEFT JOIN cat_comunidad co      ON co.id = f.comunidad_id
  LEFT JOIN cat_formato_origen fo ON fo.id = f.formato_origen_id
"""

DATASETS = {
    "mediciones": {
        "label": "Mediciones de tallas",
        "desc": "Cada fila es un pez medido: talla, peso, sexo y madurez.",
        "select": """
            m.id, e.nombre_comun AS especie,
            m.longitud_total_cm, m.longitud_furcal_cm, m.peso_gr, m.peso_gonada_gr,
            m.procesado, m.sexo, m.madurez_nikolsky,
            m.faena_id, f.fecha, f.tipo_registro,
            r.nombre AS region, z.nombre AS zona, co.nombre AS comunidad, fo.codigo AS formato
        """,
        "from": "FROM medicion m LEFT JOIN cat_especie e ON e.id = m.especie_id"
                + _FAENA_CTX.format(base="m"),
        "filters": {"especie": "m.especie_id", "region": "f.region_id", "tipo": "f.tipo_registro",
                    "formato": "f.formato_origen_id", "sexo": "m.sexo", "procesado": "m.procesado",
                    "year": "f.fecha"},
        "orphans": True, "lengths": True,
    },
    "capturas": {
        "label": "Capturas",
        "desc": "Cada fila es la captura de una especie en un viaje: kilos, organismos y precio.",
        "select": """
            c.id, e.nombre_comun AS especie, c.captura_kg, c.num_organismos, c.precio_kg,
            c.tipo_captura, c.presentacion, c.categoria_tamano,
            c.faena_id, f.fecha, f.tipo_registro, f.tiempo_efectivo_pesca_h,
            r.nombre AS region, z.nombre AS zona, co.nombre AS comunidad, fo.codigo AS formato
        """,
        "from": "FROM captura c LEFT JOIN cat_especie e ON e.id = c.especie_id"
                + _FAENA_CTX.format(base="c"),
        "filters": {"especie": "c.especie_id", "region": "f.region_id", "tipo": "f.tipo_registro",
                    "formato": "f.formato_origen_id", "year": "f.fecha"},
        "orphans": False, "lengths": False,
    },
    "faenas": {
        "label": "Faenas (viajes)",
        "desc": "Cada fila es un viaje de pesca: esfuerzo, pescadores, gasolina, capitán y técnico.",
        "select": """
            f.id, f.fecha, f.tipo_registro, f.num_pescadores, f.tiempo_efectivo_pesca_h,
            f.gasolina_lts, f.profundidad_min_brazas, f.profundidad_max_brazas,
            r.nombre AS region, z.nombre AS zona, co.nombre AS comunidad,
            s.nombre AS sitio, fo.codigo AS formato, cap.nombre AS capitan, tec.nombre AS tecnico
        """,
        "from": """FROM faena f
            LEFT JOIN cat_region r          ON r.id  = f.region_id
            LEFT JOIN cat_zona_pesca z      ON z.id  = f.zona_pesca_id
            LEFT JOIN cat_comunidad co      ON co.id = f.comunidad_id
            LEFT JOIN cat_sitio_pesca s     ON s.id  = f.sitio_pesca_id
            LEFT JOIN cat_formato_origen fo ON fo.id = f.formato_origen_id
            LEFT JOIN cat_pescador cap      ON cap.id = f.capitan_id
            LEFT JOIN cat_tecnico tec       ON tec.id = f.tecnico_id""",
        "filters": {"region": "f.region_id", "tipo": "f.tipo_registro",
                    "formato": "f.formato_origen_id", "year": "f.fecha"},
        "orphans": False, "lengths": False,
    },
    "etp": {
        "label": "Interacciones ETP",
        "desc": "Cada fila es un encuentro con especies protegidas (tortugas, mamíferos, aves…).",
        "select": """
            i.id, e.nombre_comun AS especie, ti.nombre AS interaccion, i.cantidad,
            i.faena_id, f.fecha, f.tipo_registro,
            r.nombre AS region, z.nombre AS zona, fo.codigo AS formato
        """,
        "from": """FROM interaccion_etp i
            LEFT JOIN cat_especie e ON e.id = i.especie_id
            LEFT JOIN cat_tipo_interaccion_etp ti ON ti.id = i.tipo_interaccion_id"""
                + _FAENA_CTX.format(base="i"),
        "filters": {"especie": "i.especie_id", "region": "f.region_id", "tipo": "f.tipo_registro",
                    "formato": "f.formato_origen_id", "year": "f.fecha"},
        "orphans": False, "lengths": False,
    },
}


# ---------------------------------------------------------------------
# Option lists (cached)
# ---------------------------------------------------------------------
@st.cache_data(ttl=300, show_spinner=False)
def _opts():
    esp = _q("SELECT id::text, nombre_comun FROM cat_especie ORDER BY nombre_comun")
    reg = _q("SELECT id::text, nombre FROM cat_region ORDER BY nombre")
    fmt = _q("SELECT id::text, codigo FROM cat_formato_origen ORDER BY codigo")
    sexos = [r["sexo"] for r in _q("SELECT DISTINCT sexo FROM medicion WHERE sexo IS NOT NULL ORDER BY sexo")]
    proc = [r["procesado"] for r in _q("SELECT DISTINCT procesado FROM medicion WHERE procesado IS NOT NULL ORDER BY procesado")]
    return esp, reg, fmt, sexos, proc


# Plain-Spanish meaning of every exported column (diccionario de columnas).
COL_DIC = {
    "id": "Identificador único de la fila",
    "especie": "Nombre común de la especie",
    "longitud_total_cm": "Longitud total en centímetros",
    "longitud_furcal_cm": "Longitud furcal en centímetros",
    "peso_gr": "Peso en gramos",
    "peso_gonada_gr": "Peso de la gónada en gramos",
    "procesado": "Estado del pez al medirlo (entero, eviscerado…)",
    "sexo": "Sexo del organismo",
    "madurez_nikolsky": "Etapa de madurez (escala de Nikolsky)",
    "faena_id": "Viaje al que pertenece (vacío = medición huérfana)",
    "fecha": "Fecha de la faena",
    "tipo_registro": "MASIVO o BITACORA — nunca se suman entre sí",
    "region": "Región",
    "zona": "Zona de pesca",
    "comunidad": "Comunidad",
    "formato": "Formato de origen del dato (comunidad/proyecto)",
    "captura_kg": "Kilogramos capturados",
    "num_organismos": "Número de organismos",
    "precio_kg": "Precio por kilogramo (MXN)",
    "tipo_captura": "Tipo de captura",
    "presentacion": "Presentación del producto",
    "categoria_tamano": "Categoría de tamaño",
    "tiempo_efectivo_pesca_h": "Horas efectivas de pesca",
    "num_pescadores": "Número de pescadores en el viaje",
    "gasolina_lts": "Litros de gasolina",
    "profundidad_min_brazas": "Profundidad mínima (brazas)",
    "profundidad_max_brazas": "Profundidad máxima (brazas)",
    "sitio": "Sitio de pesca",
    "capitan": "Capitán de la embarcación",
    "tecnico": "Técnico que registró",
    "interaccion": "Tipo de interacción con la especie protegida",
    "cantidad": "Cantidad de organismos",
}


@st.cache_data(ttl=300, show_spinner=False)
def _has_suspect_flag() -> bool:
    return bool(_q("""SELECT 1 FROM information_schema.columns
                      WHERE table_name='medicion' AND column_name='longitud_sospechosa'"""))


def recompute_suspect_flags() -> int:
    """Re-run the per-species suspicious-length flag (migration 0009). Returns total flagged."""
    cur = get_conn().cursor()
    cur.execute("SELECT flag_longitudes_sospechosas()")
    n = cur.fetchone()[0]
    cur.close()
    return n


# Base-table alias per dataset (for the "all fields" raw dump).
_BASE_ALIAS = {"mediciones": "m", "capturas": "c", "faenas": "f", "etp": "i"}


def _build(dataset: str, f: dict, all_fields: bool = False) -> tuple[str, list]:
    cfg = DATASETS[dataset]
    where, params = [], []
    cols = cfg["filters"]
    # psycopg2 sends Python lists as text[]: cast explicitly, or Postgres
    # refuses to compare uuid/enum columns against them.
    if f.get("especie") and "especie" in cols:
        where.append(f"{cols['especie']} = ANY(%s::uuid[])"); params.append(f["especie"])
    if f.get("region") and "region" in cols:
        where.append(f"{cols['region']} = ANY(%s::uuid[])"); params.append(f["region"])
    if f.get("formato") and "formato" in cols:
        where.append(f"{cols['formato']} = ANY(%s::uuid[])"); params.append(f["formato"])
    if f.get("tipo") and f["tipo"] != "Todos" and "tipo" in cols:
        where.append(f"{cols['tipo']} = %s"); params.append(f["tipo"])
    if f.get("sexo") and "sexo" in cols:
        where.append(f"{cols['sexo']}::text = ANY(%s)"); params.append(f["sexo"])
    if f.get("procesado") and "procesado" in cols:
        where.append(f"{cols['procesado']}::text = ANY(%s)"); params.append(f["procesado"])
    if f.get("years") and "year" in cols:
        where.append(f"EXTRACT(YEAR FROM {cols['year']}) BETWEEN %s AND %s")
        params += [f["years"][0], f["years"][1]]
    if cfg["orphans"] and not f.get("incluir_huerfanas", True):
        where.append("m.faena_id IS NOT NULL")   # orphans only exist for mediciones (alias m)
    if cfg["lengths"] and f.get("excluir_sospechosas") and _has_suspect_flag():
        where.append("(m.longitud_sospechosa IS NOT TRUE)")
    select = f"{_BASE_ALIAS[dataset]}.*" if all_fields else cfg["select"]
    sql = f"SELECT {select} {cfg['from']}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sort_dir = {"Más recientes primero": "DESC", "Más antiguas primero": "ASC"}.get(f.get("sort"))
    if sort_dir and "year" in cols:
        # orphan mediciones have no faena date → keep NULLs out of the way
        sql += f" ORDER BY {cols['year']} {sort_dir} NULLS LAST"
    return sql, params


# =====================================================================
# UI
# =====================================================================
def render_export():
    from console_ui import page_header
    page_header(
        "📤 Descargar datos",
        "Extrae los datos filtrados a un archivo CSV o Parquet para abrirlo en Excel o R.",
        help_md=(
            "1. Elige el **conjunto de datos** (mediciones, capturas, faenas o ETP).\n"
            "2. Ajusta los **filtros** (especie, región, años…).\n"
            "3. Pulsa **🔍 Generar vista previa** y revisa el resumen.\n"
            "4. Descarga con **⬇️ CSV** (Excel/R) o **⬇️ Parquet** (R/Python).\n\n"
            "¿Necesitas combinar tablas (p. ej. faenas con sus capturas)? Usa el "
            "**Constructor**."
        ),
    )

    _consultas_guardadas_ui()

    # Analistas are scoped to their assigned region and get only the curated datasets (R-C).
    is_analista = st.session_state.get("auth_rol") == "ANALISTA"
    region_lock = st.session_state.get("auth_region") if is_analista else None
    region_lock_nombre = st.session_state.get("auth_region_nombre")
    if is_analista and not region_lock:
        st.warning("Tu cuenta de analista no tiene una región asignada. Pídele a un administrador "
                   "que te asigne una para poder descargar datos.")
        return

    if is_analista:
        modo = "Conjuntos rápidos"                 # analistas: sin Constructor
    else:
        modo = st.radio("Modo", ["Conjuntos rápidos", "🔧 Constructor (combinar tablas)"],
                        horizontal=True, key="exp_modo", label_visibility="collapsed")
        if modo.startswith("🔧"):
            from export_builder import render_builder
            render_builder(render_results)
            return

    try:
        esp, reg, fmt, sexos, proc = _opts()
    except Exception as e:  # noqa: BLE001
        st.error(f"No se pudo conectar a la base de datos: {e}")
        st.info("Configura DATABASE_URL (env o .env). Ver Planning/supabase/TODO.md.")
        return

    ds = st.selectbox("Conjunto de datos", list(DATASETS),
                      format_func=lambda d: DATASETS[d]["label"], key="exp_ds")
    cfg = DATASETS[ds]
    st.caption(cfg["desc"])
    cols = cfg["filters"]
    f: dict = {}

    c1, c2 = st.columns(2)
    if "especie" in cols:
        emap = {e["id"]: e["nombre_comun"] for e in esp}
        f["especie"] = c1.multiselect("Especie", list(emap), format_func=lambda i: emap[i], key="exp_esp")
    if "region" in cols:
        if region_lock:
            f["region"] = [region_lock]
            c2.caption(f"Región: **{region_lock_nombre or '—'}** (fijada para tu cuenta)")
        else:
            rmap = {r["id"]: r["nombre"] for r in reg}
            f["region"] = c2.multiselect("Región", list(rmap), format_func=lambda i: rmap[i], key="exp_reg")
    if "formato" in cols:
        fmap = {x["id"]: x["codigo"] for x in fmt}
        f["formato"] = c1.multiselect("Formato origen", list(fmap), format_func=lambda i: fmap[i], key="exp_fmt")
    if "tipo" in cols:
        f["tipo"] = c2.radio("Tipo de registro", ["Todos", "MASIVO", "BITACORA"], horizontal=True, key="exp_tipo")
        c2.warning("MASIVO y BITÁCORA **no se suman**: son dos formas distintas de registrar. "
                   "La columna `tipo_registro` va incluida para separarlos en el análisis.")
    if "sexo" in cols and sexos:
        f["sexo"] = c1.multiselect("Sexo", sexos, key="exp_sexo")
    if "procesado" in cols and proc:
        f["procesado"] = c2.multiselect("Procesado", proc, key="exp_proc")
    if "year" in cols:
        f["years"] = st.slider("Años (por fecha de faena)", 2005, _dt.date.today().year,
                               (2005, _dt.date.today().year), key="exp_years")
        f["sort"] = st.radio(
            "Ordenar por fecha de faena",
            ["Más recientes primero", "Más antiguas primero", "Sin ordenar"],
            horizontal=True, key="exp_sort",
            help="Ordena las filas descargadas (vista previa y archivo) por la fecha de la faena.")

    if cfg["orphans"]:
        st.info("Las mediciones **huérfanas** son tallas biológicamente válidas pero sin viaje "
                "asociado (~36% del histórico). Sirven para análisis por especie; cualquier "
                "filtro de contexto (región, tipo, año) las excluye automáticamente.")
        f["incluir_huerfanas"] = st.checkbox(
            "Incluir mediciones huérfanas (sin faena)", value=True, key="exp_orph")
    if cfg["lengths"]:
        has_flag = _has_suspect_flag()
        if has_flag:
            st.info("Las tallas **sospechosas** son valores atípicos para su especie (p. ej. "
                    "milímetros capturados como centímetros en el histórico). Se excluyen por "
                    "defecto; inclúyelas solo si sabes lo que haces.")
        f["excluir_sospechosas"] = st.checkbox(
            "Excluir tallas sospechosas (outliers por especie)", value=True,
            key="exp_susp", disabled=not has_flag,
            help="Se activa cuando exista la columna longitud_sospechosa (migración 0009)."
                 if not has_flag else "Excluye filas marcadas como talla atípica.")
        if has_flag:
            with st.expander("🔧 Calidad de tallas (longitud sospechosa)"):
                cur_flag = _q("SELECT count(*) AS n FROM medicion WHERE longitud_sospechosa")[0]["n"]
                st.caption(f"Marcadas como sospechosas: **{cur_flag:,}**. Recalcula tras importar "
                           "datos o ajustar `cat_especie.longitud_maxima_cm` por especie (Lmax).")
                if st.button("♻️ Recalcular tallas sospechosas", key="exp_recompute"):
                    st.success(f"Recalculado: {recompute_suspect_flags():,} mediciones marcadas.")

    all_fields = st.checkbox(
        "Descargar todos los campos (columnas crudas de la tabla base)", value=False,
        key="exp_allf",
        help="Incluye todas las columnas de la tabla principal (con sus ids), en vez de solo la "
             "selección curada con nombres. Útil para análisis avanzado.")

    # record the current query spec (used by 'Consultas guardadas')
    st.session_state["exp_current"] = {"mode": "preset", "dataset": ds, "filters": f,
                                       "all_fields": all_fields}

    if st.button("🔍 Generar vista previa", key="exp_run", type="primary"):
        sql, params = _build(ds, f, all_fields)
        try:
            # straight from the DBAPI cursor: pd.read_sql wants SQLAlchemy and
            # warns on raw psycopg2 connections
            cur = get_conn().cursor()
            cur.execute(sql, params or None)
            df = pd.DataFrame(cur.fetchall(), columns=[c[0] for c in cur.description])
            cur.close()
            st.session_state["exp_df"] = df
            st.session_state["exp_meta"] = {"ds": ds, "when": _dt.datetime.now()}
            st.session_state.pop("exp_dl", None)   # invalidate any prepared download
        except Exception as e:  # noqa: BLE001
            st.session_state.pop("exp_df", None)
            st.error(f"Error en la consulta: {e}")

    df = st.session_state.get("exp_df")
    if df is None or st.session_state.get("exp_meta", {}).get("ds") != ds:
        st.info("Ajusta los filtros y genera la vista previa.")
        return
    render_results(df, f"{ds}_{_dt.date.today().isoformat()}", cfg)


def _apply_config(config: dict):
    """Preload the export widgets from a saved query config (set session_state keys, then the
    caller reruns so the widgets read them)."""
    ss = st.session_state
    if config.get("mode") == "builder":
        ss["exp_modo"] = "🔧 Constructor (combinar tablas)"
        base = config.get("base")
        ss["jb_base"] = base
        ss["jb_showids"] = bool(config.get("show_ids", False))
        ss["jb_limit"] = int(config.get("limit", 5000))
        if config.get("sort_col"):
            ss[f"jb_sort_{base}"] = config["sort_col"]
            ss[f"jb_sortdir_{base}"] = config.get("sort_dir") or "Más recientes primero"
        for fk_col, ids in (config.get("filtros") or {}).items():
            ss[f"jb_f_{base}_{fk_col}"] = ids
        for ch in config.get("children", []):
            t = ch["table"]
            ss[f"jb_c_{base}_{t}"] = True
            ss[f"jb_m_{base}_{t}"] = ch.get("mode", "resumen")
            if ch.get("mode") == "resumen":
                ss[f"jb_s_{base}_{t}"] = ch.get("sum_col")
            else:
                ss[f"jb_dc_{base}_{t}"] = ch.get("columns", [])
    else:
        ss["exp_modo"] = "Conjuntos rápidos"
        ss["exp_ds"] = config.get("dataset")
        ss["exp_allf"] = bool(config.get("all_fields", False))
        f = config.get("filters", {}) or {}
        for k, wk in {"especie": "exp_esp", "region": "exp_reg", "formato": "exp_fmt",
                      "tipo": "exp_tipo", "sexo": "exp_sexo", "procesado": "exp_proc",
                      "sort": "exp_sort",
                      "incluir_huerfanas": "exp_orph", "excluir_sospechosas": "exp_susp"}.items():
            if k in f:
                ss[wk] = f[k]
        if f.get("years"):
            ss["exp_years"] = tuple(f["years"])
    ss["exp_colcfg_load"] = config.get("colconfig") or {}
    ss.pop("exp_col_sig", None)   # force the column editor to re-init from the loaded config


def _consultas_guardadas_ui():
    from console_ui import flash, friendly_error
    import export_saved as es
    uid = st.session_state.get("auth_uid")
    with st.expander("💾 Consultas guardadas"):
        if not uid:
            st.caption("Inicia sesión para guardar y reutilizar consultas.")
            return
        try:
            saved = es.list_consultas(uid)
        except Exception as e:  # noqa: BLE001
            st.error(f"No se pudieron cargar las consultas: {e}")
            return
        if saved:
            ids = [s["id"] for s in saved]
            lab = {s["id"]: (s["nombre"] + ("" if s["propia"] else f"  · de {s['autor']}")
                             + (" 🔗" if s["compartida"] else "")) for s in saved}
            lc = st.columns([5, 2, 2], vertical_alignment="bottom")
            sel = lc[0].selectbox("Cargar una consulta", ids, format_func=lambda i: lab[i], key="cq_sel")
            if lc[1].button("📂 Cargar", key="cq_load", width="stretch"):
                cfg = es.load_consulta(sel)
                if cfg:
                    _apply_config(cfg)
                    flash("Consulta cargada.")
                    st.rerun()
            cur = next((s for s in saved if s["id"] == sel), None)
            if cur and cur["propia"] and lc[2].button("🗑️ Eliminar", key="cq_del", width="stretch"):
                es.delete_consulta(sel, uid)
                flash("Consulta eliminada.", "🗑️")
                st.rerun()
        else:
            st.caption("Aún no tienes consultas guardadas. Configura una descarga y guárdala abajo.")

        st.divider()
        current = st.session_state.get("exp_current")
        sc = st.columns([5, 3, 2], vertical_alignment="bottom")
        nombre = sc[0].text_input("Guardar la configuración actual como", key="cq_name",
                                  placeholder="p. ej. Capturas por faena")
        compartir = sc[1].checkbox("Compartir con administradores", key="cq_share")
        if sc[2].button("💾 Guardar", key="cq_save", width="stretch",
                        disabled=not (nombre.strip() and current)):
            try:
                config = dict(current)
                config["colconfig"] = st.session_state.get("exp_colcfg") or {}
                es.save_consulta(uid, nombre, config, compartir)
                flash(f"Consulta «{nombre}» guardada.")
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(friendly_error(e))
        if not current:
            sc[0].caption("Genera una vista previa para poder guardarla.")


def _column_editor(df):
    """Let the user pick which columns to download and rename their headers. Returns the
    export DataFrame (trimmed + renamed). Config persists in session (exp_colcfg) so
    'Consultas guardadas' can save/restore it; a saved-query load sets exp_colcfg_load."""
    sig = str(list(df.columns))
    if st.session_state.get("exp_col_sig") != sig:
        load = st.session_state.pop("exp_colcfg_load", None) or {}
        st.session_state["exp_colcfg"] = {
            c: {"incluir": bool(load.get(c, {}).get("incluir", True)),
                "nombre": str(load.get(c, {}).get("nombre", c))} for c in df.columns}
        st.session_state["exp_col_sig"] = sig
        st.session_state["exp_col_nonce"] = st.session_state.get("exp_col_nonce", 0) + 1

    cfg = st.session_state["exp_colcfg"]
    with st.expander("🎚️ Elegir y renombrar columnas"):
        st.caption("Desmarca las columnas que no quieras y edita el nombre con el que se "
                   "descargarán.")
        edf = pd.DataFrame([{"incluir": cfg[c]["incluir"], "columna": c, "nombre": cfg[c]["nombre"]}
                            for c in df.columns])
        edited = st.data_editor(
            edf, key=f"exp_coled_{st.session_state['exp_col_nonce']}", hide_index=True,
            width="stretch", disabled=["columna"],
            column_config={"incluir": st.column_config.CheckboxColumn("Incluir"),
                           "columna": "Columna", "nombre": "Nombre para descargar"})
    st.session_state["exp_colcfg"] = {
        r["columna"]: {"incluir": bool(r["incluir"]), "nombre": str(r["nombre"] or r["columna"])}
        for _, r in edited.iterrows()}

    inc = [(r["columna"], str(r["nombre"] or r["columna"]))
           for _, r in edited.iterrows() if r["incluir"]]
    if not inc:   # everything deselected → fall back to the full frame
        return df
    out = df[[c for c, _ in inc]].copy()
    out.columns = [n for _, n in inc]
    return out


def render_results(df, base_name: str, cfg: dict | None = None):
    """Shared results view (summary metrics + preview + dictionary + downloads).
    Used by the quick-datasets flow and the join builder (cfg=None for the builder)."""
    st.divider()
    st.subheader("Resumen")
    m = st.columns(4)
    m[0].metric("Filas", f"{len(df):,}")
    m[1].metric("Columnas", df.shape[1])
    if cfg and cfg.get("orphans") and "faena_id" in df:
        n_orf = int(df["faena_id"].isna().sum())
        m[2].metric("Huérfanas incluidas", f"{n_orf:,}")
    if "tipo_registro" in df:
        vc = df["tipo_registro"].value_counts(dropna=False)
        m[3].metric("MASIVO / BITÁCORA", f"{int(vc.get('MASIVO',0)):,} / {int(vc.get('BITACORA',0)):,}")

    if cfg and cfg.get("lengths") and "longitud_total_cm" in df and len(df):
        s = pd.to_numeric(df["longitud_total_cm"], errors="coerce").dropna()
        if len(s):
            st.markdown(f"**Longitud total (cm)** — n={len(s):,} · "
                        f"media {s.mean():.1f} · mediana {s.median():.1f} · "
                        f"min {s.min():.1f} · max {s.max():.1f}")
            if s.max() > 200:
                st.warning("Hay tallas > 200 cm: probable contaminación mm→cm en el histórico "
                           "(ver 06-length-audit). Considera el flag por especie (item D).")
    if "especie" in df and len(df):
        top = df["especie"].value_counts().head(8)
        st.caption("Top especies: " + " · ".join(f"{k} ({v:,})" for k, v in top.items()))

    st.dataframe(df.head(100), width="stretch", height=300)
    st.caption(f"Mostrando {min(100, len(df))} de {len(df):,} filas.")

    with st.expander("📖 Diccionario de columnas"):
        st.dataframe(pd.DataFrame(
            [{"columna": c, "significado": COL_DIC.get(c, "—")} for c in df.columns]),
            width="stretch", hide_index=True)

    # ---- choose + rename columns (both modes) ----
    export_df = _column_editor(df)

    # ---- download ----
    # Serialize on demand: encoding a large frame to CSV/Parquet on every rerun made
    # toggling columns lag. Prepare once (cleared when a new preview is generated), then
    # the buttons hand over the ready bytes. Re-preparing is only needed after a change.
    st.divider()
    st.caption(f"Descargarás **{export_df.shape[1]} de {df.shape[1]}** columnas.")
    sig = (base_name, tuple(export_df.columns), int(len(export_df)))
    prep = st.session_state.get("exp_dl")
    if not prep or prep.get("sig") != sig:
        if st.button("📦 Preparar archivo para descargar", key="exp_prep", type="primary"):
            with st.spinner("Preparando el archivo…"):
                pq = None
                if HAS_PARQUET:
                    buf = io.BytesIO(); export_df.to_parquet(buf, index=False); pq = buf.getvalue()
                st.session_state["exp_dl"] = {
                    "sig": sig, "name": base_name,
                    "csv": export_df.to_csv(index=False).encode("utf-8"), "parquet": pq}
            st.rerun()
        st.caption("Ajusta las columnas y pulsa **Preparar** para generar el archivo (así el "
                   "editor de columnas no se traba con tablas grandes).")
    else:
        d1, d2 = st.columns(2)
        d1.download_button("⬇️ CSV (Excel / R)", prep["csv"], file_name=f"{prep['name']}.csv",
                           mime="text/csv", width="stretch")
        if HAS_PARQUET and prep.get("parquet") is not None:
            d2.download_button("⬇️ Parquet (R / Python)", prep["parquet"],
                               file_name=f"{prep['name']}.parquet",
                               mime="application/octet-stream", width="stretch")
        else:
            d2.button("⬇️ Parquet", disabled=True, width="stretch")
            d2.caption("Parquet no disponible: falta el paquete `pyarrow` en el servidor "
                       "(`pip install pyarrow`). El CSV funciona igual.")

    with st.expander("💻 Cómo cargar el archivo en R o Python"):
        st.code(f'datos <- read.csv("{base_name}.csv", fileEncoding = "UTF-8")\n'
                f'# o con Parquet:  datos <- arrow::read_parquet("{base_name}.parquet")',
                language="r")
        st.code(f'import pandas as pd\n'
                f'datos = pd.read_csv("{base_name}.csv")\n'
                f'# o con Parquet:  datos = pd.read_parquet("{base_name}.parquet")',
                language="python")
