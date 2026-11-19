"""
Extrait les lettres manquantes de la Correspondance après correction de DATE_HINT_RE.

Usage:
  python3 pipeline/extract_missing_letters.py
  python3 pipeline/extract_missing_letters.py --dry-run
  python3 pipeline/extract_missing_letters.py --tomes 11

Produit : data/missing/raw_tome_NN.jsonl
Format  : identique à napoleon-corpus/cleaned/correspondance/correspondance_N.jsonl
          (compatible avec batch_clean.py --glob "data/missing/raw_tome_*.jsonl")
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

from extract_correspondances import extract_correspondance_file

SOURCE_DIR = ROOT / "napoleon-corpus" / "sources" / "texts" / "correspondances" / "32 tomes"
CLEANED_DIR = ROOT / "napoleon-corpus" / "cleaned" / "correspondance"
OUTPUT_DIR  = ROOT / "data" / "missing"

AFFECTED_TOMES = [4, 5, 6, 8, 9, 11, 12, 14, 15, 23, 27, 28]

PERIODS = [
    (1769, 1792, "Jeunesse"),
    (1793, 1795, "Révolution & Toulon"),
    (1796, 1797, "Première campagne d'Italie"),
    (1798, 1799, "Campagne d'Égypte"),
    (1800, 1804, "Consulat"),
    (1805, 1814, "Empire"),
    (1815, 1821, "Sainte-Hélène"),
]


def get_period(year: int) -> str:
    for y1, y2, label in PERIODS:
        if y1 <= year <= y2:
            return label
    return "Inconnu"


def load_existing_letter_ids(tome: int) -> set[int]:
    """Retourne les letter_id déjà présents dans le JSONL nettoyé du tome."""
    path = CLEANED_DIR / f"correspondance_{tome}.jsonl"
    if not path.exists():
        return set()
    ids: set[int] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            lid = row.get("letter_id")
            if lid is not None:
                ids.add(int(lid))
        except Exception:
            pass
    return ids


def extract_for_tome(tome: int, dry_run: bool = False) -> list[dict]:
    """
    Extrait les nouvelles lettres pour un tome donné.
    Retourne la liste des nouvelles entrées (non encore dans le JSONL nettoyé).
    """
    html_path = SOURCE_DIR / f"correspondance_{tome}.html"
    if not html_path.exists():
        print(f"  [WARN] Source introuvable : {html_path}")
        return []

    existing_ids = load_existing_letter_ids(tome)
    print(f"  Existants : {len(existing_ids)} letter_ids dans correspondance_{tome}.jsonl")

    passages = extract_correspondance_file(html_path)
    print(f"  Extraits  : {len(passages)} passages depuis {html_path.name}")

    new_entries: list[dict] = []
    seq = 0
    for p in passages:
        lid = p.get("letter_id")
        if lid is None or int(lid) in existing_ids:
            continue
        # Nouvelle lettre : créer l'entrée au format batch_clean
        seq += 1
        temp_id = f"correspondance_{tome:02d}_miss_{int(lid):05d}_{p.get('part_index', 1):02d}"
        entry = {
            "id":             temp_id,
            "source_type":    "correspondance",
            "letter_id":      int(lid),
            "part_index":     p.get("part_index", 1),
            "part_count":     p.get("part_count", 1),
            "title":          p.get("section", "")[:180],
            "date":           p.get("date_text") or p.get("date"),   # texte brut pour le LLM
            "date_text":      p.get("date_text") or p.get("date"),
            "place":          p.get("place"),
            "recipient":      p.get("recipient"),
            "recipient_raw":  p.get("recipient_raw"),
            "recipient_place": p.get("recipient_place"),
            "theme":          p.get("theme"),
            "period":         None,   # le LLM déterminera depuis date_text
            "word_count":     p.get("word_count", 0),
            "text":           p.get("text", ""),
            # Métadonnées pour la reconstruction du chunk_key
            "_tome":          tome,
        }
        new_entries.append(entry)

    return new_entries


def main():
    parser = argparse.ArgumentParser(description="Extraction des lettres manquantes")
    parser.add_argument("--dry-run", action="store_true",
                        help="Afficher le récapitulatif sans écrire les fichiers")
    parser.add_argument("--tomes", nargs="+", type=int, default=None,
                        help="Tomes à traiter (défaut : tous les tomes affectés)")
    args = parser.parse_args()

    tomes = args.tomes or AFFECTED_TOMES
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    total_new = 0
    shifts: dict[int, int] = {}   # {tome: nb_nouveaux_chunks}

    for tome in tomes:
        print(f"\n=== Tome {tome} ===")
        entries = extract_for_tome(tome, dry_run=args.dry_run)

        n = len(entries)
        shifts[tome] = n
        total_new += n

        if n == 0:
            print(f"  → Aucune nouvelle lettre trouvée")
            continue

        unique_letters = len({e["letter_id"] for e in entries})
        print(f"  → {n} nouveaux chunks ({unique_letters} lettres uniques)")

        if not args.dry_run:
            out_path = OUTPUT_DIR / f"raw_tome_{tome:02d}.jsonl"
            with out_path.open("w", encoding="utf-8") as f:
                for entry in entries:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            print(f"  → Écrit : {out_path}")

    print(f"\n{'='*50}")
    print(f"Total : {total_new} nouveaux chunks dans {len([t for t in tomes if shifts.get(t, 0) > 0])} tomes")
    print("\nRécapitulatif par tome (shifts) :")
    for tome, n in sorted(shifts.items()):
        if n > 0:
            print(f"  Tome {tome:2d} : +{n} chunks")

    # Écrire le fichier shifts.json pour les étapes suivantes
    if not args.dry_run and total_new > 0:
        shifts_path = OUTPUT_DIR / "shifts.json"
        shifts_path.write_text(json.dumps(shifts, indent=2), encoding="utf-8")
        print(f"\n✓ Shifts enregistrés : {shifts_path}")
        print("\nProchaines étapes :")
        print("  1. Nettoyer avec batch_clean.py :")
        print('     python3 pipeline/batch_clean.py prepare --glob "data/missing/raw_tome_*.jsonl" --output-dir data/missing/batch')
        print("     python3 pipeline/batch_clean.py submit")
        print("     python3 pipeline/batch_clean.py status")
        print("     python3 pipeline/batch_clean.py process --output-dir data/missing")
        print("     (Les batches seront nommés batch_all_*.jsonl — pas de conflit avec les batches existants)")

        print("  2. Renuméroter les chunks existants :")
        print("     python3 pipeline/renumber_chunks.py")
        print("  3. Embarquer et insérer les nouvelles lettres :")
        print("     python3 pipeline/embed_insert_missing.py")


if __name__ == "__main__":
    main()
