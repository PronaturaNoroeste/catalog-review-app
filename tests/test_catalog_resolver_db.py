"""Dev-only: catalog_resolver DB resolve/create/Desconocido/especie. Guarded DSN, cleans up."""
import os, pathlib, sys, uuid
BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
DEV_REF = "pxxqumcvkoltbjubyvod"
for envf in (BASE.parent/"supabase-backend"/".env", BASE.parent/"Planning"/"supabase"/".env"):
    if envf.exists():
        for line in envf.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("DATABASE_URL="):
                os.environ["DATABASE_URL"] = line.split("=",1)[1].strip().strip("'").strip('"')
assert DEV_REF in os.environ.get("DATABASE_URL",""), "solo DEV"
import streamlit as st                                  # noqa: E402
st.session_state = {"auth_nombre": "ZZ Import Test"}    # attribute _log
from form_builder import _q, _exec                      # noqa: E402
import catalog_resolver as R                            # noqa: E402

TAG = uuid.uuid4().hex[:8].upper()
NEW = f"ZZ Sitio {TAG}"
created = []
def cleanup():
    _exec("DELETE FROM cat_sitio_pesca WHERE nombre LIKE %s", (f"ZZ Sitio {TAG}%",))
    _exec("DELETE FROM cat_sitio_pesca WHERE nombre='Desconocido' AND id=ANY(%s::uuid[])", (created or [None],))
    _exec("DELETE FROM cat_especie WHERE nombre_comun LIKE %s", (f"ZZ Esp {TAG}%",))
try:
    # exact match on an existing row
    some = _q("SELECT nombre FROM cat_sitio_pesca WHERE es_aprobado LIMIT 1")
    if some:
        assert R.resolve_exact("cat_sitio_pesca", some[0]["nombre"]) is not None
    # create-or-resolve a brand new value → creates es_aprobado=false
    sid = R.resolve_or_create("cat_sitio_pesca", NEW)
    row = _q("SELECT nombre, es_aprobado FROM cat_sitio_pesca WHERE id=%s", (sid,))[0]
    assert row["nombre"] == NEW and row["es_aprobado"] is False
    assert R.resolve_or_create("cat_sitio_pesca", NEW) == sid          # idempotent
    # desconocido placeholder
    dsc = R.desconocido_id("cat_sitio_pesca"); created.append(dsc)
    assert R.desconocido_id("cat_sitio_pesca") == dsc                  # reused
    # especie pair: same común, different científico → two distinct ids (homonyms)
    a = R.resolve_or_create_especie(f"ZZ Esp {TAG}", "Genus alpha")
    b = R.resolve_or_create_especie(f"ZZ Esp {TAG}", "Genus beta")
    assert a != b
    assert R.resolve_especie(f"ZZ Esp {TAG}", "Genus alpha") == a
    print("TODOS LOS CHECKS PASAN")
finally:
    cleanup()
