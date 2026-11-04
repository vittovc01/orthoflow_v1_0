"""Load the price registry after the current TAB dependencies."""
import importlib
from pathlib import Path
from jj_runtime import _lock
from tab_runtime import current_tab,_signatures


def current_registry():
    with _lock:
        current_tab()
        module=importlib.import_module('price_registry')
        stat=Path(module.__file__).stat()
        signature=(stat.st_mtime_ns,stat.st_size,tuple(sorted(_signatures.items())))
        # Keep this signature separate from dependency signatures.
        if getattr(current_registry,'signature',None)!=signature:
            module=importlib.reload(module)
            current_registry.signature=signature
        return module
