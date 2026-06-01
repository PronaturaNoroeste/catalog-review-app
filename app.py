"""
Catalog Review App — Streamlit
Revisión de catálogos de monitoreo pesquero con biólogos.

Run:  streamlit run app.py
Docker: docker compose up
"""

import json
from pathlib import Path

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR      = Path(__file__).parent
EXPORT_DIR    = BASE_DIR / "catalogos_export"
DECISIONS_DIR = BASE_DIR / "decisions"
DECISIONS_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

NAME_COLS = {
    "cat_zona_pesca":     "zona",
    "cat_area_pesca":     "area",
    "cat_sitio_pesca":    "sitio",
    "cat_comunidad":      "comunidad",
    "cat_especie":        "nombre_comun",
    "cat_tecnico":        "tecnico",
    "cat_pescador":       "pescador_capitan",
    "cat_embarcacion":    "embarcacion",
    "cat_cooperativa":    "cooperativa",
    "cat_tipo_arte":      "tipo_arte",
    "cat_tipo_anzuelo":   "tipo_anzuelo",
    "cat_tipo_operacion": "tipo_operacion",
    "cat_tipo_fondo":     "tipo_fondo",
    "cat_tipo_viento":    "tipo_viento",
    "cat_tipo_luna":      "tipo_luna",
    "cat_tipo_marea":     "tipo_marea",
}

TABLE_LABELS = {
    "cat_zona_pesca":     "Zonas de pesca",
    "cat_area_pesca":     "Áreas de pesca",
    "cat_sitio_pesca":    "Sitios de pesca",
    "cat_comunidad":      "Comunidades",
    "cat_especie":        "Especies",
    "cat_tecnico":        "Técnicos",
    "cat_pescador":       "Pescadores / Capitanes",
    "cat_embarcacion":    "Embarcaciones",
    "cat_cooperativa":    "Cooperativas",
    "cat_tipo_arte":      "Tipos de arte",
    "cat_tipo_anzuelo":   "Tipos de anzuelo",
    "cat_tipo_operacion": "Tipos de operación",
    "cat_tipo_fondo":     "Tipos de fondo",
    "cat_tipo_viento":    "Tipos de viento",
    "cat_tipo_luna":      "Fases de luna",
    "cat_tipo_marea":     "Tipos de marea",
}

FLAG_EMOJI = {
    "DUPLICADO_EXACTO":   "🔴",
    "DUPLICADO_PROBABLE": "🟠",
    "POSIBLE_DUPLICADO":  "🟡",
}

DECISIONS = [
    "Decidir después",
    "Mantener A — eliminar B",
    "Mantener B — eliminar A",
    "Ambos son válidos",
]

# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

@st.cache_data
def load_csv(table: str) -> pd.DataFrame | None:
    path = EXPORT_DIR / f"{table}.csv"
    if not path.exists():
        return None
    return pd.read_csv(path, encoding="utf-8-sig", dtype=str).fillna("")


def save_csv(table: str, df: pd.DataFrame):
    path = EXPORT_DIR / f"{table}.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig")


def load_decisions(table: str) -> dict:
    path = DECISIONS_DIR / f"{table}.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"pairs": {}, "deleted": [], "approved": [], "renames": []}


def save_decisions(table: str, decisions: dict):
    path = DECISIONS_DIR / f"{table}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(decisions, f, ensure_ascii=False, indent=2)


@st.cache_data
def get_pairs(df: pd.DataFrame, name_col: str) -> list[dict]:
    """Return unique flagged pairs (A↔B shown once). Cached — cleared on CSV rename."""
    if "flag_tipo" not in df.columns:
        return []

    uso_cols  = [c for c in df.columns if c.startswith("uso_")]
    has_sci   = "nombre_cientifico" in df.columns
    extra_cols = ["nombre_cientifico"] if has_sci else []

    # Pre-build O(1) lookup: name → {col: val}
    lookup_cols = uso_cols + extra_cols
    lookup = (
        df.set_index(name_col)[lookup_cols].to_dict("index")
        if lookup_cols else {}
    )

    flagged = df[(df["flag_tipo"] != "") & (df["similar_a"] != "")]
    seen: set = set()
    pairs = []

    for _, row in flagged.iterrows():
        a, b = row[name_col], row["similar_a"]
        key = "|".join(sorted([a, b]))
        if key in seen:
            continue
        seen.add(key)

        row_a = lookup.get(a, {})
        row_b = lookup.get(b, {})

        pairs.append({
            "key":     key,
            "a":       a,
            "b":       b,
            "flag":    row["flag_tipo"],
            "pct":     row.get("similitud_pct", ""),
            "uso_a":   {c: row_a.get(c, "") for c in uso_cols},
            "uso_b":   {c: row_b.get(c, "") for c in uso_cols},
            "extra_a": row_a.get("nombre_cientifico", ""),
            "extra_b": row_b.get("nombre_cientifico", ""),
            "uso_cols": uso_cols,
        })

    return pairs


