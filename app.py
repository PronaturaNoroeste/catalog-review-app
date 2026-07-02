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
    # Invariant: a name must not be both a new_record AND a rename target. That combo
    # makes the importer insert it (Phase 0) and then collide renaming onto it (Phase 1).
    # The rename produces the name, so it stays out of new_records.
    targets = {r.get("to") for r in decisions.get("renames", [])}
    if decisions.get("new_records"):
        decisions["new_records"] = [n for n in decisions["new_records"] if n not in targets]
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


def merge_lookup(decisions: dict) -> dict:
    """record name → its survivor, for every collapsed group (Phase 2 `merges`)."""
    lk: dict = {}
    for survivor, absorbed in decisions.get("merges", {}).items():
        lk[survivor] = survivor
        for a in absorbed:
            lk[a] = survivor
    return lk


def pair_decided(pair: dict, decisions: dict, lk: dict) -> bool:
    """A pair counts as decided if it has a pairwise decision, OR both of its
    records were collapsed into the same survivor (resolved via a cluster merge)."""
    if decisions.get("pairs", {}).get(pair["key"], "Decidir después") != "Decidir después":
        return True
    ga, gb = lk.get(pair["a"]), lk.get(pair["b"])
    return ga is not None and ga == gb


def progress(pairs: list[dict], decisions: dict) -> tuple[int, int]:
    lk = merge_lookup(decisions)
    decided = sum(1 for p in pairs if pair_decided(p, decisions, lk))
    return decided, len(pairs)


def _apply_rename(decisions: dict, old: str, new: str, log: bool = True) -> dict:
    """Update all references to `old` name inside a decisions dict. When `log` is
    False (the row is a user-created new_record with no row in the DB yet), the
    rename is NOT recorded in the renames log — otherwise the importer would try to
    rename a non-existent row and the corrected name would be both a new_record and a
    rename target (Phase-0 insert + Phase-1 rename → unique-key collision)."""
    # renames log
    renames = decisions.get("renames", [])
    # collapse chains: if old was itself a rename target, update the chain
    renames = [r for r in renames if r["to"] != old]
    if log:
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
def table_clusters(table: str, cut_keys: tuple, manual: tuple = ()) -> list[dict]:
    """build_clusters cached by table + the set of cut ('Ambos válidos') edges and any
    manually-added links — cluster shape depends only on those, so ordinary decisions
    don't trigger a rebuild. Runs in both main() and render_clusters; caching avoids the
    double O(E²) cost."""
    decisions = {"pairs": {k: DECISION_BOTH for k in cut_keys}}
    pairs = list(table_pairs(table))
    existing = {p["key"] for p in pairs}
    for a, b in manual:                      # user-added edges the matcher missed
        key = _pairkey(a, b)
        if key not in existing:
            pairs.append({"key": key, "a": a, "b": b, "pct": "", "flag": "MANUAL"})
    return build_clusters(pairs, decisions)


def cut_keys_of(decisions: dict) -> tuple:
    """Sorted tuple of pair keys the biologist marked as 'Ambos válidos' (edge cuts)."""
    return tuple(sorted(
        k for k, v in decisions.get("pairs", {}).items() if v == DECISION_BOTH
    ))


def manual_links_of(decisions: dict) -> tuple:
    """Sorted tuple of (a, b) edges the user manually added to groups."""
    return tuple(sorted(tuple(sorted(p)) for p in decisions.get("manual_links", [])))


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


def cluster_survivor_default(cluster: dict, recon: dict, usage: dict, new_records=()) -> str:
    """A record the user just created (the correct spelling) wins; then the biologist's
    implied survivor; else the most-used record."""
    created = [m for m in cluster["members"] if m in new_records]
    if created:
        return created[-1]
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


# --- Phase 2: interactive collapse (all writes are intent-only; CSV is never mutated) ---

ACT_KEEP  = "👑 Conservar"
ACT_MERGE = "Fusionar"
ACT_SEP   = "Separar"
ACT_LATER = "Decidir después"
ACTION_OPTS = [ACT_KEEP, ACT_MERGE, ACT_SEP, ACT_LATER]


