"""
💾 Consultas de descarga guardadas (R2.1) — per-user saved export queries.

Stores a re-runnable spec (builder/preset params + column select/rename) in
`consulta_export` (migration 0014), scoped to the logged-in user. `compartida`
makes a query visible to other console users. Reuses the form_builder DB layer.
"""
from __future__ import annotations

import json

from form_builder import _q, _exec, _log


def save_consulta(uid: str, nombre: str, config: dict, compartida: bool):
    _exec("""INSERT INTO consulta_export (usuario_id, nombre, config, compartida)
             VALUES (%s,%s,%s::jsonb,%s)
             ON CONFLICT (usuario_id, nombre) DO UPDATE
               SET config=EXCLUDED.config, compartida=EXCLUDED.compartida, updated_at=now()""",
          (uid, nombre.strip(), json.dumps(config, ensure_ascii=False, default=str), compartida))
    _log("consulta_export", uid, "guardar", {"nombre": nombre.strip(), "compartida": compartida})


def list_consultas(uid: str) -> list[dict]:
    """The user's own queries + any shared ones, each flagged `propia` and with its author."""
    return _q("""SELECT c.id::text AS id, c.nombre, c.config, c.compartida,
                        (c.usuario_id = %s) AS propia, u.nombre AS autor
                 FROM consulta_export c JOIN usuario u ON u.id = c.usuario_id
                 WHERE c.usuario_id = %s OR c.compartida
                 ORDER BY propia DESC, c.nombre""", (uid, uid))


def load_consulta(cid: str) -> dict | None:
    rows = _q("SELECT config FROM consulta_export WHERE id=%s", (cid,))
    return rows[0]["config"] if rows else None


def delete_consulta(cid: str, uid: str):
    """Delete only if it belongs to the requesting user."""
    _exec("DELETE FROM consulta_export WHERE id=%s AND usuario_id=%s", (cid, uid))
    _log("consulta_export", uid, "eliminar", {"id": cid})
