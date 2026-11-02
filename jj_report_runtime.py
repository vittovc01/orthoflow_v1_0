"""Refresh reporting helpers after reconciliation in existing Cloud sessions."""
import importlib
from pathlib import Path
from jj_runtime import _lock, current_reconciliation

_signature=None


def current_reports():
    global _signature
    with _lock:
        current_reconciliation()
        module=importlib.import_module('jj_report')
        stat=Path(module.__file__).stat()
        signature=(stat.st_mtime_ns,stat.st_size)
        if _signature!=signature:
            module=importlib.reload(module)
            _signature=signature
        return module