def _pairkey(a: str, b: str) -> str:
    return "|".join(sorted([a, b]))


def cluster_collapsed(cluster: dict, lk: dict) -> str | None:
    """If every member maps to the same survivor in `merges`, return that survivor."""
    groups = {lk.get(m) for m in cluster["members"]}
    if len(groups) == 1 and None not in groups:
        return next(iter(groups))
    return None


def apply_collapse(decisions: dict, cluster: dict, survivor: str, actions: dict) -> dict:
    """Collapse a cluster around `survivor`. `actions` maps each NON-survivor member to
    one of ACT_MERGE / ACT_SEP / ACT_LATER. Mutates and returns `decisions`.

      Fusionar → record in merges[survivor] + mark deleted; set the survivor-incident
                 pair decision so the Duplicados tab agrees.
      Separar  → cut every edge touching that member ('Ambos válidos') so it splits off.
      Decidir después → left untouched.
    """
    pairs   = decisions.setdefault("pairs", {})
    merges  = decisions.setdefault("merges", {})
    deleted = set(decisions.get("deleted", []))
    approved = set(decisions.get("approved", []))

    absorbed  = [m for m, a in actions.items() if a == ACT_MERGE]
    separated = [m for m, a in actions.items() if a == ACT_SEP]

    edge_by_pair = {frozenset((e["a"], e["b"])): e for e in cluster["edges"]}

    # merges
    group = set(merges.get(survivor, [])) | set(absorbed)
    deleted |= set(absorbed)
    deleted.discard(survivor)
    approved.add(survivor)
    for m in absorbed:
        e = edge_by_pair.get(frozenset((survivor, m)))
        if e:  # only direct survivor↔loser edges are representable pairwise
            pairs[_pairkey(survivor, m)] = (
                "Mantener A — eliminar B" if e["a"] == survivor else "Mantener B — eliminar A"
            )

    # separations cut edges and undo any prior merge of that member
    for m in separated:
        for e in cluster["edges"]:
            if m in (e["a"], e["b"]):
                pairs[_pairkey(e["a"], e["b"])] = "Ambos son válidos"
        deleted.discard(m)
        group.discard(m)

    if group:
        merges[survivor] = sorted(group)
    else:
        merges.pop(survivor, None)

    decisions["deleted"]  = sorted(deleted)
    decisions["approved"] = sorted(approved)
    return decisions


def apply_separate_all(decisions: dict, cluster: dict) -> dict:
    """Mark the whole cluster as distinct records (cut every internal edge)."""
    pairs = decisions.setdefault("pairs", {})
    for e in cluster["edges"]:
        pairs[_pairkey(e["a"], e["b"])] = "Ambos son válidos"
    return decisions


def reopen_cluster(decisions: dict, cluster: dict, survivor: str) -> dict:
    """Undo a collapse: drop the merge, un-delete absorbed members, and reset the
    cluster's internal pair decisions back to pending."""
    merges   = decisions.setdefault("merges", {})
    deleted  = set(decisions.get("deleted", []))
    approved = set(decisions.get("approved", []))

    deleted -= set(merges.get(survivor, []))
    approved.discard(survivor)
    merges.pop(survivor, None)

    pairs = decisions.setdefault("pairs", {})
    for e in cluster["edges"]:
        pairs.pop(_pairkey(e["a"], e["b"]), None)

    decisions["deleted"]  = sorted(deleted)
    decisions["approved"] = sorted(approved)
    return decisions


def add_manual_link(decisions: dict, member: str, new: str) -> dict:
    """Manually link `new` (a record the matcher missed) to a cluster member, so it
    joins that group. Reverses any prior 'Separar' cut on the same pair."""
    links = decisions.setdefault("manual_links", [])
    pair  = sorted([member, new])
    if pair not in [sorted(p) for p in links]:
        links.append(pair)
    decisions.get("pairs", {}).pop(_pairkey(member, new), None)  # un-cut if separated before
    return decisions


