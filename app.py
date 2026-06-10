"""
Catalog Review App — Streamlit
Revisión de catálogos de monitoreo pesquero con biólogos.

Run:  streamlit run app.py
Docker: docker compose up
"""

import collections
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
        df.drop_duplicates(subset=[name_col]).set_index(name_col)[lookup_cols].to_dict("index")
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


@st.cache_data
def table_pairs(table: str) -> list[dict]:
    """Pairs for a table, cached by NAME (cheap lookup) — avoids re-hashing the
    full DataFrame on every rerun, which the sidebar does once per catalog."""
    df = load_csv(table)
    if df is None:
        return []
    return get_pairs(df, NAME_COLS.get(table, df.columns[0]))


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
# Cluster helpers  (Phase 1 — read-only validation)
# ---------------------------------------------------------------------------

DECISION_KEEP_A = "Mantener A — eliminar B"
DECISION_KEEP_B = "Mantener B — eliminar A"
DECISION_BOTH   = "Ambos son válidos"
DECISION_LATER  = "Decidir después"


@st.cache_data
def usage_lookup(df: pd.DataFrame, name_col: str) -> dict:
    """name → total usage across all uso_* columns (non-numeric coerced to 0)."""
    uso_cols = [c for c in df.columns if c.startswith("uso_")]
    if not uso_cols:
        return {}
    sub = df.drop_duplicates(subset=[name_col]).set_index(name_col)[uso_cols]
    totals = sub.apply(pd.to_numeric, errors="coerce").fillna(0).sum(axis=1)
    return totals.to_dict()


