"""Dedup + transactional insert for the Excel importer. Resolves a FaenaDraft's catalog
placeholders to ids, computes a natural-key legacy_id for idempotency, and commits a batch
with a per-faena SAVEPOINT so one bad faena doesn't sink the rest."""
from __future__ import annotations
import hashlib
import uuid

from form_builder import get_conn, _q, _log
import catalog_resolver as R


def _resolve_cell(v):
    """('catalog', cat, raw) → id (resolve/create); else pass-through."""
    if isinstance(v, tuple) and len(v) == 3 and v[0] == "catalog":
        _, cat, raw = v
        return R.resolve_or_create(cat, raw)
    return v


def resolve_draft(spec, draft):
    """FaenaDraft → {faena, catches, arte, carnada, etp, gasto, errors, key} with ids resolved."""
    faena = {k: _resolve_cell(v) for k, v in draft.faena_raw.items()}
    faena["legacy_id"] = natural_key_hash(spec.codigo, faena)
    catches = [{"especie_id": R.resolve_or_create_especie(c["comun"], c["cientifico"]),
                "captura_kg": c["captura_kg"], "categoria_tamano": c["categoria_tamano"],
                "precio_kg": c["precio_kg"]} for c in draft.catches]
    arte = {k: _resolve_cell(v) for k, v in draft.children_raw["arte"].items()}
    carn = draft.children_raw["carnada"]
    carnada = None
    if carn:
        carnada = {"origen": _origen(carn.get("origen")),
                   "especie_id": R.resolve_or_create_especie(carn.get("comun"), carn.get("cientifico")),
                   "sitio_pesca_carnada_id": _resolve_cell(carn.get("sitio_pesca_carnada_id")),
                   "kg_aprox": _num(carn.get("kg_aprox")), "arte_pesca_id": _resolve_cell(carn.get("arte_pesca_id"))}
    etp = [{"especie_id": R.resolve_or_create_especie(e["comun"], "NA"),
            "tipo_interaccion_id": R.resolve_or_create("cat_tipo_interaccion_etp", e["interaccion"])}
           for e in draft.children_raw["etp"]]
    gasto = [{"tipo_gasto_id": R.resolve_or_create("cat_tipo_gasto", g["tipo"]),
              "cantidad": g["cantidad"], "monto_total": g["monto_total"]}
             for g in draft.children_raw["gasto"]]
    mediciones = [{"especie_id": R.resolve_or_create_especie(m["comun"], m["cientifico"]),
                   "longitud_total_cm": m["longitud_total_cm"], "peso_gr": m.get("peso_gr"),
                   "procesado": m.get("procesado", "NA")}
                  for m in getattr(draft, "mediciones", [])]
    return {"key": draft.key, "faena": faena, "catches": catches, "arte": arte,
            "carnada": carnada, "etp": etp, "gasto": gasto, "mediciones": mediciones,
            "errors": list(draft.errors)}


def _origen(v):
    m = R.normalize(v).casefold()
    if m.startswith("compr"): return "COMPRADA"
    if m.startswith("pesc"):  return "PESCADA"
    return "NA"


def _num(v):
    try: return float(v)
    except (TypeError, ValueError): return None


def natural_key_hash(codigo, faena_resolved):
    parts = [codigo, str(faena_resolved.get("fecha")), str(faena_resolved.get("comunidad_id")),
             str(faena_resolved.get("sitio_pesca_id")), str(faena_resolved.get("capitan_id")),
             str(faena_resolved.get("embarcacion_id")), str(faena_resolved.get("tecnico_id"))]
    return codigo + ":" + hashlib.sha1("|".join(parts).encode()).hexdigest()[:24]


def existing_legacy_ids(hashes):
    if not hashes:
        return set()
    rows = _q("SELECT legacy_id FROM faena WHERE legacy_id = ANY(%s)", (list(hashes),))
    return {r["legacy_id"] for r in rows}


