"""Refresh reconciliation helpers in long-lived Streamlit worker processes."""
import importlib
from pathlib import Path
from threading import RLock

_lock = RLock()
_signatures = {}


def current_reconciliation():
    # A page rerun does not necessarily reload Python dependencies on Cloud.
    # Refresh dependencies first and return their current public entry points.
    with _lock:
        for name in ('tab_agents', 'jj_closures', 'jj_reconciliation'):
            module = importlib.import_module(name)
            stat = Path(module.__file__).stat()
            signature = (stat.st_mtime_ns, stat.st_size)
            if _signatures.get(name) != signature:
                importlib.invalidate_caches()
                module = importlib.reload(module)
                _signatures[name] = signature
        return module
