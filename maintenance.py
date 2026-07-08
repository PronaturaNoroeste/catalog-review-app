"""
🧹 Datos de prueba — purge test faenas captured during prod testing.

Prod tests are captured under the dedicated «PRUEBAS — no usar en campo» técnico
(the Test / Test_07072026 logins point at it), so test faenas are separable from
real data. This screen lets an admin preview and delete them — plus any single
stray faena by id — without the CLI. Deleting a faena cascades to its children
(captura/medicion/…) via the schema's ON DELETE CASCADE.
"""
from __future__ import annotations

import streamlit as st

from form_builder import _q, _exec, _log

TEST_TECNICO_NOMBRE = "PRUEBAS — no usar en campo"
_CHILD = ["captura", "medicion", "faena_arte", "carnada", "interaccion_etp",
          "gasto", "faena_especie_objetivo", "recurso_ahorro", "aportacion_imss",
          "valor_campo_faena"]


# ---- data layer ----
def _test_tecnico() -> dict | None:
    r = _q("SELECT id::text AS id, nombre FROM cat_tecnico WHERE nombre=%s", (TEST_TECNICO_NOMBRE,))
    return r[0] if r else None


def _faenas_de(tecnico_id: str) -> list[dict]:
    return _q("""SELECT f.id::text AS id, f.fecha, o.codigo AS formato
                 FROM faena f LEFT JOIN cat_formato_origen o ON o.id=f.formato_origen_id
                 WHERE f.tecnico_id=%s ORDER BY f.fecha""", (tecnico_id,))


def _faena_info(fid: str) -> dict | None:
    r = _q("""SELECT f.id::text AS id, f.fecha, t.nombre AS tecnico, o.codigo AS formato
              FROM faena f LEFT JOIN cat_tecnico t ON t.id=f.tecnico_id
              LEFT JOIN cat_formato_origen o ON o.id=f.formato_origen_id
              WHERE f.id=%s""", (fid,))
    return r[0] if r else None


def _child_counts(ids: list[str]) -> dict:
    out = {}
    for tbl in _CHILD:
        n = _q(f"SELECT count(*) AS n FROM {tbl} WHERE faena_id = ANY(%s::uuid[])", (ids,))[0]["n"]
        if n:
            out[tbl] = n
    return out


def _delete_faenas(ids: list[str]):
    _exec("DELETE FROM faena WHERE id = ANY(%s::uuid[])", (ids,))
    for i in ids:
        _log("faena", i, "eliminar", {"origen": "consola/datos_prueba"})


# ---- UI ----
def render_maintenance():
    from console_ui import page_header, friendly_error, empty_state, flash, confirm_button
    page_header(
        "🧹 Datos de prueba",
        "Elimina las faenas capturadas en pruebas de la tableta (no toca datos reales).",
        help_md=(
            "Las pruebas en producción se capturan con las cuentas **Test** / **Test_07072026**, "
            "ligadas al técnico **«PRUEBAS — no usar en campo»**. Aquí puedes:\n"
            "1. **Vaciar** todas las faenas de ese técnico de prueba.\n"
            "2. **Eliminar una faena por su id** (para casos sueltos).\n\n"
            "Al eliminar una faena se borran también sus capturas, mediciones, etc. (en cascada)."
        ),
    )

    # 1) purge all faenas of the dedicated test técnico
    st.subheader("Vaciar faenas de prueba")
    tec = _test_tecnico()
    if not tec:
        st.info("No existe el técnico «PRUEBAS — no usar en campo». Créalo primero "
                "(script `setup-test-tecnico`) y liga las cuentas Test a él.")
    else:
        faenas = _faenas_de(tec["id"])
        if not faenas:
            empty_state("No hay faenas de prueba que eliminar.", "✅")
        else:
            ids = [f["id"] for f in faenas]
            st.caption(f"**{len(faenas)}** faena(s) del técnico de prueba «{tec['nombre']}».")
            with st.expander("Ver faenas y lo que se eliminará"):
                import pandas as pd
                st.dataframe(pd.DataFrame(faenas), hide_index=True, width="stretch")
                cc = _child_counts(ids)
                st.caption("Hijos en cascada: "
                           + (", ".join(f"{k}={v}" for k, v in cc.items()) or "ninguno"))
            if confirm_button(f"🗑️ Eliminar {len(faenas)} faena(s) de prueba", key="mant_purge",
                              help="Borra todas las faenas del técnico de prueba y sus hijos."):
                try:
                    _delete_faenas(ids)
                    flash(f"Eliminadas {len(faenas)} faena(s) de prueba.", "🧹")
                    st.rerun()
                except Exception as e:  # noqa: BLE001
                    st.error(friendly_error(e))

    # 2) delete a single faena by id
    st.divider()
    st.subheader("Eliminar una faena por id")
    fid = st.text_input("ID de la faena (UUID)", key="mant_fid", placeholder="e28f4b3a-…")
    if fid.strip():
        info = _faena_info(fid.strip())
        if not info:
            st.warning("No se encontró una faena con ese id. (¿Quizás pegaste el id de otra cosa, "
                       "como un técnico?)")
        else:
            cc = _child_counts([info["id"]])
            st.write(f"**{info['id']}** · {info['fecha']} · téc **{info['tecnico']}** · "
                     f"formato {info['formato']}")
            st.caption("Hijos en cascada: "
                       + (", ".join(f"{k}={v}" for k, v in cc.items()) or "ninguno"))
            if info["tecnico"] != TEST_TECNICO_NOMBRE:
                st.warning("⚠️ Esta faena **no** es del técnico de prueba — revisa bien antes de eliminar.")
            if confirm_button("🗑️ Eliminar esta faena", key="mant_del_one"):
                try:
                    _delete_faenas([info["id"]])
                    flash("Faena eliminada.", "🗑️")
                    st.rerun()
                except Exception as e:  # noqa: BLE001
                    st.error(friendly_error(e))
