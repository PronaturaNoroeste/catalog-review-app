"""Declarative Anexo-2 production format specs (Masivos, Bitácoras) + pure parsing/grouping.
No DB, no Streamlit — safe to unit test."""
from __future__ import annotations
import datetime
from dataclasses import dataclass, field

from catalog_resolver import is_na, normalize   # reuse NA logic


@dataclass(frozen=True)
class Target:
    table: str
    column: str
    kind: str                 # text|num|date|hora|catalog|enum
    catalog: str | None = None


@dataclass(frozen=True)
class FormatSpec:
    codigo: str
    tipo_registro: str
    header_signature: frozenset
    faena_cols: dict
    catch_cols: dict
    especie_comun: str
    especie_cientifico: str
    key_headers: tuple
    children: dict = field(default_factory=dict)


# ---- parsers ----
def parse_num(v):
    if is_na(v):
        return None
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return None


def parse_date(dia, mes, ano):
    try:
        d, m, y = int(dia), int(mes), int(ano)
        return datetime.date(y, m, d)
    except (ValueError, TypeError):
        return None


def parse_hora(v):
    if is_na(v):
        return None
    s = normalize(v)
    if isinstance(v, datetime.time):
        return v.strftime("%H:%M")
    for sep in (":", "."):
        if sep in s:
            hh, _, mm = s.partition(sep)
            try:
                return f"{int(hh):02d}:{int(mm or 0):02d}"
            except ValueError:
                return None
    return None


def _strip(h):
    return normalize(h)


def parse_rows(headers, data_rows):
    hs = [_strip(h) for h in headers]
    out = []
    for r in data_rows:
        d = {hs[i]: r[i] for i in range(len(hs)) if hs[i]}
        if all(is_na(v) for v in d.values()):
            continue
        out.append(d)
    return out


def detect_format(headers):
    """Score by containment (matched / provided headers), not Jaccard: a real workbook's
    header row is a subset of a spec's full column signature (many optional columns), so
    penalizing for the signature's unused columns would suppress correct detection."""
    hs = {_strip(h) for h in headers if _strip(h)}
    if not hs:
        return None
    best, score = None, 0.0
    for code, spec in FORMATS.items():
        j = len(hs & spec.header_signature) / len(hs)
        if j > score:
            best, score = code, j
    return best if score >= 0.4 else None


