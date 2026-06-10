
import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

def get_supabase():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        return None
    return create_client(url, key)

def supabase_enabled():
    return os.getenv("USE_SUPABASE", "false").lower() == "true" and get_supabase() is not None
