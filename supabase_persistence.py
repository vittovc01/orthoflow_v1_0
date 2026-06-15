from pathlib import Path
import os
from typing import Optional

try:
    import streamlit as st
except Exception:
    st = None

try:
    from supabase import create_client
except Exception:
    create_client = None


DEFAULT_BUCKET = "orthoflow-backup"
DEFAULT_OBJECT = "orthoflow.db"


def _secret(name: str, default: Optional[str] = None):
    try:
        if st is not None and name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.getenv(name, default)


def _enabled() -> bool:
    return str(_secret("USE_SUPABASE", "false")).lower() == "true"


def _client():
    if not _enabled() or create_client is None:
        return None

    url = _secret("SUPABASE_URL")
    key = _secret("SUPABASE_SERVICE_KEY") or _secret("SUPABASE_ANON_KEY")
    if not url or not key:
        return None
    return create_client(str(url).rstrip("/"), str(key))


def _bucket_name() -> str:
    return str(_secret("SUPABASE_BUCKET", DEFAULT_BUCKET))


def _object_name() -> str:
    return str(_secret("SUPABASE_DB_OBJECT", DEFAULT_OBJECT))


def ensure_bucket():
    sb = _client()
    if sb is None:
        return False
    bucket = _bucket_name()
    try:
        buckets = sb.storage.list_buckets()
        names = []
        for b in buckets:
            if isinstance(b, dict):
                names.append(b.get("name"))
            else:
                names.append(getattr(b, "name", None))
        if bucket not in names:
            sb.storage.create_bucket(bucket, options={"public": False})
        return True
    except Exception:
        return False


def download_db_if_available(db_path: Path) -> bool:
    """
    Scarica il database da Supabase Storage solo se localmente non esiste
    oppure è quasi vuoto. Evita di sovrascrivere dati locali appena inseriti.
    """
    if not _enabled():
        return False

    db_path = Path(db_path)
    if db_path.exists() and db_path.stat().st_size > 4096:
        return False

    sb = _client()
    if sb is None:
        return False

    try:
        ensure_bucket()
        data = sb.storage.from_(_bucket_name()).download(_object_name())
        if data:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            db_path.write_bytes(data)
            return True
    except Exception:
        return False
    return False


def upload_db_if_available(db_path: Path = Path("data/orthoflow.db")) -> bool:
    """
    Carica il database su Supabase Storage.
    Da chiamare dopo import/salvataggi importanti.
    """
    if not _enabled():
        return False

    db_path = Path(db_path)
    if not db_path.exists() or db_path.stat().st_size <= 0:
        return False

    sb = _client()
    if sb is None:
        return False

    try:
        ensure_bucket()
        data = db_path.read_bytes()
        try:
            sb.storage.from_(_bucket_name()).upload(
                _object_name(),
                data,
                file_options={
                    "content-type": "application/octet-stream",
                    "upsert": "true",
                },
            )
        except Exception:
            sb.storage.from_(_bucket_name()).update(
                _object_name(),
                data,
                file_options={
                    "content-type": "application/octet-stream",
                    "upsert": "true",
                },
            )
        return True
    except Exception:
        return False
