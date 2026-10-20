"""New entry point upgrades sessions retaining the previous refresh function."""
import importlib
from pathlib import Path
from ocr_runtime import _lock

_signatures = {}


def refresh_ocr_modules():
    with _lock:
        for name in ('review_editor','review_exports','product_anchors','region_privacy','sticker_geometry',
                     'label_geometry','linear_label_geometry','label_pipeline',
                     'ai_failures','whole_page_labels','ai_ocr','ocr_review','ocr_repository','ocr_service'):
            module = importlib.import_module(name)
            stat = Path(module.__file__).stat()
            signature = (stat.st_mtime_ns, stat.st_size)
            if _signatures.get(name) != signature:
                importlib.reload(module)
                _signatures[name] = signature
