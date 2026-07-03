"""
Proposal review queue (M2 step 3) — the admin side of offline catalog proposals.

Field técnicos propose new catalog entries from the capture app; they sync as
*pending* catalog rows (estado='pendiente', es_aprobado=false). Here an admin
approves / rejects / merges them. Merge reuses the schema's FK graph to repoint
every faena reference from the proposed row to the chosen survivor (the "reuse
the merge infra" idea from OD-15, applied to live DB rows).

Reuses the form_builder DB layer (same DATABASE_URL). Writes a cambio_catalogo
audit row for every action.
"""
from __future__ import annotations

import streamlit as st

from form_builder import _q, _exec, _log   # shared connection + query/write/audit helpers


# Name column per catalog (cat_especie proposals arrived with migration 0013 and
# its name lives in nombre_comun, not nombre). Kept local: catalog_admin imports
# from this module, so importing its map back would create a cycle.
NAME_COL = {"cat_especie": "nombre_comun", "cat_formato_origen": "codigo"}


def _name_col(tabla: str) -> str:
    return NAME_COL.get(tabla, "nombre")


@st.cache_data(ttl=300, show_spinner=False)
def proposable_tables() -> list[str]:
    return [r["tabla"] for r in
            _q("SELECT tabla FROM catalogo_config WHERE permite_propuestas ORDER BY tabla")]


@st.cache_data(ttl=300, show_spinner=False)
def referencing_columns(tabla: str) -> list[tuple[str, str]]:
    """(table, column) pairs whose FK points at <tabla>.id — used for merge + dependents."""
    rows = _q("""
        SELECT tc.table_name AS t, kcu.column_name AS c
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema
        WHERE tc.constraint_type='FOREIGN KEY' AND tc.table_schema='public'
          AND ccu.table_name=%s AND ccu.column_name='id'
    """, (tabla,))
    return [(r["t"], r["c"]) for r in rows]


def dependents_detail(tabla: str, registro_id: str) -> list[tuple[str, int]]:
    """(referencing table, count) for every table that points at this row."""
    out = []
    for t, c in referencing_columns(tabla):
        n = _q(f'SELECT count(*) AS n FROM public."{t}" WHERE "{c}"=%s', (registro_id,))[0]["n"]
        if n:
            out.append((t, n))
    return out


def dependents(tabla: str, registro_id: str) -> int:
    return sum(n for _, n in dependents_detail(tabla, registro_id))


def pending_proposals() -> list[dict]:
    out = []
    for t in proposable_tables():
        nc = _name_col(t)
        for r in _q(f"""SELECT id::text AS id, {nc} AS nombre, propuesto_por::text AS por,
                               propuesto_at AS at
                        FROM public."{t}" WHERE estado='pendiente'
                        ORDER BY propuesto_at NULLS LAST"""):
            r["tabla"] = t
            out.append(r)
    return out


def approved_candidates(tabla: str, q: str) -> list[dict]:
    nc = _name_col(tabla)
    like = f"%{q.strip()}%"
    return _q(f"""SELECT id::text AS id, {nc} AS nombre FROM public."{tabla}"
                  WHERE es_aprobado AND {nc} ILIKE %s ORDER BY {nc} LIMIT 25""", (like,))


# Proposals that can join a curated form list on approval (doc 16 follow-up:
# an approved-but-unlisted species vanishes from the strict tablet picker).
LISTABLE = {"cat_especie": ["especies", "carnada"], "cat_pescador": ["pescadores"]}


# ---- actions ----
def approve(tabla: str, rid: str, nombre: str):
    _exec(f'UPDATE public."{tabla}" SET estado=\'aprobado\', es_aprobado=true WHERE id=%s', (rid,))
    _log(tabla, rid, "aprobar", {"nombre": nombre})


def add_to_lista(formato_id: str, lista: str, tabla: str, rid: str, nombre: str):
    """Insert the approved row into the form's curated list (idempotent)."""
    _exec("""INSERT INTO lista_opcion (formato_origen_id, lista, tabla, registro_id, importancia)
             VALUES (%s,%s,%s,%s,0)
             ON CONFLICT (formato_origen_id, lista, registro_id) DO NOTHING""",
          (formato_id, lista, tabla, rid))
    if tabla == "cat_especie" and lista == "carnada":
        _exec("UPDATE cat_especie SET apta_carnada=true WHERE id=%s", (rid,))
    _log("lista_opcion", rid, "crear",
         {"lista": lista, "formato_origen_id": formato_id, "nombre": nombre, "origen": "propuesta"})


def reject(tabla: str, rid: str, nombre: str):
    _exec(f'UPDATE public."{tabla}" SET estado=\'rechazado\' WHERE id=%s', (rid,))
    _log(tabla, rid, "rechazar", {"nombre": nombre})


def merge(tabla: str, proposed: str, survivor: str, nombre: str):
    """Repoint every FK reference proposed→survivor, then mark the proposal fusionado."""
    for t, c in referencing_columns(tabla):
        _exec(f'UPDATE public."{t}" SET "{c}"=%s WHERE "{c}"=%s', (survivor, proposed))
    _exec(f'UPDATE public."{tabla}" SET estado=\'fusionado\' WHERE id=%s', (proposed,))
    _log(tabla, proposed, "fusionar", {"nombre": nombre, "survivor": survivor})