def progress(pairs: list[dict], decisions: dict) -> tuple[int, int]:
    decided = sum(
        1 for p in pairs
        if decisions["pairs"].get(p["key"], "Decidir después") != "Decidir después"
    )
    return decided, len(pairs)


def _apply_rename(decisions: dict, old: str, new: str) -> dict:
    """Update all references to `old` name inside a decisions dict."""
    # renames log
    renames = decisions.get("renames", [])
    # collapse chains: if old was itself a rename target, update the chain
    renames = [r for r in renames if r["to"] != old]
    renames.append({"from": old, "to": new})
    decisions["renames"] = renames

    # deleted / approved lists
    decisions["deleted"]  = [new if n == old else n for n in decisions.get("deleted", [])]
    decisions["approved"] = [new if n == old else n for n in decisions.get("approved", [])]

    # pair keys: key is "|".join(sorted([a, b])), value is decision string
    new_pairs = {}
    for key, val in decisions.get("pairs", {}).items():
        parts = key.split("|")
        parts = [new if p == old else p for p in parts]
        new_key = "|".join(sorted(parts))
        new_pairs[new_key] = val
    decisions["pairs"] = new_pairs

    return decisions


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def sidebar() -> str:
    st.sidebar.title("🐟 Revisión de Catálogos")
    st.sidebar.caption("Monitoreo Pesquero — Pronatura Noroeste")
    st.sidebar.divider()

    available = [t for t in NAME_COLS if (EXPORT_DIR / f"{t}.csv").exists()]
    if not available:
        st.sidebar.error(f"No se encontraron CSVs en:\n{EXPORT_DIR}")
        st.stop()

    options = []
    for t in available:
        df = load_csv(t)
        if df is None:
            continue
        pairs = get_pairs(df, NAME_COLS[t])   # cached after first call
        dec   = load_decisions(t)
        done, total = progress(pairs, dec)
        badge = "✅" if (total > 0 and done == total) else (f"{done}/{total}" if total > 0 else "—")
        options.append((f"{TABLE_LABELS.get(t, t)}  [{badge}]", t))

    labels = [o[0] for o in options]
    idx = st.sidebar.radio("Catálogo", range(len(labels)), format_func=lambda i: labels[i])

    st.sidebar.divider()
    st.sidebar.caption("**Leyenda**")
    st.sidebar.markdown("🔴 Duplicado exacto\n🟠 Probable (≥92%)\n🟡 Posible (≥78%)")

    return options[idx][1]


# ---------------------------------------------------------------------------
# Pairs tab
# ---------------------------------------------------------------------------

