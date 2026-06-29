"""Supabase config for the admin console (server-side only).
Reads from env, then catalog-review-app/.env, then Planning/supabase/.env.
The service-role key is SECRET — it never leaves the server (Streamlit) process.
"""
import os
import pathlib

BASE_DIR = pathlib.Path(__file__).parent


def _load() -> dict:
    vals: dict = {}
    for p in (BASE_DIR / ".env", BASE_DIR.parent / "Planning" / "supabase" / ".env"):
        if p.exists():
            for raw in p.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    vals.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return vals


_ENV = _load()


def cfg(key: str, default=None):
    return os.environ.get(key) or _ENV.get(key, default)


SUPABASE_URL = cfg("SUPABASE_URL")
SUPABASE_ANON_KEY = cfg("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE_KEY = cfg("SUPABASE_SERVICE_ROLE_KEY")
