"""Dev-only round-trip for import_writer: resolve a fixture draft → commit → re-commit skips."""
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
st.session_state = {"auth_nombre": "ZZ Import Writer"}
from form_builder import _q, _exec                      # noqa: E402
import import_formats as F, import_writer as W          # noqa: E402

TAG = "ZZW" + uuid.uuid4().hex[:6]
spec = F.FORMATS["MASIVOS_LEGACY"]
def row(comun, kg):
    return {"Dia":13,"Mes":8,"Año":2009,"Comunidad/ Sitio de arribo":f"{TAG} Comunidad",
            "Lugar/ Sitio de pesca":f"{TAG} Sitio","Pescador":f"{TAG} Pescador","Embarcacion":"NA",
            "Tecnico":f"{TAG} Tecnico","Nombre comun":comun,"Captura (kg)":kg,
            "Horas de pesca (h/min)":3}
drafts = F.group_faenas([row("Cochito",50), row("Mojarra",6)], spec)

def created_faenas():
    return _q("SELECT id::text AS id FROM faena WHERE legacy_id LIKE %s", (f"{spec.codigo}:%",))
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
    _exec("DELETE FROM cat_especie WHERE nombre_comun IN ('Cochito','Mojarra') AND es_aprobado=false "
          "AND NOT EXISTS (SELECT 1 FROM captura c WHERE c.especie_id=cat_especie.id)")
try:
    cleanup()
    resolved = [W.resolve_draft(spec, d) for d in drafts]
    rep = W.commit_batch(spec, resolved)
    assert rep["faenas_nuevas"] == 1 and rep["capturas"] == 2, rep
    fa = _q("SELECT legacy_id, tipo_registro::text AS tr FROM faena f "
            "JOIN cat_sitio_pesca s ON s.id=f.sitio_pesca_id WHERE s.nombre=%s",(f"{TAG} Sitio",))
    assert fa and fa[0]["legacy_id"].startswith(spec.codigo+":") and fa[0]["tr"]=="MASIVO"
    # re-commit → skipped as duplicate
    resolved2 = [W.resolve_draft(spec, d) for d in F.group_faenas([row("Cochito",50)], spec)]
    rep2 = W.commit_batch(spec, resolved2)
    assert rep2["faenas_nuevas"]==0 and rep2["ya_existen"]==1, rep2
    print("TODOS LOS CHECKS PASAN")
finally:
    cleanup()
