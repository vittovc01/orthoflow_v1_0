"""Refresh the complete review dependency chain before importing page symbols.

A new entry module also upgrades sessions caching the previous loader itself.
"""
import importlib
from pathlib import Path
from ocr_runtime import _lock

_signatures={}


def refresh_ocr_modules():
    with _lock:
        for name in ('region_privacy','sticker_geometry','label_geometry','linear_label_geometry',
                     'label_pipeline','ocr_review','ocr_repository','ocr_service'):
            module=importlib.import_module(name)
            stat=Path(module.__file__).stat()
            signature=(stat.st_mtime_ns,stat.st_size)
            if _signatures.get(name)!=signature:
                importlib.reload(module)
                _signatures[name]=signature
