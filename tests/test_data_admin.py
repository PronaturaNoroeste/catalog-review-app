"""Dev-only round-trip for the data-table editor (data_admin.py).

Refuses to run against anything but DEV. Verifies:
  * nav gating — `registros` is ADMINISTRADOR-only;
  * save_row updates a data row (captura) and writes an attributed audit row
    (usuario_id + «por») — attribution comes from form_builder._log reading the
    Streamlit session, which we fake here;
  * dependents_detail blocks deleting a faena while a captura references it;
  * delete_row removes a child row.

Creates a throwaway faena + captura (reusing existing catalog ids) and cleans up
everything it wrote, including its own audit rows. Run from the repo root:

    PYTHONIOENCODING=utf-8 python tests/test_data_admin.py
"""
import os
import pathlib
import sys
import uuid
from decimal import Decimal

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

DEV_REF = "pxxqumcvkoltbjubyvod"
CANDS = [BASE.parent / "supabase-backend" / ".env",
         BASE.parent / "Planning" / "supabase" / ".env"]
dsn = None
for envf in CANDS:
    if envf.exists():
        for line in envf.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("DATABASE_URL="):
                dsn = line.strip().split("=", 1)[1].strip().strip("'").strip('"')
                break
    if dsn:
        break
assert dsn, f"pon el DSN de DEV en una de: {[str(c) for c in CANDS]}"
assert DEV_REF in dsn, "el DSN no es el proyecto DEV — me niego a correr contra otra base"
os.environ["DATABASE_URL"] = dsn

# --- fake a logged-in admin so _log attributes the change ---------------------
ADMIN_UID = str(uuid.uuid4())
import streamlit as st                       # noqa: E402
st.session_state = {"auth_nombre": "ZZ Test Admin", "auth_uid": ADMIN_UID}

from form_builder import _q, _exec           # noqa: E402
from proposals_review import dependents_detail  # noqa: E402
from data_admin import data_meta             # noqa: E402
from catalog_admin import save_row, delete_row, load_row  # noqa: E402
from home import modes_for                   # noqa: E402

FID = str(uuid.uuid4())
CID = str(uuid.uuid4())


def _one(sql):
    r = _q(sql)
    assert r, f"la base DEV no tiene datos para: {sql}"
    return r[0]["id"]


def cleanup():
    _exec("DELETE FROM cambio_catalogo WHERE registro_id IN (%s,%s)", (FID, CID))
    _exec("DELETE FROM captura WHERE id=%s", (CID,))
    _exec("DELETE FROM faena WHERE id=%s", (FID,))


# 0. nav gating
assert "registros" in modes_for("ADMINISTRADOR"), "registros debe estar para ADMINISTRADOR"
assert "registros" not in modes_for("ANALISTA"), "registros NO debe estar para ANALISTA"

cleanup()
formato = _one("SELECT id::text AS id FROM cat_formato_origen LIMIT 1")
comunidad = _one("SELECT id::text AS id FROM cat_comunidad LIMIT 1")
sitio = _one("SELECT id::text AS id FROM cat_sitio_pesca LIMIT 1")
capitan = _one("SELECT id::text AS id FROM cat_pescador LIMIT 1")
tecnico = _one("SELECT id::text AS id FROM cat_tecnico LIMIT 1")
especie = _one("SELECT id::text AS id FROM cat_especie LIMIT 1")

try:
    _exec("""INSERT INTO faena (id, formato_origen_id, fecha, comunidad_id, sitio_pesca_id,
                                capitan_id, tecnico_id, tiempo_efectivo_pesca_h)
             VALUES (%s,%s,CURRENT_DATE,%s,%s,%s,%s,%s)""",
          (FID, formato, comunidad, sitio, capitan, tecnico, Decimal("3.0")))
    _exec("INSERT INTO captura (id, faena_id, especie_id, captura_kg) VALUES (%s,%s,%s,%s)",
          (CID, FID, especie, Decimal("10.0")))

    # 1. save_row updates a data row (change only captura_kg) + attributed audit
    meta = data_meta("captura")
    cur = load_row("captura", CID)
    values = {m["name"]: cur.get(m["name"]) for m in meta if m["kind"] != "ro"}
    values["captura_kg"] = Decimal("12.5")
    save_row("captura", meta, CID, values)
    assert _q("SELECT captura_kg FROM captura WHERE id=%s", (CID,))[0]["captura_kg"] == Decimal("12.5")

    audit = _q("""SELECT accion, detalle, usuario_id::text AS uid FROM cambio_catalogo
                  WHERE tabla='captura' AND registro_id=%s ORDER BY id DESC LIMIT 1""", (CID,))[0]
    assert audit["accion"] == "editar", audit
    assert audit["uid"] == ADMIN_UID, f"usuario_id no atribuido: {audit}"
    assert audit["detalle"].get("por") == "ZZ Test Admin", f"«por» no atribuido: {audit}"
    assert audit["detalle"].get("campo") == "captura_kg", audit

    # 2. dependents_detail blocks deleting the faena while the captura references it
    dep = dependents_detail("faena", FID)
    assert ("captura", 1) in dep, f"la faena debería estar bloqueada por su captura: {dep}"

    # 3. delete_row removes the child; faena is then free
    delete_row("captura", CID, "captura de prueba")
    assert not _q("SELECT 1 FROM captura WHERE id=%s", (CID,)), "la captura no se eliminó"
    assert dependents_detail("faena", FID) == [], "la faena no debería tener dependientes ya"

    print("TODOS LOS CHECKS PASAN")
finally:
    cleanup()