# =====================================================================
# UI
# =====================================================================
def render_proposal_queue():
    from console_ui import page_header, friendly_error, confirm_button, empty_state, flash
    page_header(
        "📥 Propuestas de campo",
        "Nombres nuevos que los técnicos capturaron en la tableta y esperan tu decisión.",
        help_md=(
            "Cuando un técnico no encuentra un nombre en la lista, lo **propone** desde la "
            "tableta. Aquí decides qué hacer con cada propuesta:\n\n"
            "1. **✅ Aprobar** — el nombre es correcto y nuevo: entra al catálogo.\n"
            "2. **❌ Rechazar** — no debe entrar al catálogo (error o prueba).\n"
            "3. **🔀 Fusionar** — ya existe con otro nombre: los registros de pesca se "
            "mueven a la entrada existente.\n\n"
            "Cada acción queda registrada en la bitácora de cambios."
        ),
    )

    try:
        props = pending_proposals()
    except Exception as e:  # noqa: BLE001
        st.error(f"No se pudieron cargar las propuestas: {e}")
        st.info("Si el problema es de conexión, configura DATABASE_URL (env o .env). "
                "Ver Planning/supabase/TODO.md.")
        return

    st.metric("Propuestas pendientes", len(props))
    if not props:
        empty_state("No hay propuestas pendientes. ¡Todo revisado!", "🎉")
        return

    labels = {"cat_pescador": "Pescador/Capitán", "cat_embarcacion": "Embarcación",
              "cat_sitio_pesca": "Sitio de pesca", "cat_especie": "Especie"}

    for p in props:
        rid, tabla, nombre = p["id"], p["tabla"], p["nombre"]
        dep = dependents(tabla, rid)
        with st.container(border=True):
            top = st.columns([4, 2, 2])
            top[0].markdown(f"### {nombre}")
            top[0].caption(f"{labels.get(tabla, tabla)} · propuesto "
                           f"{p['at'].strftime('%Y-%m-%d') if p['at'] else 's/f'}")
            top[1].metric("Faenas que lo usan", dep)
            top[2].caption(f"sesión: `{(p['por'] or '—')[:8]}`")

            # optional: put the approved entry straight on the form's curated list —
            # a strict picker only shows listed entries, so an approved-but-unlisted
            # name would vanish from the tablet.
            add_l = False
            fsel = lsel = None
            if tabla in LISTABLE:
                from form_builder import formatos_en_uso
                formatos = formatos_en_uso()
                if formatos:
                    lc1, lc2, lc3 = st.columns([3, 2, 2])
                    add_l = lc1.checkbox(
                        "Al aprobar, añadir a la lista del formulario", value=True,
                        key=f"addl_{rid}",
                        help="Si no está en la lista curada, el técnico no la verá en la "
                             "tableta aunque esté aprobada.")
                    fmap = {f["id"]: f["codigo"] for f in formatos}
                    fsel = lc2.selectbox("Formulario", list(fmap), format_func=lambda i: fmap[i],
                                         key=f"addlf_{rid}", disabled=not add_l)
                    listas = LISTABLE[tabla]
                    lsel = lc3.selectbox("Lista", listas, key=f"addll_{rid}",
                                         disabled=not add_l or len(listas) == 1)

            a, r = st.columns(2)
            if a.button("✅ Aprobar", key=f"ap_{rid}", use_container_width=True):
                try:
                    approve(tabla, rid, nombre)
                    if add_l and fsel and lsel:
                        add_to_lista(fsel, lsel, tabla, rid, nombre)
                        flash(f"«{nombre}» aprobada y añadida a la lista «{lsel}».")
                    else:
                        flash(f"«{nombre}» aprobada.")
                    st.rerun()
                except Exception as e:  # noqa: BLE001
                    st.error(friendly_error(e))
            if r.button("❌ Rechazar", key=f"rj_{rid}", use_container_width=True,
                        help="Marca como rechazada. Si hay faenas que la usan, considera fusionar."):
                try:
                    reject(tabla, rid, nombre)
                    flash(f"«{nombre}» rechazada.", "❌")
                    st.rerun()
                except Exception as e:  # noqa: BLE001
                    st.error(friendly_error(e))

            with st.expander("🔀 Fusionar con una entrada existente"):
                q = st.text_input("Buscar entrada aprobada", value=nombre, key=f"q_{rid}")
                cands = approved_candidates(tabla, q) if q.strip() else []
                if not cands:
                    st.caption("Sin coincidencias aprobadas.")
                else:
                    pick = st.selectbox(
                        "Sobrevive (las faenas se repuntan a esta)", [c["id"] for c in cands],
                        format_func=lambda i, m={c["id"]: c["nombre"] for c in cands}: m.get(i, i),
                        key=f"surv_{rid}")
                    detail = dependents_detail(tabla, rid)
                    if detail:
                        st.info("Al fusionar se moverán: " +
                                " · ".join(f"**{n}** registro(s) de `{t}`" for t, n in detail))
                    else:
                        st.caption("Ningún registro usa esta propuesta todavía; la fusión "
                                   "solo la marca como fusionada.")
                    if confirm_button(f"Fusionar «{nombre}» → la seleccionada", key=f"mg_{rid}",
                                      help="La fusión mueve las faenas a la entrada elegida; "
                                           "no se puede deshacer."):
                        try:
                            merge(tabla, rid, pick, nombre)
                            flash("Fusionada: las faenas ahora apuntan a la entrada elegida.", "🔀")
                            st.rerun()
                        except Exception as e:  # noqa: BLE001
                            st.error(friendly_error(e))
