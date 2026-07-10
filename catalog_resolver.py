"""Catalog resolution for the Excel importer: normalize free-text values, fuzzy-match
them against existing cat_* entries (difflib), and resolve-or-create ids. Especie is
matched on the (común, científico) pair — never común alone (homonyms).
"""
from __future__ import annotations
import functools
import unicodedata
from difflib import SequenceMatcher, get_close_matches

_NA = {"", "na", "nd", "n/a", "s/n", "sn", "pendiente", "desconocido",
       "sin dato", "sin datos", "none", "null", "-", "."}


def normalize(v) -> str:
    if v is None:
        return ""
    return " ".join(str(v).split()).strip()


def is_na(v) -> bool:
    return normalize(v).casefold() in _NA


def _key(s: str) -> str:
    # accent- and case-insensitive comparison key
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.casefold()


def best_matches(candidates: list[str], value: str, n: int = 3,
                 cutoff: float = 0.82) -> list[tuple[str, float]]:
    """Top-n candidate names similar to `value`, accent/case-insensitive, with scores."""
    v = _key(normalize(value))
    if not v:
        return []
    keyed = {_key(c): c for c in candidates}
    hits = get_close_matches(v, list(keyed), n=n, cutoff=cutoff)
    out = [(keyed[h], SequenceMatcher(None, v, h).ratio()) for h in hits]
    return out


from form_builder import _q, _exec, _log

_NAMECOL = {"cat_especie": "nombre_comun"}   # else 'nombre'


def _namecol(catalog: str) -> str:
    return _NAMECOL.get(catalog, "nombre")


@functools.lru_cache(maxsize=1)
def _approvable_catalogs() -> frozenset[str]:
    """Catalogs that carry an es_aprobado column (queried live — the set of catalogs
    with moderation differs from table to table, e.g. cat_tipo_viento/luna/marea/gasto/
    interaccion_etp have none, but cat_tipo_arte/anzuelo/fondo/operacion do)."""
    rows = _q("SELECT table_name FROM information_schema.columns "
              "WHERE table_schema='public' AND column_name='es_aprobado'")
    return frozenset(r["table_name"] for r in rows)


def catalog_names(catalog: str) -> list[dict]:
    nc = _namecol(catalog)
    return _q(f'SELECT id::text AS id, {nc} AS name FROM public."{catalog}" '
              f'WHERE {nc} IS NOT NULL')


def _index(catalog: str) -> dict[str, str]:
    return {_key(normalize(r["name"])): r["id"] for r in catalog_names(catalog)}


def _lookup(catalog: str, value: str) -> str | None:
    """Exact index lookup, bypassing is_na — used for placeholder names ("Desconocido")
    that are themselves NA-sentinel text but are real catalog rows once created."""
    return _index(catalog).get(_key(normalize(value)))


def resolve_exact(catalog: str, value: str) -> str | None:
    if is_na(value):
        return None
    return _lookup(catalog, value)


def fuzzy_suggest(catalog: str, value: str) -> list[tuple[str, str, float]]:
    names = [r["name"] for r in catalog_names(catalog)]
    idx = {r["name"]: r["id"] for r in catalog_names(catalog)}
    return [(idx[n], n, sc) for n, sc in best_matches(names, value)]


def _insert(catalog: str, cols: dict) -> str:
    if catalog in _approvable_catalogs():
        cols = {**cols, "es_aprobado": False}
    keys = ", ".join(f'"{k}"' for k in cols)
    ph = ", ".join(["%s"] * len(cols))
    rid = _q(f'INSERT INTO public."{catalog}" ({keys}) VALUES ({ph}) RETURNING id::text AS id',
             list(cols.values()))[0]["id"]
    _log(catalog, rid, "importar", {"creado": cols})
    return rid


def resolve_or_create(catalog: str, value: str) -> str:
    if is_na(value):
        return desconocido_id(catalog)
    hit = resolve_exact(catalog, value)
    return hit if hit else _insert(catalog, {_namecol(catalog): normalize(value)})


def desconocido_id(catalog: str) -> str:
    hit = _lookup(catalog, "Desconocido")
    return hit if hit else _insert(catalog, {_namecol(catalog): "Desconocido"})


# --- especie (pair-keyed) ---
def _especie_index() -> dict[tuple[str, str], str]:
    rows = _q("SELECT id::text AS id, nombre_comun, nombre_cientifico FROM cat_especie")
    return {(_key(normalize(r["nombre_comun"])), _key(normalize(r["nombre_cientifico"]))): r["id"]
            for r in rows}


def _lookup_especie(comun, cientifico) -> str | None:
    """Exact especie-pair lookup, bypassing is_na — see _lookup."""
    c = "" if is_na(cientifico) else _key(normalize(cientifico))
    return _especie_index().get((_key(normalize(comun)), c))


def resolve_especie(comun, cientifico) -> str | None:
    if is_na(comun) and is_na(cientifico):
        return None
    return _lookup_especie(comun, cientifico)


def fuzzy_especie(comun, cientifico) -> list[tuple[str, str, float]]:
    # suggest on común (display "común — científico"); admin disambiguates científico
    rows = _q("SELECT id::text AS id, nombre_comun, nombre_cientifico FROM cat_especie")
    disp = {f'{r["nombre_comun"]} — {r["nombre_cientifico"] or "?"}': r["id"] for r in rows}
    names = [r["nombre_comun"] for r in rows]
    byname = {r["nombre_comun"]: r for r in rows}
    out = []
    for n, sc in best_matches(names, comun, n=5, cutoff=0.8):
        r = byname[n]
        out.append((r["id"], f'{r["nombre_comun"]} — {r["nombre_cientifico"] or "?"}', sc))
    return out


def resolve_or_create_especie(comun, cientifico) -> str:
    if is_na(comun) and is_na(cientifico):
        return desconocido_especie_id()
    hit = resolve_especie(comun, cientifico)
    if hit:
        return hit
    cols = {"nombre_comun": normalize(comun) or "Desconocido",
            "nombre_cientifico": None if is_na(cientifico) else normalize(cientifico),
            "es_aprobado": False}
    return _insert_especie(cols)


def _insert_especie(cols: dict) -> str:
    keys = ", ".join(f'"{k}"' for k in cols)
    ph = ", ".join(["%s"] * len(cols))
    rid = _q(f'INSERT INTO cat_especie ({keys}) VALUES ({ph}) RETURNING id::text AS id',
             list(cols.values()))[0]["id"]
    _log("cat_especie", rid, "importar", {"creado": cols})
    return rid


def desconocido_especie_id() -> str:
    hit = _lookup_especie("Desconocido", "NA")
    return hit if hit else _insert_especie(
        {"nombre_comun": "Desconocido", "nombre_cientifico": None, "es_aprobado": False})
