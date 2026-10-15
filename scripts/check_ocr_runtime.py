"""Fail early: evaluation must never silently run without barcode dependencies."""
import importlib.metadata,json,subprocess
import cv2,zxingcpp,fitz
from PIL import Image
if __name__=='__main__':
    print(json.dumps({p:importlib.metadata.version(p) for p in
      ('opencv-python-headless','zxing-cpp','Pillow','PyMuPDF','numpy')},sort_keys=True))
    print(subprocess.run(['tesseract','--version'],capture_output=True,text=True,check=True).stdout.splitlines()[0])
    langs=subprocess.run(['tesseract','--list-langs'],capture_output=True,text=True,check=True).stdout.splitlines()
    if 'eng' not in langs:raise RuntimeError('Tesseract English trained data assenti')
