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
        "label": "Mediciones (tallas)",
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
        "label": "Capturas (composición / CPUE)",
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
        "label": "Faenas (esfuerzo)",
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
        "label": "Interacciones ETP (bycatch)",
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


@st.cache_data(ttl=300, show_spinner=False)
def _has_suspect_flag() -> bool:
    return bool(_q("""SELECT 1 FROM information_schema.columns
                      WHERE table_name='medicion' AND column_name='longitud_sospechosa'"""))


def _build(dataset: str, f: dict) -> tuple[str, list]:
    cfg = DATASETS[dataset]
    where, params = [], []
    cols = cfg["filters"]
    if f.get("especie") and "especie" in cols:
        where.append(f"{cols['especie']} = ANY(%s)"); params.append(f["especie"])
    if f.get("region") and "region" in cols:
        where.append(f"{cols['region']} = ANY(%s)"); params.append(f["region"])
    if f.get("formato") and "formato" in cols:
        where.append(f"{cols['formato']} = ANY(%s)"); params.append(f["formato"])
    if f.get("tipo") and f["tipo"] != "Todos" and "tipo" in cols:
        where.append(f"{cols['tipo']} = %s"); params.append(f["tipo"])
    if f.get("sexo") and "sexo" in cols:
        where.append(f"{cols['sexo']} = ANY(%s)"); params.append(f["sexo"])
    if f.get("procesado") and "procesado" in cols:
        where.append(f"{cols['procesado']} = ANY(%s)"); params.append(f["procesado"])
    if f.get("years") and "year" in cols:
        where.append(f"EXTRACT(YEAR FROM {cols['year']}) BETWEEN %s AND %s")
        params += [f["years"][0], f["years"][1]]
    if cfg["orphans"] and not f.get("incluir_huerfanas", True):
        where.append("m.faena_id IS NOT NULL")   # orphans only exist for mediciones (alias m)
    if cfg["lengths"] and f.get("excluir_sospechosas") and _has_suspect_flag():
        where.append("(m.longitud_sospechosa IS NOT TRUE)")
    sql = f"SELECT {cfg['select']} {cfg['from']}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    return sql, params


# =====================================================================
# UI
# =====================================================================
def render_export():
    st.title("📤 Exportar datos para R")
    st.caption("Descarga filtrada (CSV / Parquet) con un resumen previo. Análisis en R; "
               "esto solo entrega los datos. Ver AppDashboardSpec/02, OD-19.")

    try:
        esp, reg, fmt, sexos, proc = _opts()
    except Exception as e:  # noqa: BLE001
        st.error(f"No se pudo conectar a la base de datos: {e}")
        st.info("Configura DATABASE_URL (env o .env). Ver Planning/supabase/TODO.md.")
        return

    ds = st.selectbox("Conjunto de datos", list(DATASETS),
                      format_func=lambda d: DATASETS[d]["label"], key="exp_ds")
    cfg = DATASETS[ds]
    cols = cfg["filters"]
    f: dict = {}

    c1, c2 = st.columns(2)
    if "especie" in cols:
        emap = {e["id"]: e["nombre_comun"] for e in esp}
        f["especie"] = c1.multiselect("Especie", list(emap), format_func=lambda i: emap[i], key="exp_esp")
    if "region" in cols:
        rmap = {r["id"]: r["nombre"] for r in reg}
        f["region"] = c2.multiselect("Región", list(rmap), format_func=lambda i: rmap[i], key="exp_reg")
    if "formato" in cols:
        fmap = {x["id"]: x["codigo"] for x in fmt}
        f["formato"] = c1.multiselect("Formato origen", list(fmap), format_func=lambda i: fmap[i], key="exp_fmt")
    if "tipo" in cols:
        f["tipo"] = c2.radio("Tipo de registro", ["Todos", "MASIVO", "BITACORA"], horizontal=True, key="exp_tipo")
        c2.caption("⚠️ MASIVO y BITÁCORA **no se suman**. La columna se incluye para separarlos en R.")
    if "sexo" in cols and sexos:
        f["sexo"] = c1.multiselect("Sexo", sexos, key="exp_sexo")
    if "procesado" in cols and proc:
        f["procesado"] = c2.multiselect("Procesado", proc, key="exp_proc")
    if "year" in cols:
        f["years"] = st.slider("Años (por fecha de faena)", 2005, _dt.date.today().year,
                               (2005, _dt.date.today().year), key="exp_years")

    if cfg["orphans"]:
        f["incluir_huerfanas"] = st.checkbox(
            "Incluir mediciones huérfanas (sin faena)", value=True, key="exp_orph",
            help="Tallas válidas sin contexto de viaje (~36% del histórico). "
                 "Cualquier filtro de contexto (región/tipo/año) las excluye automáticamente.")
    if cfg["lengths"]:
        has_flag = _has_suspect_flag()
        f["excluir_sospechosas"] = st.checkbox(
            "Excluir tallas sospechosas (outliers por especie)", value=True,
            key="exp_susp", disabled=not has_flag,
            help="Activo cuando exista la columna longitud_sospechosa (pendiente, item D)."
                 if not has_flag else "Excluye filas marcadas como talla atípica.")

    if st.button("🔍 Generar vista previa", key="exp_run", type="primary"):
        sql, params = _build(ds, f)
        try:
            df = pd.read_sql(sql, get_conn(), params=params or None)
            st.session_state["exp_df"] = df
            st.session_state["exp_meta"] = {"ds": ds, "when": _dt.datetime.now()}
        except Exception as e:  # noqa: BLE001
            st.session_state.pop("exp_df", None)
            st.error(f"Error en la consulta: {e}")

    df = st.session_state.get("exp_df")
    if df is None or st.session_state.get("exp_meta", {}).get("ds") != ds:
        st.info("Ajusta los filtros y genera la vista previa.")
        return

    # ---- heads-up ----
    st.divider()
    st.subheader("Resumen")
    m = st.columns(4)
    m[0].metric("Filas", f"{len(df):,}")
    m[1].metric("Columnas", df.shape[1])
    if cfg["orphans"] and "faena_id" in df:
        n_orf = int(df["faena_id"].isna().sum())
        m[2].metric("Huérfanas incluidas", f"{n_orf:,}")
    if "tipo_registro" in df:
        vc = df["tipo_registro"].value_counts(dropna=False)
        m[3].metric("MASIVO / BITÁCORA", f"{int(vc.get('MASIVO',0)):,} / {int(vc.get('BITACORA',0)):,}")

    if cfg["lengths"] and "longitud_total_cm" in df and len(df):
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

    st.dataframe(df.head(100), use_container_width=True, height=300)
    st.caption(f"Mostrando 100 de {len(df):,} filas.")

    # ---- download ----
    st.divider()
    stamp = _dt.date.today().isoformat()
    base = f"{ds}_{stamp}"
    d1, d2 = st.columns(2)
    d1.download_button("⬇️ CSV", df.to_csv(index=False).encode("utf-8"),
                       file_name=f"{base}.csv", mime="text/csv", use_container_width=True)
    if HAS_PARQUET:
        buf = io.BytesIO(); df.to_parquet(buf, index=False)
        d2.download_button("⬇️ Parquet", buf.getvalue(),
                           file_name=f"{base}.parquet", mime="application/octet-stream",
                           use_container_width=True)
    else:
        d2.button("⬇️ Parquet (instala pyarrow)", disabled=True, use_container_width=True)
