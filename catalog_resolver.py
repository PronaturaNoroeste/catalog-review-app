"""Catalog resolution for the Excel importer: normalize free-text values, fuzzy-match
them against existing cat_* entries (difflib), and resolve-or-create ids. Especie is
matched on the (común, científico) pair — never común alone (homonyms).
"""
from __future__ import annotations
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
