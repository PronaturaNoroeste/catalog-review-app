"""Smoke: importar mode gating + wizard skeleton renders."""
import pathlib, sys
BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from home import modes_for                       # noqa: E402

assert "importar" in modes_for("ADMINISTRADOR")
assert "importar" not in modes_for("ANALISTA")

import import_formats as F                              # noqa: E402
from excel_import import build_mapping_model            # noqa: E402
spec = F.FORMATS["MASIVOS_LEGACY"]
rows = F.parse_rows(["Dia ","Mes ","Año","Comunidad/ Sitio de arribo","Lugar/ Sitio de pesca",
                     "Pescador","Embarcacion","Tecnico","Nombre comun","Nombre cientifico","Captura (kg)"],
                    [(1,1,2020,"CoA","SiA","PeA","NA","TeA","Cochito","Balistes","5")])
model = build_mapping_model(rows, spec)
# every catalog-bound distinct value appears, keyed by catalog
assert ("cat_sitio_pesca","SiA") in model["values"]
assert ("cat_comunidad","CoA") in model["values"]
assert model["especies"] == [("Cochito","Balistes")]
print("TODOS LOS CHECKS PASAN")
