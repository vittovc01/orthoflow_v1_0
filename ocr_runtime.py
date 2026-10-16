"""Refresh changed OCR dependencies in long-lived Streamlit sessions."""
import importlib
from pathlib import Path
from threading import RLock

_lock=RLock()
_signatures={}


def current_label_pipeline():
    with _lock:
        for name in ('region_privacy','sticker_geometry','label_geometry','linear_label_geometry','label_pipeline'):
            module=importlib.import_module(name)
            stat=Path(module.__file__).stat()
            signature=(stat.st_mtime_ns,stat.st_size)
            if _signatures.get(name)!=signature:
                importlib.reload(module)
                _signatures[name]=signature
        return importlib.import_module('label_pipeline')
