"""Dev-only e2e for the Monitoreo pesquero (biológico) format: parse_rows -> group_faenas ->
apply_mapping(auto) -> commit_batch, assert a faena + its mediciones are created (with the
MONITOREO_LEGACY formato auto-created), and a re-run skips the faena as a duplicate.
Guarded DEV DSN; cleans up everything it created."""
import os, pathlib, sys, uuid
BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
DEV_REF = "pxxqumcvkoltbjubyvod"
for envf in (BASE.parent/"supabase-backend"/".env", BASE.parent/"Planning"/"supabase"/".env"):
    if envf.exists():
        for line in envf.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("DATABASE_URL="):
                os.environ["DATABASE_URL"] = line.split("=", 1)[1].strip().strip("'").strip('"')
assert DEV_REF in os.environ.get("DATABASE_URL", ""), "solo DEV"
import streamlit as st                                  # noqa: E402
st.session_state = {"auth_nombre": "ZZ Monitoreo E2E"}
from form_builder import _q, _exec                      # noqa: E402
import import_formats as F                              # noqa: E402
import import_writer as IW                              # noqa: E402
from excel_import import apply_mapping                  # noqa: E402

TAG = "ZZM" + uuid.uuid4().hex[:6]
spec = F.FORMATS["MONITOREO_LEGACY"]
headers = ["Dia", "Mes ", "Año", "Lugar de arribo/ campo pesquero", "Sitio de Pesca ", "Pescador",
           "Embarcacion", "Técnico", "Arte de pesca", "Nombre comun", "Nombre cientifico",
           "Longitud total (cm)", "Peso Entero(kg)"]


def row(comun, cient, longitud, peso):
    return (23, 4, 2009, f"{TAG} Comunidad", f"{TAG} Sitio", "NA", "NA", f"{TAG} Tecnico",
            "Chinchorro", comun, cient, longitud, peso)


data_rows = [row("Cochito", "Balistes polylepis", 31, 0.5),   # peso 0.5 kg -> 500 g, ENTERO
             row("Cochito", "Balistes polylepis", 32, "NA"),  # no peso -> peso_gr NULL, NA
             row("Cochito", "Balistes polylepis", "NA", "NA")]  # no longitud -> skipped
rows = F.parse_rows(headers, data_rows)
drafts = F.group_faenas(rows, spec)


def cleanup():
    ids = [r["id"] for r in _q("SELECT f.id::text AS id FROM faena f "
           "JOIN cat_sitio_pesca s ON s.id=f.sitio_pesca_id WHERE s.nombre=%s", (f"{TAG} Sitio",))]
    for t in ("medicion", "captura", "faena_arte", "carnada", "interaccion_etp", "gasto"):
        _exec(f"DELETE FROM {t} WHERE faena_id=ANY(%s::uuid[])", (ids or [None],))
    _exec("DELETE FROM cambio_catalogo WHERE registro_id=ANY(%s::uuid[])", (ids or [None],))
    _exec("DELETE FROM faena WHERE id=ANY(%s::uuid[])", (ids or [None],))
    for c, val in (("cat_comunidad", f"{TAG} Comunidad"), ("cat_sitio_pesca", f"{TAG} Sitio"),
                   ("cat_tecnico", f"{TAG} Tecnico")):
        _exec(f"DELETE FROM {c} WHERE nombre=%s", (val,))
    _exec("DELETE FROM cat_especie WHERE nombre_comun='Cochito' AND nombre_cientifico='Balistes polylepis' "
          "AND NOT EXISTS (SELECT 1 FROM medicion m WHERE m.especie_id=cat_especie.id) "
          "AND NOT EXISTS (SELECT 1 FROM captura c WHERE c.especie_id=cat_especie.id)")


try:
    cleanup()
    resolved = apply_mapping(spec, drafts, {})
    rep = IW.commit_batch(spec, resolved)
    assert rep["faenas_nuevas"] == 1, rep
    assert rep["mediciones"] == 2, rep                 # 3rd row (no longitud) dropped
    fa = _q("SELECT f.id::text AS id, f.legacy_id, f.tipo_registro FROM faena f "
            "JOIN cat_sitio_pesca s ON s.id=f.sitio_pesca_id WHERE s.nombre=%s", (f"{TAG} Sitio",))
    assert fa and fa[0]["legacy_id"].startswith("MONITOREO_LEGACY:"), fa
    assert fa[0]["tipo_registro"] == "MASIVO", fa
    meds = _q("SELECT longitud_total_cm, peso_gr, procesado::text AS procesado FROM medicion "
              "WHERE faena_id=%s ORDER BY longitud_total_cm", (fa[0]["id"],))
    assert len(meds) == 2, meds
    assert float(meds[0]["longitud_total_cm"]) == 31 and float(meds[0]["peso_gr"]) == 500, meds
    assert meds[0]["procesado"] == "ENTERO", meds
    assert meds[1]["peso_gr"] is None and meds[1]["procesado"] == "NA", meds
    # formato row was auto-created
    assert _q("SELECT 1 AS ok FROM cat_formato_origen WHERE codigo='MONITOREO_LEGACY'"), "formato faltante"
    # re-run same data → faena skipped as duplicate
    drafts2 = F.group_faenas(F.parse_rows(headers, [row("Cochito", "Balistes polylepis", 31, 0.5)]), spec)
    rep2 = IW.commit_batch(spec, apply_mapping(spec, drafts2, {}))
    assert rep2["faenas_nuevas"] == 0 and rep2["ya_existen"] == 1, rep2
    print("TODOS LOS CHECKS PASAN")
finally:
    cleanup()
