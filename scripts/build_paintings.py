"""Tableaux du tableau mural : versions réduites des œuvres du catalogue napoleon-corpus/metadata/tableaux.json.

Les images d'origine (Wikimedia Commons, domaine public, versions de 1920 px) sont dans data/images_source/,
hors des dépôts ; ce script les réduit à 1400 px au plus et les écrit en JPEG dans web/decor/tableaux/<id>.jpg.
Blender sert seulement à lire, réduire et écrire les images.

Usage :
    blender -b --factory-startup -P scripts/build_paintings.py
"""
import json
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "images_source"
OUT = ROOT / "web" / "decor" / "tableaux"
MAX_SIDE = 1400

OUT.mkdir(parents=True, exist_ok=True)
scn = bpy.context.scene
scn.render.image_settings.file_format = "JPEG"
scn.render.image_settings.quality = 85
scn.view_settings.view_transform = "Standard"
for t in json.loads((ROOT / "napoleon-corpus" / "metadata" / "tableaux.json").read_text(encoding="utf-8")):
    src = next(SRC.glob(f"{t['id']}.*"))
    img = bpy.data.images.load(str(src))
    w, h = img.size
    k = min(1.0, MAX_SIDE / max(w, h))
    img.scale(max(1, round(w * k)), max(1, round(h * k)))
    path = OUT / f"{t['id']}.jpg"
    img.save_render(str(path), scene=scn)
    print(f"{t['id']}: {img.size[0]}x{img.size[1]} → {path.stat().st_size // 1000} Ko")