def render_pairs(table: str, df: pd.DataFrame, name_col: str):
    pairs     = get_pairs(df, name_col)
    decisions = load_decisions(table)

    if not pairs:
        st.info("No hay pares flaggeados en este catálogo.")
        return

    done, total = progress(pairs, decisions)
    st.progress(done / total if total else 0, text=f"{done} de {total} pares revisados")

    filt = st.segmented_control(
        "Mostrar",
        ["Todos", "Solo pendientes", "🔴 Exacto", "🟠 Probable", "🟡 Posible"],
        default="Solo pendientes",
    )

    changed = False
    for pair in pairs:
        current = decisions["pairs"].get(pair["key"], "Decidir después")
        pending = current == "Decidir después"

        if filt == "Solo pendientes" and not pending:
            continue
        if filt == "🔴 Exacto"   and pair["flag"] != "DUPLICADO_EXACTO":
            continue
        if filt == "🟠 Probable" and pair["flag"] != "DUPLICADO_PROBABLE":
            continue
        if filt == "🟡 Posible"  and pair["flag"] != "POSIBLE_DUPLICADO":
            continue

        emoji = FLAG_EMOJI.get(pair["flag"], "⚪")
        pct   = f" ({pair['pct']}% similitud)" if pair["pct"] else ""

        with st.container(border=True):
            st.markdown(f"{emoji} **{pair['flag'].replace('_', ' ').title()}**{pct}")

            col_a, col_sep, col_b = st.columns([10, 1, 10])

            with col_a:
                st.markdown(f"**A** — `{pair['a']}`")
                if pair["extra_a"]:
                    st.caption(f"_{pair['extra_a']}_")
                for c, v in pair["uso_a"].items():
                    if v and v != "0":
                        st.caption(f"{c.replace('uso_', '').replace('_', ' ')}: **{v}**")

            with col_sep:
                st.markdown(
                    "<div style='text-align:center;padding-top:1.2rem'>↔</div>",
                    unsafe_allow_html=True,
                )

            with col_b:
                st.markdown(f"**B** — `{pair['b']}`")
                if pair["extra_b"]:
                    st.caption(f"_{pair['extra_b']}_")
                for c, v in pair["uso_b"].items():
                    if v and v != "0":
                        st.caption(f"{c.replace('uso_', '').replace('_', ' ')}: **{v}**")

            choice = st.radio(
                "Decisión",
                DECISIONS,
                index=DECISIONS.index(current),
                key=f"pair_{table}_{pair['key']}",
                horizontal=True,
                label_visibility="collapsed",
            )

            if choice != current:
                decisions["pairs"][pair["key"]] = choice
                deleted = set(decisions.get("deleted", []))
                if choice == "Mantener A — eliminar B":
                    deleted.discard(pair["a"]); deleted.add(pair["b"])
                elif choice == "Mantener B — eliminar A":
                    deleted.discard(pair["b"]); deleted.add(pair["a"])
                else:
                    deleted.discard(pair["a"]); deleted.discard(pair["b"])
                decisions["deleted"] = sorted(deleted)
                changed = True

    if changed:
        save_decisions(table, decisions)
        st.rerun()

    st.divider()
    done2, _ = progress(pairs, decisions)
    st.caption(
        f"✅ {done2}/{total} pares decididos  •  "
        f"🗑 {len(decisions.get('deleted', []))} entradas marcadas para eliminar"
    )


# ---------------------------------------------------------------------------
# All entries tab
# ---------------------------------------------------------------------------

