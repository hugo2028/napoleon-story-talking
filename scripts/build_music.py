"""Extraits musicaux de la scène : un par ambiance, découpés dans des enregistrements libres de droits.

Les enregistrements d'origine (Wikimedia Commons, domaine public ou CC0) sont dans data/musique_source/,
hors des dépôts ; les extraits sont écrits dans web/music/<ambiance>.mp3, avec un fondu au début et à la fin
pour boucler sans à-coup. Blender sert seulement à lire et encoder le son (module aud, avec FFmpeg).

Usage :
    blender -b --factory-startup -P scripts/build_music.py

Crédits (aussi dans docs/SCENE.md) :
- triomphale : Beethoven, Symphonie n° 3 « Héroïque », I. Allegro con brio — Musopen Symphony, CC0
- melancolique : Beethoven, Symphonie n° 3, II. Marche funèbre — Musopen Symphony, CC0
- marseillaise : Rouget de Lisle, La Marseillaise — Musique de la Garde républicaine, domaine public
- tendre : Mozart, Sérénade n° 13 K. 525 « Petite musique de nuit », Romance — Musopen, domaine public
- solennelle : Haydn, La Création, « Représentation du chaos » — St Matthew's Choir, Phiroz Dalal, domaine public
"""
from pathlib import Path

import aud

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "musique_source"
OUT = ROOT / "web" / "music"
FADE = 3.0          # secondes de fondu au début et à la fin
RATE = 44100

# ambiance : (fichier source, début (s), durée (s))
EXTRAITS = {
    "triomphale": ("eroica_1.ogg", 0, 120),
    "melancolique": ("eroica_2.ogg", 0, 120),
    "marseillaise": ("marseillaise.ogg", 0, 140),
    "tendre": ("mozart_romanze.ogg", 0, 120),
    "solennelle": ("haydn_chaos.oga", 0, 120),
}

OUT.mkdir(parents=True, exist_ok=True)
for name, (src, start, length) in EXTRAITS.items():
    sound = aud.Sound(str(SRC / src)).resample(RATE, False)
    total = min(length, sound.length / RATE - start)
    sound = sound.limit(start, start + total).fadein(0, FADE).fadeout(total - FADE, FADE)
    path = OUT / f"{name}.mp3"
    sound.write(str(path), rate=RATE, channels=aud.CHANNELS_STEREO, format=aud.FORMAT_S16,
                container=aud.CONTAINER_MP3, codec=aud.CODEC_MP3, bitrate=96000)
    print(f"{name}: {total:.0f} s -> {path.name} ({path.stat().st_size / 1e6:.1f} Mo)")
