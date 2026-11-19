"""
Génère un fichier Markdown par tome dans data/gallica_check/.
Chaque fichier contient :
  - les métadonnées Gallica (ark, offset, formule de calcul)
  - la première lettre extraite (chunk_num le plus bas)
  - la date, le titre, l'incipit
  - l'URL Gallica calculée et la vue correspondante

Usage :
  python3 pipeline/gen_gallica_check.py
"""

import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB   = ROOT / "data" / "rag" / "napoleon_clean.sqlite"
OUT  = ROOT / "data" / "gallica_check"
OUT.mkdir(exist_ok=True)

TOME_META: dict[int, dict] = {
    1:  {"ark": "bpt6k63323895",  "offset": 26,  "max_letter": 1471, "total_vues": 878},
    2:  {"ark": "bpt6k6295821n",  "offset": 12,  "max_letter": 1141, "total_vues": 552},
    3:  {"ark": "bpt6k6295853m",  "offset": 29,  "max_letter": 1130, "total_vues": 554},
    4:  {"ark": "bpt6k6332764q",  "offset": 12,  "max_letter": 1255, "total_vues": 806},
    5:  {"ark": "bpt6k96389458",  "offset": 12,  "max_letter": 1387, "total_vues": 814},
    6:  {"ark": "bpt6k6296310f",  "offset": 12,  "max_letter": 1313, "total_vues": 658},
    7:  {"ark": "bpt6k62963462",  "offset": 12,  "max_letter": 1251, "total_vues": 628},
    8:  {"ark": "bpt6k96414306",  "offset": 16,  "max_letter": 1110, "total_vues": 756},
    9:  {"ark": "bpt6k9634014c",  "offset": 27,  "max_letter": 1209, "total_vues": 768},
    10: {"ark": "bpt6k9634014c",  "offset": 13,  "max_letter": 1210, "total_vues": 768},
    11: {"ark": "bpt6k6328251z",  "offset": 12,  "max_letter": 1353, "total_vues": 758},
    12: {"ark": "bpt6k6294040x",  "offset": 15,  "max_letter": 1333, "total_vues": 632},
    13: {"ark": "bpt6k6328645m",  "offset": 12,  "max_letter": 1395, "total_vues": 783},
    14: {"ark": "bpt6k6296790v",  "offset": 22,  "max_letter": 1393, "total_vues": 654},
    15: {"ark": "bpt6k6294033s",  "offset": 20,  "max_letter": 1331, "total_vues": 620},
    16: {"ark": "bpt6k62981230",  "offset": 20,  "max_letter": 1386, "total_vues": 592},
    17: {"ark": "bpt6k96341740",  "offset": 31,  "max_letter": 1302, "total_vues": 754},
    18: {"ark": "bpt6k63285295",  "offset": 12,  "max_letter": 1463, "total_vues": 732},
    19: {"ark": "bpt6k96411995",  "offset": 11,  "max_letter": 1463, "total_vues": 760},
    20: {"ark": "bpt6k9642186v",  "offset": 25,  "max_letter": 1485, "total_vues": 732},
    21: {"ark": "bpt6k9641472j",  "offset": 18,  "max_letter": 1327, "total_vues": 730},
    22: {"ark": "bpt6k6336529t",  "offset": 12,  "max_letter": 1446, "total_vues": 717},
    23: {"ark": "bpt6k9667296p",  "offset": 34,  "max_letter": 1375, "total_vues": 708},
    24: {"ark": "bpt6k63342473",  "offset": 18,  "max_letter": 1640, "total_vues": 770},
    25: {"ark": "bpt6k62962170",  "offset": 30,  "max_letter": 1245, "total_vues": 592},
    26: {"ark": "bpt6k9634170b",  "offset": 18,  "max_letter": 1371, "total_vues": 728},
    27: {"ark": "bpt6k6312497h",  "offset": 11,  "max_letter":  803, "total_vues": 601},
    28: {"ark": "bpt6k6293077n",  "offset": 35,  "max_letter":  803, "total_vues": 360},
}
GALLICA_COVER_OFFSET = 2