def create_new_record(table: str, name: str, name_col: str, fields: dict | None = None) -> bool:
    """Append a brand-new row to the catalog CSV — used when the correct name doesn't
    exist in the data yet. `fields` fills the other columns (else blank). Returns False
    if it already exists. Mutates the CSV (like renames do) and clears derived caches."""
    df = load_csv(table)
    if df is None or name in set(df[name_col].tolist()):
        return False
    row = {c: "" for c in df.columns}
    row[name_col] = name
    for c, v in (fields or {}).items():
        if c in row:
            row[c] = v
    save_csv(table, pd.concat([df, pd.DataFrame([row])], ignore_index=True))
    for cache in (load_csv, get_pairs, table_pairs, table_clusters, usage_lookup):
        cache.clear()
    return True


def _rename_in_phase2(decisions: dict, old: str, new: str):
    """Update the Phase 2 decision keys (merges / manual_links / new_records) on rename."""
    merges = decisions.get("merges", {})
    if old in merges:
        merges[new] = merges.pop(old)
    for s in list(merges):
        merges[s] = [new if x == old else x for x in merges[s]]
    decisions["manual_links"] = [[new if x == old else x for x in p]
                                 for p in decisions.get("manual_links", [])]
    decisions["new_records"]  = [new if x == old else x for x in decisions.get("new_records", [])]


def rename_record(table: str, old: str, new: str, name_col: str, decisions: dict) -> str:
    """Rename an existing record to fix its spelling. Updates the CSV (both `name_col`
    AND every `similar_a` that referenced the old name, so cluster edges stay intact)
    and all decision keys. Returns "" on success, else an error message."""
    new = new.strip()
    if not new or new == old:
        return "Escribe un nombre distinto."
    df = load_csv(table)
    names = set(df[name_col].tolist()) if df is not None else set()
    if old not in names:
        return f"'{old}' no existe."
    if new in names:
        return f"'{new}' ya existe — usa **Fusionar** para unirlos, no renombrar."

    df = df.copy()
    df.loc[df[name_col] == old, name_col] = new
    if "similar_a" in df.columns:                       # keep matcher edges consistent
        df.loc[df["similar_a"] == old, "similar_a"] = new
    save_csv(table, df)

    # If `old` is a record the user created this session, this is just correcting the
    # new record's name — not a catalog rename (there's no DB row to rename). Don't log it.
    is_new = old in decisions.get("new_records", [])
    _apply_rename(decisions, old, new, log=not is_new)  # renames log / deleted / approved / pairs
    _rename_in_phase2(decisions, old, new)              # merges / manual_links / new_records
    for cache in (load_csv, get_pairs, table_pairs, table_clusters, usage_lookup):
        cache.clear()
    return ""


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
    lk = merge_lookup(decisions)
    def _passes(pair) -> bool:
        if filt == "Solo pendientes":
            return not pair_decided(pair, decisions, lk)  # merge-aware
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
# Clusters tab  (interactive collapse — Phase 2)
# ---------------------------------------------------------------------------

STATUS_CHIP = {
    "resuelto":  "✅ Resuelto",
    "pendiente": "🕓 Pendiente",
    "conflicto": "⚠️ Conflicto",
}


def _edge_evidence(cluster: dict):
    with st.expander(f"🔗 Enlaces internos ({len(cluster['edges'])})"):
        erows = [{
            "A":           e["a"],
            "B":           e["b"],
            "Similitud %": e["pct"],
            "Tipo":        e["flag"].replace("_", " ").title(),
            "Puente":      "🌉 sí" if frozenset((e["a"], e["b"])) in cluster["bridges"] else "",
        } for e in cluster["edges"]]
        st.dataframe(pd.DataFrame(erows), use_container_width=True, hide_index=True)


