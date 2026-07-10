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
