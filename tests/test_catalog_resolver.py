"""Pure unit tests for catalog_resolver (no DB)."""
import pathlib, sys
BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from catalog_resolver import normalize, is_na, best_matches   # noqa: E402

assert normalize("  El   Portugués ") == "El Portugués"
assert normalize(None) == ""
assert is_na("NA") and is_na("nd") and is_na("") and is_na("  Pendiente ") and is_na(None)
assert not is_na("El Portugués")

cands = ["El Portugués", "El Mechudo", "La Reyna Cerralvo"]
# exact-ish near match ranks first, above cutoff
top = best_matches(cands, "El Portugues")     # missing accent
assert top and top[0][0] == "El Portugués"
# no reasonable match → empty
assert best_matches(cands, "Zzzzz Nowhere") == []
print("TODOS LOS CHECKS PASAN")
