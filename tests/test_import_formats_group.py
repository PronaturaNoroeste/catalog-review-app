import pathlib, sys
BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
import import_formats as F                              # noqa: E402

spec = F.FORMATS["MASIVOS_LEGACY"]
def row(comun, kg, **kw):
    base = {"Dia": 13, "Mes": 8, "Año": 2009, "Comunidad/ Sitio de arribo": "Punta Coyote",
            "Lugar/ Sitio de pesca": "El Mechudo", "Pescador": "Playa Camarón I",
            "Embarcacion": "NA", "Tecnico": "NA", "Nombre comun": comun, "Captura (kg)": kg}
    base.update(kw); return base

rows = [row("Cochito", 50), row("Mojarra", 6), row("Burro", "NA")]   # 3rd has no kg
drafts = F.group_faenas(rows, spec)
assert len(drafts) == 1                              # one trip
d = drafts[0]
assert len(d.catches) == 2                           # kg-less catch dropped
assert any("Captura (kg)" in e or "kg" in e for e in d.errors)   # and reported
assert d.faena_raw["tiempo_efectivo_pesca_h"] in (0, 0.0)        # NA hours → 0 w/ warning
assert any("tiempo" in e.lower() for e in d.errors)

# arte: no arte columns present in source rows -> no faena_arte data emitted
assert d.children_raw["arte"] == {}

# boat-fallback: same day/site, NA pescador, two boats → two faenas
r2 = [row("X", 1, Pescador="NA", Embarcacion="Albatros II"),
      row("Y", 2, Pescador="NA", Embarcacion="Naydeli")]
assert len(F.group_faenas(r2, spec)) == 2

# unparseable date → faena flagged, no catches emitted for insert
bad = F.group_faenas([row("Z", 1, Dia="NA")], spec)
assert bad and bad[0].errors and bad[0].key is None
print("TODOS LOS CHECKS PASAN")
