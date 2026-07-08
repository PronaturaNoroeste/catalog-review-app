"""Round-trip test for lista_editor's data layer against the DEV database.

Requires the dev DSN in ../supabase-backend/.env (DATABASE_URL) and refuses to
run against anything that isn't the dev project. Creates a throwaway formato +
catalog rows, exercises the API, and cleans up after itself (audit rows in
cambio_catalogo are left — the trail is append-only by design).

Run from the repo root:  PYTHONPATH="$PYLIB:." python3 tests/test_lista_editor.py
"""
import os
import pathlib
import sys
import uuid

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

DEV_REF = "pxxqumcvkoltbjubyvod"
envf = BASE.parent / "supabase-backend" / ".env"
dsn = None
if envf.exists():
    for line in envf.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("DATABASE_URL="):
            dsn = line.strip().split("=", 1)[1].strip().strip("'").strip('"')
            break
assert dsn, f"pon el DSN de DEV en {envf}"
assert DEV_REF in dsn, "el DSN no es el proyecto DEV — me niego a correr contra otra base"
os.environ["DATABASE_URL"] = dsn      # form_builder._dsn() prefers the environment

from form_builder import _q, _exec    # noqa: E402
import lista_editor as le             # noqa: E402

FID = str(uuid.uuid4())
TAG = f"ZZTEST R3 {FID[:8]}"


def cleanup():
    _exec("DELETE FROM lista_opcion WHERE formato_origen_id=%s", (FID,))
    _exec("DELETE FROM cat_especie WHERE nombre_comun LIKE %s", (TAG + "%",))
    _exec("DELETE FROM cat_formato_origen WHERE id=%s", (FID,))


_exec("INSERT INTO cat_formato_origen (id, codigo, nombre, activo) "
      "VALUES (%s,%s,%s,false)", (FID, f"TEST_R3_{FID[:8]}", "Throwaway R3 test"))
try:
    # 1. a fresh formato has no lists
    assert le.form_listas(FID) == {}

    # 2. create_and_add: brand-new approved especie lands in catalog + list
    n1 = f"{TAG} uno"
    rid1 = le.create_and_add(FID, "especies_test", "cat_especie", n1, "Testus unus")
    row = _q("SELECT estado, es_aprobado, nombre_cientifico FROM cat_especie WHERE id=%s",
             (rid1,))[0]
    assert row["estado"] == "aprobado" and row["es_aprobado"] is True
    assert row["nombre_cientifico"] == "Testus unus"
    ops = le.get_opciones(FID, "especies_test", "cat_especie")
    assert [o["registro_id"] for o in ops] == [rid1]
    assert ops[0]["nombre"] == n1 and ops[0]["cientifico"] == "Testus unus"
    assert ops[0]["importancia"] == 0

    # 3. search: accent/case-insensitive, respects exclude_ids
    hits = le.search_catalogo("cat_especie", f"zztest r3 {FID[:8]} UNO")
    assert any(h["id"] == rid1 for h in hits)
    hits = le.search_catalogo("cat_especie", n1, exclude_ids={rid1})
    assert not any(h["id"] == rid1 for h in hits)

    # 4. add an existing row; higher importancia sorts first
    n2 = f"{TAG} dós"                             # accent exercises _norm
    rid2 = str(uuid.uuid4())
    _exec("INSERT INTO cat_especie (id, nombre_comun, nombre_cientifico, es_aprobado, estado) "
          "VALUES (%s,%s,'Testus duo',true,'aprobado')", (rid2, n2))
    le.add_opcion(FID, "especies_test", "cat_especie", rid2, importancia=5)
    ops = le.get_opciones(FID, "especies_test", "cat_especie")
    assert [o["registro_id"] for o in ops] == [rid2, rid1]

    # 5. form_listas now sees it
    assert le.form_listas(FID) == {"especies_test": "cat_especie"}

    # 6. set_importancia reorders; re-add is an upsert (no duplicate)
    le.set_importancia(FID, "especies_test", rid1, 9)
    ops = le.get_opciones(FID, "especies_test", "cat_especie")
    assert ops[0]["registro_id"] == rid1 and ops[0]["importancia"] == 9
    le.add_opcion(FID, "especies_test", "cat_especie", rid2, importancia=7)
    assert len(le.get_opciones(FID, "especies_test", "cat_especie")) == 2

    # 7. search returns only estado='aprobado' rows (search the full unique
    # name — a short term like «dós» could match unrelated dev species)
    _exec("UPDATE cat_especie SET estado='pendiente' WHERE id=%s", (rid2,))
    assert not le.search_catalogo("cat_especie", n2)
    _exec("UPDATE cat_especie SET estado='aprobado' WHERE id=%s", (rid2,))

    # 8. remove one option; the other stays
    le.remove_opcion(FID, "especies_test", rid2)
    ops = le.get_opciones(FID, "especies_test", "cat_especie")
    assert [o["registro_id"] for o in ops] == [rid1]

    # 9. create_and_add on lista 'carnada' marks apta_carnada; blank sci → 'Pendiente'
    rid3 = le.create_and_add(FID, "carnada", "cat_especie", f"{TAG} tres")
    row = _q("SELECT apta_carnada, nombre_cientifico FROM cat_especie WHERE id=%s", (rid3,))[0]
    assert row["apta_carnada"] is True and row["nombre_cientifico"] == "Pendiente"

    # 10. build_campo: lista set / dropped / preserved
    from form_builder import build_campo
    base_v = {"key": "especie", "label": "Especie", "tipo": "catalogo",
              "bind_tipo": "core", "bind_columna": "captura.especie_id",
              "catalogo": "cat_especie"}
    c0 = {"key": "especie", "tipo": "catalogo", "lista": "especies"}
    # managed + new name → set
    out = build_campo(c0, {**base_v, "lista_managed": True, "lista": "otra"}, {})
    assert out["lista"] == "otra"
    # managed + empty → dropped (detach)
    out = build_campo(c0, {**base_v, "lista_managed": True, "lista": ""}, {})
    assert "lista" not in out
    # not managed → preserved untouched (old callers can't drop it)
    out = build_campo(c0, base_v, {})
    assert out["lista"] == "especies"

    print("TODOS LOS CHECKS PASAN")
finally:
    cleanup()
