"""Refresh TAB dependencies in existing Streamlit workers after deployments."""
import importlib
from pathlib import Path
from jj_runtime import _lock,current_reconciliation

_signatures={}


def current_tab():
    with _lock:
        current_reconciliation()
        changed=False
        for name in ('tab_verified_prices','tab_management','tab_management_ui','tab_price_anomalies'):
            module=importlib.import_module(name)
            stat=Path(module.__file__).stat()
            signature=(stat.st_mtime_ns,stat.st_size)
            # Reload downstream import bindings even when only a dependency changed.
            if changed or _signatures.get(name)!=signature:
                importlib.invalidate_caches()
                module=importlib.reload(module)
                _signatures[name]=signature
                changed=True
        if changed:
            importlib.import_module('tab_management_ui').refresh()
        return module


def current_management():
    current_tab()
    return importlib.import_module('tab_management_ui')
