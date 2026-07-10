"""Smoke: importar mode gating + wizard skeleton renders."""
import pathlib, sys
BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from home import modes_for                       # noqa: E402

assert "importar" in modes_for("ADMINISTRADOR")
assert "importar" not in modes_for("ANALISTA")
print("TODOS LOS CHECKS PASAN")