def render_all(table: str, df: pd.DataFrame, name_col: str):
    decisions    = load_decisions(table)
    deleted_set  = set(decisions.get("deleted", []))
    approved_set = set(decisions.get("approved", []))
    all_names    = set(df[name_col].tolist())

    # --- columns to show ---
    display_cols = [name_col]
    if "nombre_cientifico" in df.columns:
        display_cols.append("nombre_cientifico")
    geo_cols = [c for c in ["region", "zona", "area"] if c in df.columns and c != name_col]
    uso_cols = [c for c in df.columns if c.startswith("uso_")]
    display_cols += geo_cols + uso_cols

    display = df[display_cols].copy()
    display.insert(0, "✓ Aprobar", display[name_col].map(lambda n: n in approved_set))
    display.insert(1, "Estado", display[name_col].map(
        lambda n: "🗑 Eliminar" if n in deleted_set
        else ("✅ Aprobado" if n in approved_set else "")
    ))

    # --- batch actions ---
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("✅ Aprobar todos los no eliminados", use_container_width=True):
            decisions["approved"] = sorted(
                r[name_col] for _, r in df.iterrows() if r[name_col] not in deleted_set
            )
            save_decisions(table, decisions)
            st.rerun()
    with col2:
        if st.button("↩️ Limpiar aprobaciones", use_container_width=True):
            decisions["approved"] = []
            save_decisions(table, decisions)
            st.rerun()
    with col3:
        pending = len(df) - len(approved_set) - len(deleted_set)
        st.caption(f"{len(approved_set)} aprobados · {len(deleted_set)} a eliminar · {pending} pendientes")

    # --- filter ---
    show = st.selectbox(
        "Filtrar",
        ["Todas", "Solo pendientes", "Aprobados", "A eliminar", "Flaggeados", "Renombrados"],
    )
    renamed_names = {r["from"] for r in decisions.get("renames", [])}
    if show == "Solo pendientes":
        display = display[~display[name_col].isin(approved_set | deleted_set)]
    elif show == "Aprobados":
        display = display[display[name_col].isin(approved_set)]
    elif show == "A eliminar":
        display = display[display[name_col].isin(deleted_set)]
    elif show == "Flaggeados" and "flag_tipo" in df.columns:
        flagged_names = set(df[df["flag_tipo"] != ""][name_col])
        display = display[display[name_col].isin(flagged_names)]
    elif show == "Renombrados":
        display = display[display[name_col].isin(renamed_names)]

    # --- editable columns ---
    editable = {"✓ Aprobar", name_col}
    if "nombre_cientifico" in display.columns:
        editable.add("nombre_cientifico")
    read_only = [c for c in display.columns if c not in editable]

    st.caption("✏️ Los campos **nombre** son editables — doble clic para corregir una entrada directamente.")

    # keep a snapshot of names before editing (by index) for rename detection
    pre_edit = display[[name_col]].copy()
    if "nombre_cientifico" in display.columns:
        pre_edit = display[[name_col, "nombre_cientifico"]].copy()

    edited = st.data_editor(
        display,
        column_config={
            "✓ Aprobar": st.column_config.CheckboxColumn("✓ Aprobar", width="small"),
            "Estado":    st.column_config.TextColumn("Estado", width="small", disabled=True),
            name_col:    st.column_config.TextColumn("Nombre", help="Editable — corrige el texto directamente"),
        },
        use_container_width=True,
        hide_index=True,
        disabled=read_only,
        key=f"editor_{table}",
    )

    # --- detect renames ---
    renames_applied = False
    for idx in pre_edit.index:
        if idx not in edited.index:
            continue

        old_name = pre_edit.at[idx, name_col]
        new_name = edited.at[idx, name_col].strip()

        if new_name and new_name != old_name:
            if new_name in all_names and new_name != old_name:
                st.warning(
                    f"⚠️ **'{new_name}'** ya existe en este catálogo. "
                    "Considera usar la pestaña de duplicados para gestionar este par."
                )
            else:
                # Update CSV
                full_df = load_csv(table).copy()
                full_df.loc[full_df[name_col] == old_name, name_col] = new_name
                save_csv(table, full_df)

                # Update decisions
                decisions = _apply_rename(decisions, old_name, new_name)

                # Update approved/deleted sets for subsequent iterations
                approved_set = {new_name if n == old_name else n for n in approved_set}
                deleted_set  = {new_name if n == old_name else n for n in deleted_set}
                all_names    = {new_name if n == old_name else n for n in all_names}

                st.toast(f"✏️ Renombrado: '{old_name}' → '{new_name}'")
                renames_applied = True

        # nombre_cientifico edit (cat_especie only)
        if "nombre_cientifico" in pre_edit.columns:
            old_sci = pre_edit.at[idx, "nombre_cientifico"]
            new_sci = edited.at[idx, "nombre_cientifico"].strip()
            if new_sci and new_sci != old_sci:
                full_df = load_csv(table).copy()
                full_df.loc[full_df[name_col] == new_name, "nombre_cientifico"] = new_sci
                save_csv(table, full_df)
                st.toast(f"✏️ Nombre científico actualizado: '{old_sci}' → '{new_sci}'")
                renames_applied = True

    if renames_applied:
        save_decisions(table, decisions)
        load_csv.clear()    # invalidate Streamlit cache so rerun sees updated CSV
        get_pairs.clear()   # pairs may reference old names
        st.rerun()

    # --- persist approval checkbox changes ---
    new_approved = set(edited.loc[edited["✓ Aprobar"], name_col].tolist())
    new_rejected  = set(edited.loc[~edited["✓ Aprobar"], name_col].tolist())
    merged = (approved_set | new_approved) - new_rejected - deleted_set
    if merged != approved_set:
        decisions["approved"] = sorted(merged)
        save_decisions(table, decisions)

    # --- renames log at bottom ---
    if decisions.get("renames"):
        with st.expander(f"📝 Renombres aplicados ({len(decisions['renames'])})"):
            st.dataframe(
                pd.DataFrame(decisions["renames"]),
                use_container_width=True,
                hide_index=True,
            )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(
        page_title="Revisión Catálogos",
        page_icon="🐟",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    table    = sidebar()
    df       = load_csv(table)
    if df is None or df.empty:
        st.error(f"No se pudo cargar {table}.csv")
        return

    name_col    = NAME_COLS.get(table, df.columns[0])
    decisions   = load_decisions(table)
    pairs       = get_pairs(df, name_col)
    done, total = progress(pairs, decisions)

    st.title(f"📋 {TABLE_LABELS.get(table, table)}")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total entradas",   len(df))
    m2.metric("Pares flaggeados", total)
    m3.metric("Pares revisados",  f"{done}/{total}")
    m4.metric("A eliminar",       len(decisions.get("deleted", [])))
    m5.metric("Renombrados",      len(decisions.get("renames", [])))

    tab_pairs, tab_all = st.tabs([
        f"🔁 Duplicados posibles  ({total})",
        f"📋 Todas las entradas  ({len(df)})",
    ])

    with tab_pairs:
        render_pairs(table, df, name_col)

    with tab_all:
        render_all(table, df, name_col)


if __name__ == "__main__":
    main()