def gallica_url(tome: int, chunk_num: int) -> tuple[str, int]:
    """Retourne (url, vue) pour un chunk donné."""
    meta = TOME_META[tome]
    offset     = meta["offset"]
    max_letter = meta["max_letter"]
    total_vues = meta["total_vues"]
    if max_letter <= total_vues:
        vue = chunk_num + offset + GALLICA_COVER_OFFSET
    else:
        vue = round(offset + (chunk_num / max_letter) * (total_vues - offset)) + GALLICA_COVER_OFFSET
    vue = max(1, min(vue, total_vues + GALLICA_COVER_OFFSET))
    url = "https://gallica.bnf.fr/ark:/12148/{ark}/f{vue}".format(
        ark=meta["ark"], vue=vue
    )
    return url, vue


def chunk_num_from_key(chunk_key: str) -> int:
    m = re.match(r"^correspondance_\d+_(\d+)$", chunk_key)
    return int(m.group(1)) if m else 0


def main():
    conn = sqlite3.connect(DB)
    col  = [d[0] for d in conn.execute("SELECT * FROM chunks LIMIT 0").description]

    for tome in range(1, 29):
        prefix = "correspondance_{t}_".format(t=tome)
        prefix_len = len(prefix)

        # Première lettre = chunk_num le plus petit dans ce tome.
        # On échappe les underscores dans LIKE pour éviter que correspondance_1_%
        # matche correspondance_10_..., correspondance_11_... etc.
        escaped_prefix = prefix.replace("_", r"\_")
        rows = conn.execute(
            r"SELECT * FROM chunks WHERE chunk_key LIKE ? ESCAPE '\' "
            "ORDER BY CAST(SUBSTR(chunk_key, ?) AS INTEGER) LIMIT 1",
            (escaped_prefix + "%", prefix_len + 1),
        ).fetchall()

        if not rows:
            print("Tome {:2d} : AUCUN CHUNK".format(tome))
            continue

        d        = dict(zip(col, rows[0]))
        ckey     = d["chunk_key"]
        cnum     = chunk_num_from_key(ckey)
        date_iso = d["date_iso"]
        title    = d.get("title") or "—"
        text     = (d["text"] or "").strip()[:400]
        meta     = TOME_META[tome]
        mode     = "page" if meta["max_letter"] <= meta["total_vues"] else "lettre"
        url, vue = gallica_url(tome, cnum)

        lines = [
            "# Tome {t} — Correspondance de Napoléon".format(t=tome),
            "",
            "## Métadonnées Gallica",
            "- **ARK** : {ark}".format(ark=meta["ark"]),
            "- **URL base** : https://gallica.bnf.fr/ark:/12148/{ark}".format(ark=meta["ark"]),
            "- **offset** (vues avant page 1) : {v}".format(v=meta["offset"]),
            "- **max_letter** : {v}".format(v=meta["max_letter"]),
            "- **total_vues** : {v}".format(v=meta["total_vues"]),
            "- **Mode** : numéro de {m}".format(m=mode),
            "- **GALLICA_COVER_OFFSET** : {v}".format(v=GALLICA_COVER_OFFSET),
            "",
            "## Première lettre extraite",
            "",
            "- **chunk_key** : `{k}`".format(k=ckey),
            "- **Numéro** ({m}) : `{n}`".format(m=mode, n=cnum),
            "- **Date** : `{d}`".format(d=date_iso),
            "- **Titre** : {t}".format(t=title),
            "- **URL Gallica calculée** : [{url}]({url})".format(url=url),
            "  → vue f{vue}".format(vue=vue),
            "",
            "### Début du texte",
            "",
            "> {txt}".format(txt=text),
            "",
            "---",
            "*Si la page Gallica ne correspond pas : noter la vue réelle.",
            "Décalage à corriger = vue réelle − vue calculée (f{vue}).".format(vue=vue),
            "Nouveau offset = {off} + décalage.*".format(off=meta["offset"]),
        ]

        content = "\n".join(lines) + "\n"
        fname   = OUT / "tome_{t:02d}.md".format(t=tome)
        fname.write_text(content, encoding="utf-8")

        print("Tome {:2d} | chunk_key={} | num={:6d} | date={} | vue=f{} | {}".format(
            tome, ckey, cnum, date_iso, vue, title[:50]
        ))

    print("\n✓ 28 fichiers dans {}".format(OUT))


if __name__ == "__main__":
    main()
