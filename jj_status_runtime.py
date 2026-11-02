"""Refresh intervention status helpers in an existing Streamlit worker."""
import importlib
from pathlib import Path
from jj_runtime import _lock
from jj_report_runtime import current_reports

_signature=None

def current_status():
    global _signature
    with _lock:
        current_reports()
        module=importlib.import_module('jj_intervention_status')
        stat=Path(module.__file__).stat()
        signature=(stat.st_mtime_ns,stat.st_size)
        if _signature!=signature:
            module=importlib.reload(module)
            _signature=signature
        return module