def render_clusters(table: str, df: pd.DataFrame, name_col: str):
    decisions = load_decisions(table)
    usage     = usage_lookup(df, name_col)
    clusters  = table_clusters(table, cut_keys_of(decisions), manual_links_of(decisions))

    if not clusters:
        st.info("No hay grupos de duplicados en este catálogo.")
        return

    lk     = merge_lookup(decisions)
    recons = [reconcile_cluster(c, decisions) for c in clusters]
    warns  = [over_merge_warning(c) for c in clusters]
    collap = [cluster_collapsed(c, lk) for c in clusters]

    n_multi     = sum(1 for c in clusters if len(c["members"]) >= 3)
    n_collapsed = sum(1 for c in collap if c)
    n_con       = sum(1 for r, cc in zip(recons, collap) if not cc and r["status"] == "conflicto")
    n_warn      = sum(1 for w, cc in zip(warns, collap) if not cc and w)

    st.caption(
        f"**{len(clusters)} grupos**  •  {n_multi} con 3+ miembros  •  "
        f"✅ {n_collapsed} colapsados  •  ⚠️ {n_con} conflictos  •  "
        f"🚩 {n_warn} posible sobre-agrupación"
    )
    st.caption(
        "Elige el registro a **conservar** (👑) y marca el resto como **Fusionar** "
        "(se elimina y se cuenta como el sobreviviente) o **Separar** (no es duplicado). "
        "Nada se borra del CSV — las decisiones quedan registradas y son reversibles."
    )

    filt = st.segmented_control(
        "Mostrar",
        ["Todos", "Pendientes", "Conflictos", "🚩 Sobre-agrupación", "✅ Colapsados"],
        default="Todos",
        key=f"cluster_filt_{table}",
    )

    has_sci   = "nombre_cientifico" in df.columns
    geo_cols  = [c for c in ["region", "zona", "area"] if c in df.columns and c != name_col]
    dedup     = df.drop_duplicates(subset=[name_col]).set_index(name_col)
    sci_lk    = dedup["nombre_cientifico"].to_dict() if has_sci else {}
    geo_lk    = {c: dedup[c].to_dict() for c in geo_cols}
    all_names   = [n for n in dedup.index.tolist() if n]   # catalog records for manual add
    new_records = set(decisions.get("new_records", []))    # user-created records (default survivor)
    # columns a user can fill on a brand-new record (everything but the name + matcher internals)
    field_cols  = [c for c in df.columns
                   if c != name_col and c not in {"flag_tipo", "similar_a", "similitud_pct"}]

    def _passes(recon, warn, collapsed) -> bool:
        if filt == "✅ Colapsados":       return bool(collapsed)
        if filt == "Pendientes":          return not collapsed and recon["status"] == "pendiente"
        if filt == "Conflictos":          return not collapsed and recon["status"] == "conflicto"
        if filt == "🚩 Sobre-agrupación": return not collapsed and bool(warn)
        return True  # Todos

    visible = [t for t in zip(clusters, recons, warns, collap) if _passes(t[1], t[2], t[3])]
    if not visible:
        st.success("✅ No hay grupos que coincidan con este filtro.")
        return

    PAGE_SIZE = 12   # each card has an editable table; keep the page light
    n_pages   = (len(visible) + PAGE_SIZE - 1) // PAGE_SIZE
    page_key  = f"cluster_page_{table}"
    if st.session_state.get(page_key, 1) > n_pages:
        st.session_state[page_key] = n_pages
    page = st.number_input(
        f"Página (1–{n_pages})", min_value=1, max_value=n_pages, step=1, key=page_key
    ) if n_pages > 1 else 1

    start = (page - 1) * PAGE_SIZE
    page_clusters = visible[start:start + PAGE_SIZE]
    st.caption(f"Mostrando {start + 1}–{start + len(page_clusters)} de {len(visible)} grupos")

    for cluster, recon, warn, collapsed in page_clusters:
        members = cluster["members"]
        cid     = "|".join(members)

        # ---- already collapsed: show summary + reopen ----
        if collapsed:
            absorbed = [m for m in members if m != collapsed]
            with st.container(border=True):
                st.markdown(f"**Grupo de {len(members)}**  —  ✅ **Colapsado**")
                st.success(
                    f"👑 Se conserva **{collapsed}**  ·  🗑 {len(absorbed)} fusionados: "
                    + ", ".join(absorbed)
                )
                if st.button("↩️ Reabrir grupo", key=f"reopen_{table}_{cid}"):
                    reopen_cluster(decisions, cluster, collapsed)
                    save_decisions(table, decisions)
                    st.rerun()
            continue

        # ---- actionable cluster ----
        survivor_default = cluster_survivor_default(cluster, recon, usage, new_records)
        with st.container(border=True):
            head = f"**Grupo de {len(members)}**  —  {STATUS_CHIP.get(recon['status'], recon['status'])}"
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

            rows = []
            for m in members:
                row = {"Registro": m, "Uso": usage.get(m, 0)}
                if has_sci:
                    row["Nombre científico"] = sci_lk.get(m, "")
                for c in geo_cols:
                    row[c] = geo_lk[c].get(m, "")
                row["Acción"] = ACT_KEEP if m == survivor_default else ACT_MERGE
                rows.append(row)

            colcfg = {
                "Registro": st.column_config.TextColumn("Registro", disabled=True),
                "Uso":      st.column_config.NumberColumn("Uso", disabled=True),
                "Acción":   st.column_config.SelectboxColumn(
                    "Acción", options=ACTION_OPTS, required=True, width="medium"
                ),
            }
            if has_sci:
                colcfg["Nombre científico"] = st.column_config.TextColumn("Nombre científico", disabled=True)
            for c in geo_cols:
                colcfg[c] = st.column_config.TextColumn(c, disabled=True)

            edited = st.data_editor(
                pd.DataFrame(rows),
                column_config=colcfg,
                hide_index=True,
                use_container_width=True,
                key=f"act_{table}_{cid}",
            )
            actions = dict(zip(edited["Registro"], edited["Acción"]))
            keepers = [m for m, a in actions.items() if a == ACT_KEEP]

            c1, c2, _ = st.columns([2, 2, 3])
            if c1.button("✅ Colapsar grupo", key=f"col_{table}_{cid}", use_container_width=True):
                if len(keepers) != 1:
                    st.warning("Marca **exactamente un** registro como 👑 Conservar.")
                else:
                    surv = keepers[0]
                    apply_collapse(decisions, cluster, surv,
                                   {m: a for m, a in actions.items() if m != surv})
                    save_decisions(table, decisions)
                    st.rerun()
            if c2.button("✂️ Separar todos", key=f"sep_{table}_{cid}", use_container_width=True,
                         help="Marca todo el grupo como registros distintos (no duplicados)"):
                apply_separate_all(decisions, cluster)
                save_decisions(table, decisions)
                st.rerun()

            # ---- membership actions: one toggle row + a single panel (kept light: the
            # heavy selectbox/editor only renders for the group being edited) ----
            panel_key = f"panel_{table}_{cid}"
            mode = st.session_state.get(panel_key, "")
            tb1, tb2, tb3 = st.columns(3)
            if tb1.button("➕ Agregar existente", key=f"pbadd_{table}_{cid}", use_container_width=True):
                st.session_state[panel_key] = "" if mode == "add" else "add"
                st.rerun()
            if tb2.button("✨ Crear nuevo", key=f"pbnew_{table}_{cid}", use_container_width=True):
                st.session_state[panel_key] = "" if mode == "new" else "new"
                st.rerun()
            if tb3.button("✏️ Renombrar", key=f"pbren_{table}_{cid}", use_container_width=True):
                st.session_state[panel_key] = "" if mode == "rename" else "rename"
                st.rerun()

            if mode == "add":
                pick = st.selectbox(
                    "Registro existente a agregar (no fue detectado automáticamente)",
                    [n for n in all_names if n not in set(members)],
                    index=None, placeholder="Busca un registro del catálogo…",
                    key=f"addsel_{table}_{cid}",
                )
                if st.button("➕ Agregar al grupo", key=f"addok_{table}_{cid}",
                             use_container_width=True, disabled=not pick):
                    add_manual_link(decisions, survivor_default, pick)
                    save_decisions(table, decisions)
                    st.session_state[panel_key] = ""
                    st.rerun()

            elif mode == "new":
                newname = st.text_input("Nombre del nuevo registro",
                                        key=f"nn_{table}_{cid}").strip()
                fields = {}
                if field_cols:
                    st.caption("Completa los demás campos del registro (opcional):")
                    ed = st.data_editor(
                        pd.DataFrame([{c: "" for c in field_cols}]),
                        hide_index=True, use_container_width=True, key=f"nf_{table}_{cid}",
                    )
                    fields = {c: str(ed.iloc[0][c]) for c in field_cols}
                if st.button("✨ Crear y agregar", key=f"nok_{table}_{cid}",
                             use_container_width=True, disabled=not newname):
                    if newname in set(all_names):
                        st.warning(f"'{newname}' ya existe — usa **Agregar existente**.")
                    elif create_new_record(table, newname, name_col, fields):
                        add_manual_link(decisions, survivor_default, newname)
                        nr = decisions.setdefault("new_records", [])
                        if newname not in nr:
                            nr.append(newname)
                        save_decisions(table, decisions)
                        st.session_state[panel_key] = ""
                        st.rerun()

            elif mode == "rename":
                old = st.selectbox(
                    "Registro a renombrar", members, index=None,
                    placeholder="Elige el registro con el nombre incorrecto…",
                    key=f"rensel_{table}_{cid}",
                )
                corrected = st.text_input("Nombre correcto", key=f"rennew_{table}_{cid}").strip()
                if st.button("✏️ Aplicar nombre", key=f"renok_{table}_{cid}",
                             use_container_width=True, disabled=not (old and corrected)):
                    err = rename_record(table, old, corrected, name_col, decisions)
                    if err:
                        st.warning(err)
                    else:
                        # Do NOT add `corrected` to new_records — it's a rename TARGET,
                        # not a brand-new row. Doing so made the importer insert it
                        # (Phase 0) AND rename another row onto it (Phase 1) → unique-key
                        # collision. rename_record already records the rename.
                        save_decisions(table, decisions)
                        st.session_state[panel_key] = ""
                        st.rerun()

            _edge_evidence(cluster)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(
        page_title="Consola de monitoreo",
        page_icon="🐟",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    from console_theme import apply_theme
    apply_theme()
    from console_ui import show_flash
    show_flash()

    # Login gate (ADMINISTRADOR → all modes, ANALISTA → export only).
    from console_auth import require_login, logout_button
    rol, nombre = require_login()
    st.sidebar.caption(f"👤 {nombre} · {rol}")
    logout_button()
    st.sidebar.divider()

    # Top-level console mode (gated by role) — grouped button nav + home screen.
    from home import render_sidebar_nav, render_home
    mode = render_sidebar_nav(rol)
    st.sidebar.divider()
    if mode == "inicio":
        render_home(rol)
        return
    if mode == "formularios":
        from form_builder import render_form_builder
        render_form_builder()
        return
    if mode == "propuestas":
        from proposals_review import render_proposal_queue
        render_proposal_queue()
        return
    if mode == "editar":
        from catalog_admin import render_catalog_admin
        render_catalog_admin()
        return
    if mode == "listas":
        from lista_import import render_lista_import
        render_lista_import()
        return
    if mode == "usuarios":
        from users_admin import render_users_admin
        render_users_admin()
        return
    if mode == "exportar":
        from export_data import render_export
        render_export()
        return

    # mode == "catalogos" — catalog dedup review (the original app).
    table    = sidebar()
    df       = load_csv(table)
    if df is None or df.empty:
        st.error(f"No se pudo cargar {table}.csv")
        return

    name_col    = NAME_COLS.get(table, df.columns[0])
    decisions   = load_decisions(table)
    pairs       = table_pairs(table)
    done, total = progress(pairs, decisions)
    clusters    = table_clusters(table, cut_keys_of(decisions), manual_links_of(decisions))

    from console_ui import page_header
    page_header(
        f"🔎 Duplicados — {TABLE_LABELS.get(table, table)}",
        "Limpia el catálogo: decide si dos nombres parecidos son el mismo registro.",
        help_md=(
            "El sistema marcó pares de nombres que se parecen. Para cada par decide:\n\n"
            "1. **Mantener uno** — son lo mismo; se conserva el bien escrito.\n"
            "2. **Ambos son válidos** — son registros distintos.\n"
            "3. **Decidir después** — lo dejas pendiente.\n\n"
            "En **🧬 Grupos** puedes revisar familias de nombres parecidos y fusionarlas "
            "de una vez. Las decisiones se guardan solas; puedes salir y continuar luego."
        ),
    )
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