# ---- shared faena/catch/child column maps (stripped headers) ----
_FAENA = {
    "Comunidad/ Sitio de arribo": Target("faena", "comunidad_id", "catalog", "cat_comunidad"),
    "Lugar/ Sitio de pesca":      Target("faena", "sitio_pesca_id", "catalog", "cat_sitio_pesca"),
    "Area de Pesca":              Target("faena", "area_pesca_id", "catalog", "cat_area_pesca"),
    "Zona de pesca":              Target("faena", "zona_pesca_id", "catalog", "cat_zona_pesca"),
    "Pescador":                   Target("faena", "capitan_id", "catalog", "cat_pescador"),
    "Embarcacion":                Target("faena", "embarcacion_id", "catalog", "cat_embarcacion"),
    "Cooperativa":                Target("faena", "cooperativa_id", "catalog", "cat_cooperativa"),
    "Num de pescadores":          Target("faena", "num_pescadores", "num"),
    "Gasolina (lts)":             Target("faena", "gasolina_lts", "num"),
    "Encargado del lugar":        Target("faena", "encargado_lugar", "text"),
    "Motor (hp)":                 Target("faena", "motor_hp", "num"),
    "Hora de salida":             Target("faena", "hora_salida", "hora"),
    "Hora de llegada":            Target("faena", "hora_llegada", "hora"),
    "Horas de pesca (h/min)":     Target("faena", "tiempo_efectivo_pesca_h", "num"),
    "profund_min":                Target("faena", "profundidad_min_brazas", "num"),
    "profund_max":                Target("faena", "profundidad_max_brazas", "num"),
    "Tipo de fondo":              Target("faena", "tipo_fondo_id", "catalog", "cat_tipo_fondo"),
    "Viento":                     Target("faena", "viento_id", "catalog", "cat_tipo_viento"),
    "Luna":                       Target("faena", "luna_id", "catalog", "cat_tipo_luna"),
    "Marea":                      Target("faena", "marea_id", "catalog", "cat_tipo_marea"),
    "Latitud":                    Target("faena", "latitud_legacy", "text"),
    "Longitud":                   Target("faena", "longitud_legacy", "text"),
    "Observaciones/ Pescador":    Target("faena", "observaciones", "text"),
}
_CATCH = {
    "Categoria por tamaño": Target("captura", "categoria_tamano", "text"),
    "Captura (kg)":         Target("captura", "captura_kg", "num"),
    "Precio":               Target("captura", "precio_kg", "num"),
}
# child sub-specs (headers → target columns); resolution/skip logic in Task 5 group_faenas
_CHILDREN = {
    "arte": {"tipo_arte_id": ("Arte de pesca", "cat_tipo_arte"),
             "tipo_anzuelo_id": ("Tipo de anzuelo", "cat_tipo_anzuelo"),
             "tipo_operacion_id": ("Operacion", "cat_tipo_operacion"),
             "metodo": ("Metodo/Caida", None), "material": ("Anzuelos trabajando/Material", None)},
    "carnada": {"origen": ("Comprada o pescada", None),
                "comun": ("Nombre comun carnada", None), "cientifico": ("Nombre cientifico carnada", None),
                "sitio_pesca_carnada_id": ("Sitio de pesca de la carnada", "cat_sitio_pesca"),
                "kg_aprox": ("Kg (aprox/ carnada)", None),
                "arte_pesca_id": ("Arte de pesca carnada", "cat_tipo_arte")},
    "etp": [("Especie", "Interacción"), ("Especie 2", "Interacción 2")],
    "gasto": {  # gasto tipo (cat_tipo_gasto name) : (cantidad header, monto header)
        "Gasolina": ("Gasolina (lts)", "$ gasolina"), "Anzuelos": ("anzuelos", "$anzuelos"),
        "Destorcedores": ("Destorcedores", "$ destorcedores"), "Plomadas": ("plomada", "$plomadas"),
        "Piola": ("piola", "$ piola")},
}

_MASIVOS = FormatSpec(
    codigo="MASIVOS_LEGACY", tipo_registro="MASIVO",
    header_signature=frozenset({*_FAENA, *_CATCH, "ID", "Num.Formato", "Tecnico", "Dia", "Mes",
                                "Año", "Nombre comun", "Nombre cientifico", "Otros gastos"}),
    faena_cols={**_FAENA, "Tecnico": Target("faena", "tecnico_id", "catalog", "cat_tecnico"),
                "Num.Formato": Target("faena", "codigo_formato", "text")},
    catch_cols=_CATCH, especie_comun="Nombre comun", especie_cientifico="Nombre cientifico",
    key_headers=("Dia", "Mes", "Año", "Comunidad/ Sitio de arribo", "Lugar/ Sitio de pesca",
                 "Pescador", "Embarcacion", "Tecnico"),
    children=_CHILDREN)

_BITACORA = FormatSpec(
    codigo="BITACORA_LEGACY", tipo_registro="BITACORA",
    header_signature=frozenset({*_FAENA, *_CATCH, "Dia", "Mes", "Año", "Nombre comun",
                                "Nombre cientifico", "Datos capturados por", "Cantidad de aceite"}),
    faena_cols={**_FAENA,
                "Datos capturados por": Target("faena", "tecnico_id", "catalog", "cat_tecnico")},
    catch_cols=_CATCH, especie_comun="Nombre comun", especie_cientifico="Nombre cientifico",
    key_headers=("Dia", "Mes", "Año", "Comunidad/ Sitio de arribo", "Lugar/ Sitio de pesca",
                 "Pescador", "Embarcacion", "Datos capturados por"),
    children=_CHILDREN)