_FAENA_COLS = ("legacy_id", "codigo_formato", "formato_origen_id", "tipo_registro", "fecha",
               "comunidad_id", "sitio_pesca_id", "area_pesca_id", "zona_pesca_id", "embarcacion_id",
               "cooperativa_id", "capitan_id", "tecnico_id", "encargado_lugar", "num_pescadores",
               "gasolina_lts", "motor_hp", "tiempo_efectivo_pesca_h", "profundidad_min_brazas",
               "profundidad_max_brazas", "tipo_fondo_id", "viento_id", "luna_id", "marea_id",
               "latitud_legacy", "longitud_legacy", "hora_salida", "hora_llegada", "observaciones")


_FORMATO_NOMBRE = {"MASIVOS_LEGACY": "Masivos Legacy (Anexo 2)",
                   "BITACORA_LEGACY": "Bitácoras Legacy (Anexo 2)",
                   "MONITOREO_LEGACY": "Monitoreo Pesquero Legacy (Anexo 2)"}


def _formato_id(codigo):
    row = _q("SELECT id::text AS id FROM cat_formato_origen WHERE codigo=%s", (codigo,))
    if row:
        return row[0]["id"]
    nombre = _FORMATO_NOMBRE.get(codigo, codigo)
    return _q("INSERT INTO cat_formato_origen (codigo, nombre) VALUES (%s,%s) "
              "RETURNING id::text AS id", (codigo, nombre))[0]["id"]


def _ins(cur, table, cols: dict):
    rid = str(uuid.uuid4())
    cols = {"id": rid, **cols}
    keys = ", ".join(f'"{k}"' for k in cols)
    ph = ", ".join(["%s"] * len(cols))
    cur.execute(f'INSERT INTO public."{table}" ({keys}) VALUES ({ph})', list(cols.values()))
    return rid


def commit_batch(spec, resolved, *, force=False):
    formato_id = _formato_id(spec.codigo)
    hashes = [r["faena"]["legacy_id"] for r in resolved if r["key"]]
    dup = set() if force else existing_legacy_ids(hashes)
    rep = {"faenas_nuevas": 0, "ya_existen": 0, "capturas": 0, "mediciones": 0,
           "faenas_error": 0, "errores": []}
    conn = get_conn()
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            for r in resolved:
                if r["key"] is None:
                    rep["faenas_error"] += 1; rep["errores"] += r["errors"]; continue
                if r["faena"]["legacy_id"] in dup:
                    rep["ya_existen"] += 1; continue
                cur.execute("SAVEPOINT sp")
                try:
                    f = {k: r["faena"].get(k) for k in _FAENA_COLS}
                    f["formato_origen_id"] = formato_id
                    fid = _ins(cur, "faena", f)
                    for c in r["catches"]:
                        _ins(cur, "captura", {"faena_id": fid, **c}); rep["capturas"] += 1
                    for m in r.get("mediciones", []):
                        _ins(cur, "medicion", {"faena_id": fid,
                                               **{k: v for k, v in m.items() if v is not None}})
                        rep["mediciones"] += 1
                    if any(v is not None for v in r["arte"].values()):
                        _ins(cur, "faena_arte", {"faena_id": fid, **{k: v for k, v in r["arte"].items() if v is not None}})
                    if r["carnada"]:
                        _ins(cur, "carnada", {"faena_id": fid, **{k: v for k, v in r["carnada"].items() if v is not None},
                                              "kg_aprox": r["carnada"].get("kg_aprox") or 0})
                    for e in r["etp"]:
                        _ins(cur, "interaccion_etp", {"faena_id": fid, **e})
                    for g in r["gasto"]:
                        _ins(cur, "gasto", {"faena_id": fid, **g})
                    cur.execute("RELEASE SAVEPOINT sp")
                    _log("faena", fid, "importar", {"legacy_id": f["legacy_id"],
                                                    "capturas": len(r["catches"]),
                                                    "mediciones": len(r.get("mediciones", []))})
                    rep["faenas_nuevas"] += 1
                except Exception as e:      # noqa: BLE001
                    cur.execute("ROLLBACK TO SAVEPOINT sp")
                    rep["faenas_error"] += 1; rep["errores"].append(str(e))
        conn.commit()
    except Exception:
        conn.rollback(); raise
    finally:
        conn.autocommit = True
    return rep
