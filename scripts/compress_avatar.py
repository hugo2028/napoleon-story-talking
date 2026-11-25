"""Allège web/avatar/avatar.glb : réencode ses textures PNG en JPEG (et en réduit certaines), sans toucher
à la géométrie, aux visèmes (morph targets) ni aux animations.

Les textures font l'essentiel du poids (5 PNG de 4 à 5 Mo). Le JPEG fait partie de glTF 2.0 de base :
aucune extension ni décodeur supplémentaire n'est nécessaire côté three.js.

L'original est gardé dans data/avatar/avatar.orig.glb (hors dépôt) ; le script repart toujours de lui,
on peut donc le relancer avec d'autres réglages.

Usage (Blender sert seulement à lire et écrire les images) :
    blender -b --factory-startup -P scripts/compress_avatar.py
    blender -b --factory-startup -P scripts/compress_avatar.py -- --info    # dimensions et alpha, sans écrire
"""
from __future__ import annotations

import json
import shutil
import struct
import sys
import tempfile
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parent.parent
GLB = ROOT / "web" / "avatar" / "avatar.glb"
ORIG = ROOT / "data" / "avatar" / "avatar.orig.glb"   # hors de web/ : Vite surveille ce dossier

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
INFO = "--info" in argv

# Taille maximale (px) et qualité JPEG par texture (les originaux font 2048 px) : seul le relief des
# accessoires (chapeau, épée, médaille), peu visible, est réduit.
SETTINGS = {
    "napoleon_body_Basecolor": (2048, 90),
    "napoleon_body_Normal": (2048, 92),
    "napoleon_clothes_Basecolor": (2048, 88),
    "napoleon_things_Basecolor": (2048, 88),
    "napoleon_things_Normal": (1024, 92),
}
DEFAULT = (2048, 88)


def read_glb(path: Path):
    b = path.read_bytes()
    magic, version, _ = struct.unpack_from("<III", b, 0)
    assert magic == 0x46546C67 and version == 2, "GLB 2.0 attendu"
    jlen, jtype = struct.unpack_from("<II", b, 12)
    assert jtype == 0x4E4F534A
    j = json.loads(b[20:20 + jlen])
    off = 20 + jlen
    blen, btype = struct.unpack_from("<II", b, off)
    assert btype == 0x004E4942
    return j, b[off + 8: off + 8 + blen]


def write_glb(path: Path, j: dict, binary: bytes):
    js = json.dumps(j, separators=(",", ":")).encode("utf-8")
    js += b" " * (-len(js) % 4)
    binary += b"\0" * (-len(binary) % 4)
    total = 12 + 8 + len(js) + 8 + len(binary)
    with path.open("wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, total))
        f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        f.write(struct.pack("<II", len(binary), 0x004E4942) + binary)


def view_bytes(j, binary, idx):
    v = j["bufferViews"][idx]
    o = v.get("byteOffset", 0)
    return binary[o: o + v["byteLength"]]


def main():
    if not ORIG.exists():
        shutil.copy2(GLB, ORIG)
        print(f"Original sauvegardé : {ORIG}")
    j, binary = read_glb(ORIG)
    opaque = all(m.get("alphaMode", "OPAQUE") == "OPAQUE" for m in j.get("materials", []))
    tmp = Path(tempfile.mkdtemp(prefix="avatar_tex_"))
    new_images = {}
    for i, im in enumerate(j.get("images", [])):
        name = im.get("name") or f"image_{i}"
        src = tmp / f"{i}.png"
        src.write_bytes(view_bytes(j, binary, im["bufferView"]))
        img = bpy.data.images.load(str(src))
        w, h = img.size
        print(f"{name}: {w}x{h}, {img.channels} canaux, {len(src.read_bytes()) / 1e6:.2f} Mo")
        if INFO:
            continue
        max_px, quality = SETTINGS.get(name, DEFAULT)
        if max(w, h) > max_px:
            img.scale(max_px * w // max(w, h), max_px * h // max(w, h))
        dst = tmp / f"{i}.jpg"
        # save_render applique les réglages d'image de la scène (format, qualité) ; transformation
        # « Standard » : les octets sRGB (couleur comme relief) sont écrits tels quels.
        settings = bpy.context.scene.render.image_settings
        settings.file_format = "JPEG"
        settings.color_mode = "RGB"
        settings.quality = quality
        bpy.context.scene.view_settings.view_transform = "Standard"
        bpy.context.scene.view_settings.look = "None"
        bpy.context.scene.view_settings.exposure = 0
        bpy.context.scene.view_settings.gamma = 1
        img.save_render(str(dst), scene=bpy.context.scene)
        new_images[i] = dst.read_bytes()
        print(f"  → {img.size[0]}x{img.size[1]} JPEG q{quality} : {len(new_images[i]) / 1e6:.2f} Mo")
    if INFO:
        print("Matériaux tous opaques :", opaque)
        return
    if not opaque:
        raise SystemExit("Un matériau utilise la transparence : le JPEG la perdrait, compression annulée.")

    # Reconstruit le buffer : vues inchangées recopiées, vues d'images remplacées, décalages recalculés
    image_views = {im["bufferView"]: i for i, im in enumerate(j["images"])}
    out = bytearray()
    for vi, v in enumerate(j["bufferViews"]):
        data = new_images[image_views[vi]] if vi in image_views else view_bytes(j, binary, vi)
        out += b"\0" * (-len(out) % 4)          # alignement 4 octets (exigé pour les accesseurs)
        v["byteOffset"] = len(out)
        v["byteLength"] = len(data)
        out += data
    for i in new_images:
        j["images"][i]["mimeType"] = "image/jpeg"
    j["buffers"][0]["byteLength"] = len(out)
    write_glb(GLB, j, bytes(out))
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"GLB : {ORIG.stat().st_size / 1e6:.1f} Mo → {GLB.stat().st_size / 1e6:.1f} Mo")


main()