FORMATS = {"MASIVOS_LEGACY": _MASIVOS, "BITACORA_LEGACY": _BITACORA}


from dataclasses import dataclass as _dc

@_dc
class FaenaDraft:
    key: tuple | None
    faena_raw: dict
    catches: list
    children_raw: dict
    errors: list


def _faena_fields(row, spec):
    """Map trip-level raw row → {faena_column: raw_or_parsed_value} (pre-catalog)."""
    out, errors = {}, []
    for header, t in spec.faena_cols.items():
        v = row.get(header)
        if t.kind == "num":
            out[t.column] = parse_num(v)
        elif t.kind == "hora":
            out[t.column] = parse_hora(v)
        elif t.kind == "catalog":
            out[t.column] = ("catalog", t.catalog, v)      # resolved later
        else:
            out[t.column] = None if is_na(v) else normalize(v)
    # fecha
    out["fecha"] = parse_date(row.get("Dia"), row.get("Mes"), row.get("Año"))
    # required hours default
    if not out.get("tiempo_efectivo_pesca_h"):
        out["tiempo_efectivo_pesca_h"] = 0
        errors.append("tiempo de pesca desconocido → 0 (revisar)")
    out["tipo_registro"] = spec.tipo_registro
    return out, errors


def _catch(row, spec):
    kg = parse_num(row.get("Captura (kg)"))
    if kg is None:
        return None
    return {"comun": row.get(spec.especie_comun), "cientifico": row.get(spec.especie_cientifico),
            "captura_kg": kg,
            "categoria_tamano": None if is_na(row.get("Categoria por tamaño"))
            else normalize(row.get("Categoria por tamaño")),
            "precio_kg": parse_num(row.get("Precio"))}


def _key(row, spec):
    return tuple(normalize(row.get(h)) for h in spec.key_headers)


def group_faenas(rows, spec):
    order, buckets = [], {}
    for row in rows:
        k = _key(row, spec)
        if k not in buckets:
            buckets[k] = []; order.append(k)
        buckets[k].append(row)
    drafts = []
    for k in order:
        group = buckets[k]
        faena_raw, errors = _faena_fields(group[0], spec)
        valid_key = k if faena_raw.get("fecha") else None
        if faena_raw.get("fecha") is None:
            errors.append("fecha inválida (Día/Mes/Año) — faena omitida")
        catches = []
        for row in group:
            c = _catch(row, spec)
            if c is None:
                errors.append(f"captura sin kg omitida: {normalize(row.get(spec.especie_comun))}")
            else:
                catches.append(c)
        children_raw = _children(group[0], spec)      # trip-level children from first row
        drafts.append(FaenaDraft(valid_key, faena_raw, catches, children_raw, errors))
    return drafts


def _children(row, spec):
    ch = spec.children
    out = {"arte": {}, "carnada": {}, "etp": [], "gasto": []}
    if any(not is_na(row.get(header)) for header, _cat in ch["arte"].values()):
        for col, (header, cat) in ch["arte"].items():
            v = row.get(header)
            out["arte"][col] = ("catalog", cat, v) if cat else (None if is_na(v) else normalize(v))
    if not is_na(row.get(ch["carnada"]["comun"][0])) or not is_na(row.get(ch["carnada"]["origen"][0])):
        for col, (header, cat) in ch["carnada"].items():
            v = row.get(header)
            out["carnada"][col] = ("catalog", cat, v) if cat else (None if is_na(v) else normalize(v))
    for esp_h, int_h in ch["etp"]:
        if not is_na(row.get(esp_h)):
            out["etp"].append({"comun": row.get(esp_h), "interaccion": row.get(int_h)})
    for tipo, (cant_h, monto_h) in ch["gasto"].items():
        monto = parse_num(row.get(monto_h))
        if monto is not None:
            out["gasto"].append({"tipo": tipo, "cantidad": parse_num(row.get(cant_h)),
                                 "monto_total": monto})
    return out