def _components(nodes: set, edges: list) -> list[list]:
    """Connected components via union-find. `edges` is a list of (a, b) tuples."""
    parent = {n: n for n in nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    groups: dict = {}
    for n in nodes:
        groups.setdefault(find(n), []).append(n)
    return list(groups.values())


def _connected(adj: dict, src, dst, skip: frozenset) -> bool:
    """Is `dst` reachable from `src` if we ignore the single edge `skip`?"""
    seen = {src}
    stack = [src]
    while stack:
        x = stack.pop()
        for y in adj[x]:
            if frozenset((x, y)) == skip:
                continue
            if y == dst:
                return True
            if y not in seen:
                seen.add(y)
                stack.append(y)
    return False


def find_bridges(edges: list[dict]) -> set:
    """Edges (as frozenset{a,b}) whose removal disconnects their endpoints."""
    adj: dict = collections.defaultdict(set)
    for e in edges:
        adj[e["a"]].add(e["b"])
        adj[e["b"]].add(e["a"])
    bridges = set()
    for e in edges:
        key = frozenset((e["a"], e["b"]))
        if not _connected(adj, e["a"], e["b"], skip=key):
            bridges.add(key)
    return bridges


def build_clusters(pairs: list[dict], decisions: dict) -> list[dict]:
    """Connected components of flagged records, ignoring 'Ambos válidos' edges (cuts).

    Edge orientation (a, b) is preserved from get_pairs so the pairwise decision
    strings ('Mantener A …') can be interpreted later. Singletons are dropped.
    """
    pair_dec = decisions.get("pairs", {})
    nodes: set = set()
    live: list[dict] = []
    for p in pairs:
        nodes.add(p["a"]); nodes.add(p["b"])
        if pair_dec.get(p["key"]) == DECISION_BOTH:
            continue  # edge cut — biologist confirmed these are distinct
        live.append({"a": p["a"], "b": p["b"], "pct": p.get("pct", ""), "flag": p["flag"]})

    edge_tuples = [(e["a"], e["b"]) for e in live]
    clusters = []
    for members in _components(nodes, edge_tuples):
        if len(members) < 2:
            continue
        mset = set(members)
        edges = [e for e in live if e["a"] in mset and e["b"] in mset]
        clusters.append({
            "members": sorted(members),
            "edges":   edges,
            "bridges": find_bridges(edges),
        })
    clusters.sort(key=lambda c: -len(c["members"]))
    return clusters


@st.cache_data
def table_clusters(table: str, cut_keys: tuple) -> list[dict]:
    """build_clusters cached by table + the set of cut ('Ambos válidos') edges —
    cluster shape depends only on those, so ordinary decisions don't trigger a rebuild.
    Runs in both main() and render_clusters; caching avoids the double O(E²) cost."""
    decisions = {"pairs": {k: DECISION_BOTH for k in cut_keys}}
    return build_clusters(table_pairs(table), decisions)


def cut_keys_of(decisions: dict) -> tuple:
    """Sorted tuple of pair keys the biologist marked as 'Ambos válidos' (edge cuts)."""
    return tuple(sorted(
        k for k, v in decisions.get("pairs", {}).items() if v == DECISION_BOTH
    ))


def reconcile_cluster(cluster: dict, decisions: dict) -> dict:
    """Derive a cluster-level conclusion from the existing pairwise decisions."""
    pair_dec = decisions.get("pairs", {})
    survivors: set = set()   # implied kept
    losers: set = set()      # implied deleted
    pending = 0

    for e in cluster["edges"]:
        key = "|".join(sorted([e["a"], e["b"]]))
        dec = pair_dec.get(key, DECISION_LATER)
        if dec == DECISION_KEEP_A:
            survivors.add(e["a"]); losers.add(e["b"])
        elif dec == DECISION_KEEP_B:
            survivors.add(e["b"]); losers.add(e["a"])
        else:  # Decidir después / unknown
            pending += 1

    contradictory  = survivors & losers          # kept in one pair, deleted in another
    pure_survivors = survivors - losers
    decided        = len(cluster["edges"]) - pending

    conflicts = []
    if contradictory:
        conflicts.append(
            "Conservado y eliminado a la vez: " + ", ".join(sorted(contradictory))
        )
    if len(pure_survivors) > 1:
        conflicts.append(
            "Más de un sobreviviente implícito: " + ", ".join(sorted(pure_survivors))
        )

    if conflicts:
        status = "conflicto"
    elif pending == 0 and decided > 0 and len(pure_survivors) <= 1:
        status = "resuelto"
    else:
        status = "pendiente"

    return {
        "status":           status,
        "implied_survivor": next(iter(pure_survivors)) if len(pure_survivors) == 1 else "",
        "survivors":        survivors,
        "losers":           losers,
        "pending":          pending,
        "conflicts":        conflicts,
    }


def cluster_survivor_default(cluster: dict, recon: dict, usage: dict) -> str:
    """Honor the biologist's implied survivor; else the most-used record."""
    if recon["implied_survivor"]:
        return recon["implied_survivor"]
    # most usage wins; shorter name breaks ties (tends to be the clean spelling)
    return max(cluster["members"], key=lambda n: (usage.get(n, 0), -len(n)))


def _pct_below(pct, threshold: float) -> bool:
    try:
        return float(pct) < threshold
    except (ValueError, TypeError):
        return False


def over_merge_warning(cluster: dict) -> str:
    """Heuristic flag for likely false clustering (transitive over-merge)."""
    members, edges, bridges = cluster["members"], cluster["edges"], cluster["bridges"]
    if len(members) < 3:
        return ""

    reasons = []
    weak_bridges = [
        e for e in edges
        if frozenset((e["a"], e["b"])) in bridges and _pct_below(e["pct"], 92)
    ]
    if weak_bridges:
        reasons.append("se sostiene por enlaces débiles (puente <92%)")

    pcts = [float(e["pct"]) for e in edges if _pct_below(e["pct"], 1e9)]  # numeric only
    if len(members) >= 6 and pcts and max(pcts) <= 92 and len(edges) <= len(members):
        reasons.append("grupo grande con similitud uniformemente baja")

    return "; ".join(reasons)


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

    # The radio options/labels MUST stay static. Previously each label embedded a live
    # progress badge (e.g. "[138/535]"); when a decision changed that badge during the
    # st.rerun(), the browser radio lost its checked state and the next click fell back
    # to index 0 — jumping the user to the first catalog. Options are now the table ids
    # with fixed names; progress is rendered separately below as plain markdown.
    selected = st.sidebar.radio(
        "Catálogo",
        available,
        format_func=lambda t: TABLE_LABELS.get(t, t),
        key="sidebar_catalog",
    )

    st.sidebar.divider()
    st.sidebar.caption("**Progreso**")
    rows = []
    for t in available:
        done, total = progress(table_pairs(t), load_decisions(t))
        badge = "✅" if (total > 0 and done == total) else (f"{done}/{total}" if total > 0 else "—")
        mark  = "**▶**" if t == selected else "•"
        rows.append(f"- {mark} {TABLE_LABELS.get(t, t)} — `{badge}`")
    st.sidebar.markdown("\n".join(rows))

    st.sidebar.divider()
    st.sidebar.caption("**Leyenda**")
    st.sidebar.markdown("🔴 Duplicado exacto\n🟠 Probable (≥92%)\n🟡 Posible (≥78%)")

    return selected


# ---------------------------------------------------------------------------
# Pairs tab
# ---------------------------------------------------------------------------

def render_pairs(table: str, df: pd.DataFrame, name_col: str):
    pairs     = table_pairs(table)
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
        key=f"pairs_filt_{table}",
    )

    # Filter first, then paginate. Rendering every pair as its own card+radio is the
    # bottleneck (e.g. cat_sitio_pesca has 400+ pending pairs → ~8s per rerun), so we
    # only ever render one page of cards.
    def _passes(pair) -> bool:
        if filt == "Solo pendientes":
            return decisions["pairs"].get(pair["key"], "Decidir después") == "Decidir después"
        if filt == "🔴 Exacto":   return pair["flag"] == "DUPLICADO_EXACTO"
        if filt == "🟠 Probable": return pair["flag"] == "DUPLICADO_PROBABLE"
        if filt == "🟡 Posible":  return pair["flag"] == "POSIBLE_DUPLICADO"
        return True  # Todos

    visible = [p for p in pairs if _passes(p)]
    if not visible:
        st.success("✅ No hay pares que coincidan con este filtro.")
        return

    PAGE_SIZE = 25
    n_pages   = (len(visible) + PAGE_SIZE - 1) // PAGE_SIZE
    page_key  = f"pairs_page_{table}"
    # clamp any stale page before the widget is built (e.g. after decisions shrink the list)
    if st.session_state.get(page_key, 1) > n_pages:
        st.session_state[page_key] = n_pages

    if n_pages > 1:
        page = st.number_input(
            f"Página (1–{n_pages})", min_value=1, max_value=n_pages, step=1, key=page_key
        )
    else:
        page = 1

    start      = (page - 1) * PAGE_SIZE
    page_pairs = visible[start:start + PAGE_SIZE]
    st.caption(f"Mostrando {start + 1}–{start + len(page_pairs)} de {len(visible)} pares")

    changed = False
    for pair in page_pairs:
        current = decisions["pairs"].get(pair["key"], "Decidir después")

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
        load_csv.clear()     # invalidate Streamlit cache so rerun sees updated CSV
        get_pairs.clear()    # pairs may reference old names
        table_pairs.clear()    # name-keyed pairs cache also references old names
        table_clusters.clear() # clusters derive from pairs → rebuild after rename
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
# Clusters tab  (read-only — Phase 1)
# ---------------------------------------------------------------------------

