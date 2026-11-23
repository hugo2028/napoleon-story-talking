"""Vue Gallica exacte de chaque lettre, d'après les tables des matières des tomes.

Les tables viennent du service officiel « Toc » de l'API Document de Gallica
(https://api.bnf.fr/fr/api-document-de-gallica), enregistrées à la main depuis le
navigateur (Gallica bloque les appels par script) :

    https://gallica.bnf.fr/services/Toc?ark=ark:/12148/<ark du tome>
    → napoleon-corpus/gallica_services/gallica_table_tome_<n>.xml

Chaque ligne de table donne le numéro de la lettre et l'image où elle commence
(« 6332389/000405.TIF » = vue f405). Quelques lettres manquent dans les tables de
Gallica (tome 1 : n° 438 à 458) ; on les place entre leurs deux voisines connues.

Sortie : napoleon-corpus/metadata/gallica_pages.json  {"1": {"468": 405, ...}, ...}

    python scripts/build_gallica_pages.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "napoleon-corpus" / "gallica_services"
OUT = ROOT / "napoleon-corpus" / "metadata" / "gallica_pages.json"

ROW_RE = re.compile(r"<row>(.*?)</row>", re.S)
FIRST_CELL_RE = re.compile(r"<cell>\s*(\d+)\s*</cell>")
VUE_RE = re.compile(r"/(\d+)\.(?:TIF|tif|jp2|JP2)\)?\"")


MAX_GAP = 40   # au-delà, trou trop grand pour placer les lettres entre voisines : on n'invente rien


def read_table(path: Path) -> tuple[dict[int, int], int]:
    """Numéro de lettre → vue. Renvoie aussi le nombre de lignes écartées (OCR douteux)."""
    raw = path.read_bytes()
    m = re.search(rb'encoding="([^"]+)"', raw[:200])
    text = raw.decode(m.group(1).decode() if m else "utf-8", errors="replace")
    rows: list[tuple[int, int]] = []
    for row in ROW_RE.findall(text):
        num, vue = FIRST_CELL_RE.match(row), VUE_RE.search(row)
        if num and vue:
            rows.append((int(num.group(1)), int(vue.group(1))))
    kept = _increasing(rows)
    vues: dict[int, int] = {}
    for n, v in kept:
        vues.setdefault(n, v)
    return vues, len(rows) - len(kept)


def _increasing(rows: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Plus longue suite où numéros et vues croissent ensemble, dans l'ordre de la table.

    Écarte les numéros mal lus par l'OCR (« 104499 » pour « 10449 », « 3965 » pour « 5965 »).
    """
    if not rows:
        return []
    best = [1] * len(rows)
    prev = [-1] * len(rows)
    for i, (n, v) in enumerate(rows):
        for j in range(max(0, i - 200), i):     # une erreur d'OCR ne couvre jamais 200 lignes
            if rows[j][0] < n and rows[j][1] <= v and best[j] + 1 > best[i]:
                best[i], prev[i] = best[j] + 1, j
    i = max(range(len(rows)), key=best.__getitem__)
    out = []
    while i >= 0:
        out.append(rows[i])
        i = prev[i]
    return out[::-1]


def fill_gaps(vues: dict[int, int]) -> tuple[dict[int, int], int]:
    """Lettres absentes de la table : entre la précédente et la suivante connues (petits trous)."""
    nums = sorted(vues)
    filled = dict(vues)
    added = 0
    for a, b in zip(nums, nums[1:]):
        if b - a - 1 > MAX_GAP:
            continue
        for n in range(a + 1, b):
            filled[n] = round(vues[a] + (vues[b] - vues[a]) * (n - a) / (b - a))
            added += 1
    return filled, added


def main() -> int:
    tables = sorted(TABLES.glob("gallica_table_tome_*.xml"),
                    key=lambda p: int(re.search(r"(\d+)", p.stem.rsplit("_", 1)[-1]).group(1)))
    if not tables:
        print(f"Aucune table dans {TABLES}")
        return 1
    result: dict[str, dict[str, int]] = {}
    for path in tables:
        tome = int(path.stem.rsplit("_", 1)[-1])
        vues, dropped = read_table(path)
        if not vues:
            print(f"tome {tome:>2} : aucune lettre lue dans {path.name}")
            continue
        filled, added = fill_gaps(vues)
        result[str(tome)] = {str(n): filled[n] for n in sorted(filled)}
        print(f"tome {tome:>2} : {len(vues)} lettres dans la table, {added} placées entre voisines, "
              f"{dropped} ligne(s) écartée(s) (n° {min(filled)}–{max(filled)})")
    OUT.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"→ {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
