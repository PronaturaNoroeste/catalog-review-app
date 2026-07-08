"""Dev-only round-trip for the R4 formato-assignment data layer (users_admin).

Locates the DEV DSN (Planning/supabase/.env on Windows, or
../supabase-backend/.env on WSL), refuses to run against anything else, creates
a throwaway formato + usuario, and asserts formato_origen_id round-trips and is
cleared when the role changes away from TECNICO. Audit rows in cambio_catalogo
are left behind by design. Run from the repo root:

    PYTHONIOENCODING=utf-8 python tests/test_users_formato.py
"""
import os
import pathlib
import sys
import uuid

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
os.environ["DATABASE_URL"] = dsn          # form_builder._dsn() prefers the environment

from form_builder import _q, _exec         # noqa: E402
import users_admin as ua                   # noqa: E402

UID = str(uuid.uuid4())
FID = str(uuid.uuid4())
EMAIL = f"zztest_r4_{UID[:8]}@example.test"


def cleanup():
    _exec("DELETE FROM usuario WHERE id=%s", (UID,))
    _exec("DELETE FROM cat_formato_origen WHERE id=%s", (FID,))


cleanup()
_exec("INSERT INTO cat_formato_origen (id, codigo, nombre, activo) "
      "VALUES (%s,%s,%s,true)", (FID, f"ZZ_R4_{UID[:8]}", "Throwaway R4 formato"))
try:
    # 1. create a TECNICO with a formato assignment → persists
    ua.create_usuario(UID, "ZZ Test R4", EMAIL, "TECNICO", None, None, formato_origen_id=FID)
    row = _q("SELECT rol::text AS rol, formato_origen_id::text AS f FROM usuario WHERE id=%s",
             (UID,))[0]
    assert row["rol"] == "TECNICO" and row["f"] == FID

    # 2. list_usuarios surfaces the formato id + name
    me = next(r for r in ua.list_usuarios() if r["id"] == UID)
    assert me["formato_origen_id"] == FID and me["formato"] == "Throwaway R4 formato"

    # 3. _formatos includes our active throwaway formato
    assert any(f["id"] == FID for f in ua._formatos())

    # 4. set_rol away from TECNICO clears the formato (kept only for TECNICO)
    ua.set_rol(UID, "ADMINISTRADOR", None, formato_origen_id=None)
    assert _q("SELECT formato_origen_id FROM usuario WHERE id=%s",
              (UID,))[0]["formato_origen_id"] is None

    # 5. set_rol back to TECNICO with a formato → set again
    ua.set_rol(UID, "TECNICO", None, formato_origen_id=FID)
    assert _q("SELECT formato_origen_id::text AS f FROM usuario WHERE id=%s",
              (UID,))[0]["f"] == FID

    print("TODOS LOS CHECKS PASAN")
finally:
    cleanup()