STATUS_CHIP = {
    "resuelto":  "✅ Resuelto",
    "pendiente": "🕓 Pendiente",
    "conflicto": "⚠️ Conflicto",
}


def render_clusters(table: str, df: pd.DataFrame, name_col: str):
    decisions = load_decisions(table)
    usage     = usage_lookup(df, name_col)
    clusters  = table_clusters(table, cut_keys_of(decisions))

    if not clusters:
        st.info("No hay grupos de duplicados en este catálogo.")
        return

    recons = [reconcile_cluster(c, decisions) for c in clusters]
    warns  = [over_merge_warning(c) for c in clusters]

    n_multi = sum(1 for c in clusters if len(c["members"]) >= 3)
    n_res   = sum(1 for r in recons if r["status"] == "resuelto")
    n_pen   = sum(1 for r in recons if r["status"] == "pendiente")
    n_con   = sum(1 for r in recons if r["status"] == "conflicto")
    n_warn  = sum(1 for w in warns if w)

    st.caption(
        f"**{len(clusters)} grupos**  •  {n_multi} con 3+ miembros  •  "
        f"✅ {n_res} resueltos  •  🕓 {n_pen} pendientes  •  "
        f"⚠️ {n_con} conflictos  •  🚩 {n_warn} posible sobre-agrupación"
    )
    st.caption(
        "Vista de **solo lectura**. Reconstruye los grupos a partir de las decisiones por "
        "pares ya tomadas. Las acciones para colapsar grupos llegarán en una fase posterior."
    )

    filt = st.segmented_control(
        "Mostrar",
        ["Todos", "Pendientes", "Conflictos", "🚩 Sobre-agrupación", "Resueltos"],
        default="Todos",
        key=f"cluster_filt_{table}",
    )

    # distinguishing columns for context
    has_sci  = "nombre_cientifico" in df.columns
    geo_cols = [c for c in ["region", "zona", "area"] if c in df.columns and c != name_col]
    dedup    = df.drop_duplicates(subset=[name_col]).set_index(name_col)
    sci_lk   = dedup["nombre_cientifico"].to_dict() if has_sci else {}
    geo_lk   = {c: dedup[c].to_dict() for c in geo_cols}

    def _passes(recon, warn) -> bool:
        if filt == "Pendientes":          return recon["status"] == "pendiente"
        if filt == "Conflictos":          return recon["status"] == "conflicto"
        if filt == "Resueltos":           return recon["status"] == "resuelto"
        if filt == "🚩 Sobre-agrupación": return bool(warn)
        return True  # Todos

    visible = [t for t in zip(clusters, recons, warns) if _passes(t[1], t[2])]
    if not visible:
        st.success("✅ No hay grupos que coincidan con este filtro.")
        return

    PAGE_SIZE = 20
    n_pages   = (len(visible) + PAGE_SIZE - 1) // PAGE_SIZE
    page_key  = f"cluster_page_{table}"
    if st.session_state.get(page_key, 1) > n_pages:
        st.session_state[page_key] = n_pages

    if n_pages > 1:
        page = st.number_input(
            f"Página (1–{n_pages})", min_value=1, max_value=n_pages, step=1, key=page_key
        )
    else:
        page = 1

    start = (page - 1) * PAGE_SIZE
    page_clusters = visible[start:start + PAGE_SIZE]
    st.caption(f"Mostrando {start + 1}–{start + len(page_clusters)} de {len(visible)} grupos")

    for cluster, recon, warn in page_clusters:
        status   = recon["status"]
        members  = cluster["members"]
        survivor = cluster_survivor_default(cluster, recon, usage)

        with st.container(border=True):
            head = f"**Grupo de {len(members)}**  —  {STATUS_CHIP.get(status, status)}"
            if warn:
                head += "  •  🚩 **Posible sobre-agrupación**"
            st.markdown(head)

            if warn:
                st.caption(
                    f"🚩 {warn}. Revisa los enlaces antes de colapsar — "
                    "podrían ser registros **distintos**."
                )
            for c in recon["conflicts"]:
                st.caption(f"⚠️ {c}")

            # --- members ---
            rows = []
            for m in members:
                if m == survivor:
                    role = "👑 sobreviviente"
                elif m in recon["losers"]:
                    role = "🗑 eliminar"
                else:
                    role = "—"
                row = {"Registro": m, "Uso": usage.get(m, 0), "Rol propuesto": role}
                if has_sci:
                    row["Nombre científico"] = sci_lk.get(m, "")
                for c in geo_cols:
                    row[c] = geo_lk[c].get(m, "")
                rows.append(row)
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            # --- edge evidence ---
            with st.expander(f"🔗 Enlaces internos ({len(cluster['edges'])})"):
                erows = [{
                    "A":           e["a"],
                    "B":           e["b"],
                    "Similitud %": e["pct"],
                    "Tipo":        e["flag"].replace("_", " ").title(),
                    "Puente":      "🌉 sí" if frozenset((e["a"], e["b"])) in cluster["bridges"] else "",
                } for e in cluster["edges"]]
                st.dataframe(pd.DataFrame(erows), use_container_width=True, hide_index=True)


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
    pairs       = table_pairs(table)
    done, total = progress(pairs, decisions)
    clusters    = table_clusters(table, cut_keys_of(decisions))

    st.title(f"📋 {TABLE_LABELS.get(table, table)}")
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Total entradas",   len(df))
    m2.metric("Pares flaggeados", total)
    m3.metric("Pares revisados",  f"{done}/{total}")
    m4.metric("Grupos",           len(clusters))
    m5.metric("A eliminar",       len(decisions.get("deleted", [])))
    m6.metric("Renombrados",      len(decisions.get("renames", [])))

    # NOTE: deliberately NOT st.tabs — st.tabs resets to the first tab on every
    # rerun (e.g. after a decision triggers st.rerun()), which threw the user back
    # to "Duplicados". A keyed radio persists the active view across reruns, and we
    # render only the selected view (faster than st.tabs, which renders all three).
    view = st.radio(
        "Vista",
        ["pairs", "all", "clusters"],
        format_func=lambda v: {
            "pairs":    f"🔁 Duplicados posibles  ({total})",
            "all":      f"📋 Todas las entradas  ({len(df)})",
            "clusters": f"🧬 Grupos  ({len(clusters)})",
        }[v],
        horizontal=True,
        key="main_view",
        label_visibility="collapsed",
    )
    st.divider()

    if view == "pairs":
        render_pairs(table, df, name_col)
    elif view == "all":
        render_all(table, df, name_col)
    else:
        render_clusters(table, df, name_col)


if __name__ == "__main__":
    main()
