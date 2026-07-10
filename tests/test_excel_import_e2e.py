"""Dev-only e2e: build an in-memory .xlsx, drive parse_rows -> group_faenas ->
apply_mapping(auto) -> commit_batch, assert faenas+capturas created and a re-run skips them.
Guarded DEV DSN; cleans up everything it created."""
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
st.session_state = {"auth_nombre": "ZZ Import E2E"}
from form_builder import _q, _exec                      # noqa: E402
import import_formats as F                              # noqa: E402
import import_writer as IW                              # noqa: E402
from excel_import import apply_mapping                  # noqa: E402

TAG = "ZZE" + uuid.uuid4().hex[:6]
spec = F.FORMATS["MASIVOS_LEGACY"]
headers = ["Dia ","Mes ","Año","Comunidad/ Sitio de arribo","Lugar/ Sitio de pesca","Pescador",
           "Embarcacion","Tecnico","Nombre comun","Nombre cientifico","Captura (kg)",
           "Horas de pesca (h/min)"]

def row(comun, cientifico, kg):
    return (13, 8, 2009, f"{TAG} Comunidad", f"{TAG} Sitio", f"{TAG} Pescador", "NA",
            f"{TAG} Tecnico", comun, cientifico, kg, 3)

data_rows = [row("Cochito", "Balistes polylepis", 50), row("Mojarra", "Diapterus peruvianus", 6)]
rows = F.parse_rows(headers, data_rows)
drafts = F.group_faenas(rows, spec)

def cleanup():
    ids=[r["id"] for r in _q("SELECT f.id::text AS id FROM faena f "
         "JOIN cat_sitio_pesca s ON s.id=f.sitio_pesca_id WHERE s.nombre=%s",(f"{TAG} Sitio",))]
    for t in ("captura","carnada","interaccion_etp","gasto","faena_arte"):
        _exec(f"DELETE FROM {t} WHERE faena_id=ANY(%s::uuid[])", (ids or [None],))
    _exec("DELETE FROM cambio_catalogo WHERE registro_id=ANY(%s::uuid[])", (ids or [None],))
    _exec("DELETE FROM faena WHERE id=ANY(%s::uuid[])", (ids or [None],))
    for c,val in (("cat_comunidad",f"{TAG} Comunidad"),("cat_sitio_pesca",f"{TAG} Sitio"),
                  ("cat_pescador",f"{TAG} Pescador"),("cat_tecnico",f"{TAG} Tecnico")):
        _exec(f"DELETE FROM {c} WHERE nombre=%s",(val,))
    _exec("DELETE FROM cat_especie WHERE nombre_comun IN ('Cochito','Mojarra') "
          "AND nombre_cientifico IN ('Balistes polylepis','Diapterus peruvianus') "
          "AND NOT EXISTS (SELECT 1 FROM captura c WHERE c.especie_id=cat_especie.id)")

try:
    cleanup()
    resolved = apply_mapping(spec, drafts, {})
    rep = IW.commit_batch(spec, resolved)
    assert rep["faenas_nuevas"] == 1 and rep["capturas"] == 2, rep
    fa = _q("SELECT legacy_id FROM faena f JOIN cat_sitio_pesca s ON s.id=f.sitio_pesca_id "
            "WHERE s.nombre=%s", (f"{TAG} Sitio",))
    assert fa and fa[0]["legacy_id"].startswith(spec.codigo + ":")
    # re-run with the same data → skipped as duplicate
    drafts2 = F.group_faenas(F.parse_rows(headers, [row("Cochito", "Balistes polylepis", 50)]), spec)
    resolved2 = apply_mapping(spec, drafts2, {})
    rep2 = IW.commit_batch(spec, resolved2)
    assert rep2["faenas_nuevas"] == 0 and rep2["ya_existen"] == 1, rep2
    print("TODOS LOS CHECKS PASAN")
finally:
    cleanup()
