"""Prépare la carte d'Hérisson (1815) pour le tableau mural : recadrage sur l'Europe et la Méditerranée, et
position des villes et des batailles sur l'image.

La carte gravée (projection conique, méridiens courbes) est calée sur 10 villes repères relevées à l'œil sur
l'image source, à pleine résolution. On ajuste un polynôme du second degré (longitude, latitude) → position sur l'image recadrée,
puis on calcule la position de chaque lieu. La précision (de l'ordre du pour cent) suffit pour un tableau
vu de loin.

Source : Eustache Hérisson, « Carte de l'Europe dans son état actuel, comprenant en outre une partie de l'Asie,
de l'Afrique et la mer Méditerranée », Paris, Desray et J. Goujon, 1815. BnF, Cartes et plans, GE C-8218
(gallica.bnf.fr/ark:/12148/btv1b530930058), domaine public, via Wikimedia Commons (version 3 840 px).

Usage :
    python scripts/build_map_places.py                      # écrit web/src/mapPlaces.js (positions des lieux)
    blender -b -P scripts/build_map_places.py -- --crop     # écrit web/decor/carte_herisson_1815.jpg
    blender -b -P scripts/build_map_places.py -- --check    # même image, un point rouge sur chaque lieu
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "carte_source" / "herisson_1815_3840.jpg"     # téléchargée, hors dépôt
OUT_IMAGE = ROOT / "web" / "decor" / "carte_herisson_1815.jpg"
OUT_JS = ROOT / "web" / "src" / "mapPlaces.js"

# Recadrage en pixels de l'image source (3 840 px) : du Portugal à l'est de Moscou, de Saint-Pétersbourg au
# bord inférieur de la gravure (l'Égypte), sans le cartouche ni les légendes du coin supérieur gauche.
CROP = (540, 900, 2880, 2650)
OUT_WIDTH = 1800

# Villes repères : (longitude, latitude) réelles → position relevée sur l'image source, à pleine résolution
CONTROL = {
    "Paris": ((2.35, 48.86), (1207, 1524)),
    "Londres": ((-0.13, 51.5), (1206, 1349)),
    "Madrid": ((-3.7, 40.42), (833, 1900)),
    "Rome": ((12.5, 41.9), (1505, 1967)),
    "Vienne": ((16.37, 48.21), (1694, 1660)),
    "Moscou": ((37.62, 55.75), (2366, 1198)),
    "Constantinople": ((28.98, 41.01), (2158, 2011)),
    "Le Caire": ((31.24, 30.04), (2325, 2580)),
    "Alexandrie": ((29.92, 31.2), (2195, 2530)),
    "Saint-Jean-d'Acre": ((35.07, 32.93), (2478, 2420)),
}

# Lieux affichés : toujours (capitales) ou quand leur région s'éclaire (batailles et étapes)
PLACES = {
    # capitales
    "Paris": (2.35, 48.86, None), "Londres": (-0.13, 51.5, None), "Madrid": (-3.7, 40.42, None),
    "Lisbonne": (-9.14, 38.72, None), "Rome": (12.5, 41.9, None), "Vienne": (16.37, 48.21, None),
    "Berlin": (13.4, 52.52, None), "Varsovie": (21.01, 52.23, None), "Moscou": (37.62, 55.75, None),
    "Constantinople": (28.98, 41.01, None), "Le Caire": (31.24, 30.04, None),
    # régions de l'archiviste
    "Ajaccio": (8.74, 41.92, "corse"), "Toulon": (5.93, 43.12, "france"), "Fontainebleau": (2.7, 48.4, "france"),
    "Milan": (9.19, 45.46, "italie"), "Lodi": (9.5, 45.31, "italie"), "Arcole": (11.27, 45.36, "italie"),
    "Rivoli": (10.81, 45.57, "italie"), "Marengo": (8.68, 44.88, "italie"),
    "Alexandrie": (29.92, 31.2, "egypte"), "Aboukir": (30.06, 31.32, "egypte"),
    "Les Pyramides": (31.13, 29.98, "egypte"), "Saint-Jean-d'Acre": (35.07, 32.93, "egypte"),
    "Saragosse": (-0.88, 41.65, "espagne"), "Baylen": (-3.77, 38.1, "espagne"),
    "Ulm": (9.99, 48.4, "autriche"), "Austerlitz": (16.76, 49.15, "autriche"), "Wagram": (16.56, 48.3, "autriche"),
    "Iéna": (11.59, 50.93, "prusse"), "Eylau": (20.64, 54.39, "pologne"), "Friedland": (21.01, 54.45, "pologne"),
    "Leipzig": (12.37, 51.34, "allemagne"), "Dresde": (13.74, 51.05, "allemagne"),
    "Smolensk": (32.05, 54.78, "russie"), "La Moskowa": (35.82, 55.52, "russie"),
    "Bérézina": (28.8, 54.3, "russie"),
    "Waterloo": (4.4, 50.68, "belgique"), "Ligny": (4.58, 50.51, "belgique"),
    "Portoferraio": (10.33, 42.81, "elbe"),
}


def features(lon, lat):
    lon, lat = np.asarray(lon, float), np.asarray(lat, float)
    return np.stack([np.ones_like(lon), lon, lat, lon * lon, lat * lat, lon * lat], axis=-1)


def fit():
    ll = np.array([c[0] for c in CONTROL.values()])
    xy = np.array([c[1] for c in CONTROL.values()], float)
    A = features(ll[:, 0], ll[:, 1])
    cx, *_ = np.linalg.lstsq(A, xy[:, 0], rcond=None)
    cy, *_ = np.linalg.lstsq(A, xy[:, 1], rcond=None)
    pred = np.stack([A @ cx, A @ cy], axis=-1)
    err = np.hypot(*(pred - xy).T)
    print("Écart des repères (px, image source) :", {k: round(float(e), 1) for k, e in zip(CONTROL, err)})
    return cx, cy


def residuals(cx, cy):
    ll = np.array([c[0] for c in CONTROL.values()])
    xy = np.array([c[1] for c in CONTROL.values()], float)
    A = features(ll[:, 0], ll[:, 1])
    return ll, xy - np.stack([A @ cx, A @ cy], axis=-1)


def to_uv(cx, cy, lon, lat):
    """Position (0-1) sur l'image recadrée : u de gauche à droite, v de haut en bas.
    Polynôme, puis correction locale : l'écart de chaque repère est réparti sur ses voisins (pondération en
    inverse du carré de la distance), si bien que les repères tombent exactement à leur place."""
    f = features(lon, lat)
    x, y = float(f @ cx), float(f @ cy)
    ll, res = residuals(cx, cy)
    d2 = (ll[:, 0] - lon) ** 2 + (ll[:, 1] - lat) ** 2
    if d2.min() < 1e-9:
        x, y = x + res[d2.argmin(), 0], y + res[d2.argmin(), 1]
    else:
        w = 1 / d2
        x, y = x + float(w @ res[:, 0] / w.sum()), y + float(w @ res[:, 1] / w.sum())
    x0, y0, x1, y1 = CROP
    return (x - x0) / (x1 - x0), (y - y0) / (y1 - y0)


def write_js(cx, cy):
    places = []
    for name, (lon, lat, region) in PLACES.items():
        u, v = to_uv(cx, cy, lon, lat)
        places.append({"name": name, "u": round(u, 4), "v": round(v, 4), "region": region})
    OUT_JS.write_text(
        "// Généré par scripts/build_map_places.py : position (u, v de 0 à 1, v vers le bas) des lieux sur\n"
        "// web/decor/carte_herisson_1815.jpg. region : null = toujours affiché, sinon région de l'archiviste.\n"
        f"export const MAP_PLACES = {json.dumps(places, ensure_ascii=False, indent=2)}\n", encoding="utf-8")
    print(f"{len(places)} lieux → {OUT_JS.relative_to(ROOT)}")


def crop_image(cx, cy, check=False):
    import bpy  # noqa: PLC0415 — seulement dans Blender
    img = bpy.data.images.load(str(SOURCE))
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(h, w, 4)[::-1]                          # haut de l'image en premier
    x0, y0, x1, y1 = CROP
    sub = np.ascontiguousarray(px[y0:y1, x0:x1])
    if check:                                               # points rouges sur chaque lieu, pour vérifier le calage
        for name, (lon, lat, _) in PLACES.items():
            u, v = to_uv(cx, cy, lon, lat)
            cxp, cyp = int(u * (x1 - x0)), int(v * (y1 - y0))
            if 6 <= cxp < x1 - x0 - 6 and 6 <= cyp < y1 - y0 - 6:
                sub[cyp - 6:cyp + 6, cxp - 6:cxp + 6] = (1, 0, 0, 1)
    out = bpy.data.images.new("carte", x1 - x0, y1 - y0)
    out.pixels.foreach_set(sub[::-1].ravel())
    out.scale(OUT_WIDTH, round(OUT_WIDTH * (y1 - y0) / (x1 - x0)))
    scn = bpy.context.scene
    scn.render.image_settings.file_format = "JPEG"
    scn.render.image_settings.quality = 85
    scn.view_settings.view_transform = "Standard"
    target = OUT_IMAGE.with_name("carte_verification.jpg") if check else OUT_IMAGE
    out.save_render(str(target), scene=scn)
    print("IMAGE", target, out.size[:])


cx, cy = fit()
if "--crop" in sys.argv or "--check" in sys.argv:
    crop_image(cx, cy, check="--check" in sys.argv)
else:
    write_js(cx, cy)
