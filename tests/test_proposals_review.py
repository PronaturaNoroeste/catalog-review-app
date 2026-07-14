"""Round-trip test for the proposal→curated-list wiring against the DEV database.

A curated list is a strict subset of its catalog, so a name that is approved but never
listed vanishes from the tablet picker it was proposed on. Migration 0019 makes the
proposal carry its list; this checks the console can read that back (proposal_origin)
and put the approved name into exactly that list (add_to_lista).

Refuses to run against anything that isn't the dev project. Cleans up after itself
(cambio_catalogo audit rows are append-only by design and are left behind).

Run from the repo root:  python tests/test_proposals_review.py
"""
import json
import os
import pathlib
import sys
import uuid

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

DEV_REF = "pxxqumcvkoltbjubyvod"
# the migrations repo is checked out as supabase-backend/ (WSL) or Planning/supabase/ (Windows)
CANDIDATES = [BASE.parent / "supabase-backend" / ".env",
              BASE.parent / "Planning" / "supabase" / ".env"]
dsn = None
for envf in CANDIDATES:
    if not envf.exists():
        continue
    for line in envf.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("DATABASE_URL="):
            dsn = line.strip().split("=", 1)[1].strip().strip("'").strip('"')
            break
    if dsn:
        break
assert dsn, "pon el DSN de DEV en " + " o ".join(str(c) for c in CANDIDATES)
assert DEV_REF in dsn, "el DSN no es el proyecto DEV — me niego a correr contra otra base"
os.environ["DATABASE_URL"] = dsn

from form_builder import _q, _exec           # noqa: E402
import proposals_review as pr                # noqa: E402

FID = str(uuid.uuid4())                      # throwaway formato
RID = str(uuid.uuid4())                      # the proposed catalog row
TAG = f"ZZTEST prop {FID[:8]}"
LISTA = "arte_de_pesca_de_la_carnada"


def cleanup():
    _exec("DELETE FROM lista_opcion WHERE formato_origen_id=%s", (FID,))
    _exec("DELETE FROM cat_tipo_arte WHERE id=%s", (RID,))
    _exec("DELETE FROM cat_formato_origen WHERE id=%s", (FID,))


def main():
    cleanup()
    _exec("INSERT INTO cat_formato_origen (id, codigo, nombre) VALUES (%s,%s,%s)",
          (FID, f"ZZTEST_{FID[:8]}", TAG))
    # a pending proposal, exactly as the tablet's RPC writes it (0019 detalle)
    _exec("""INSERT INTO cat_tipo_arte (id, nombre, estado, es_aprobado)
             VALUES (%s,%s,'pendiente',false)""", (RID, TAG))
    _exec("""INSERT INTO cambio_catalogo (tabla, registro_id, accion, detalle)
             VALUES ('cat_tipo_arte', %s, 'crear', %s::jsonb)""",
          (RID, json.dumps({"nombre": TAG, "origen": "app", "faena_id": str(uuid.uuid4()),
                            "lista": LISTA, "formato_origen_id": FID})))

    # 1. the console recovers the list + form the técnico proposed from
    origin = pr.proposal_origin(RID)
    assert origin == {"lista": LISTA, "formato_origen_id": FID}, origin

    # 2. approving + listing puts it in that list, and it is then visible to the tablet
    pr.approve("cat_tipo_arte", RID, TAG)
    pr.add_to_lista(FID, LISTA, "cat_tipo_arte", RID, TAG)

    row = _q("SELECT estado, es_aprobado FROM cat_tipo_arte WHERE id=%s", (RID,))[0]
    assert row["estado"] == "aprobado" and row["es_aprobado"] is True, row
    listed = _q("""SELECT 1 FROM lista_opcion
                    WHERE formato_origen_id=%s AND lista=%s AND registro_id=%s""",
                (FID, LISTA, RID))
    assert listed, "the approved name never joined the curated list — it would vanish"

    # 3. idempotent: a second approval must not duplicate the list row
    pr.add_to_lista(FID, LISTA, "cat_tipo_arte", RID, TAG)
    n = _q("""SELECT count(*) AS n FROM lista_opcion
               WHERE formato_origen_id=%s AND lista=%s AND registro_id=%s""",
           (FID, LISTA, RID))[0]["n"]
    assert n == 1, f"lista_opcion duplicated ({n})"

    # 4. the list now shows up as a candidate for this catalog on this form
    assert LISTA in pr.listas_for("cat_tipo_arte", FID)

    # 5. a proposal with no recorded list (pre-0019) degrades to a manual choice
    assert pr.proposal_origin(str(uuid.uuid4())) == {}

    print("OK — proposal carries its list; approval puts the name back in it.")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
