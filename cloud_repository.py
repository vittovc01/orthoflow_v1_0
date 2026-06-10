
"""
Repository Supabase opzionale.
La app v0.5 mantiene SQLite locale come fallback.
Questo file permette di migrare gradualmente i moduli a Supabase.
"""

from supabase_client import get_supabase, supabase_enabled

def insert_row(table: str, data: dict):
    if not supabase_enabled():
        return None
    sb = get_supabase()
    return sb.table(table).insert(data).execute()

def select_all(table: str, order_by: str = "id", desc: bool = True):
    if not supabase_enabled():
        return None
    sb = get_supabase()
    q = sb.table(table).select("*")
    if order_by:
        q = q.order(order_by, desc=desc)
    return q.execute()

def upload_document(bucket: str, path: str, data: bytes, content_type: str | None = None):
    if not supabase_enabled():
        return None
    sb = get_supabase()
    opts = {}
    if content_type:
        opts["content-type"] = content_type
    return sb.storage.from_(bucket).upload(path, data, file_options=opts)
