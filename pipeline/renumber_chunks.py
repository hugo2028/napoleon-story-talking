"""
Renumérotation des chunks existants dans napoleon_clean.sqlite.

Pour chaque tome affecté, décale les chunk_nums existants de +N
(N = nombre de nouveaux chunks extraits pour ce tome).

Cela libère les positions 1..N pour les nouvelles lettres qui seront
insérées par embed_insert_missing.py.

Usage:
  python3 pipeline/renumber_chunks.py               # utilise data/missing/shifts.json
  python3 pipeline/renumber_chunks.py --dry-run     # affiche sans modifier
  python3 pipeline/renumber_chunks.py --shifts "12:8,14:46,15:25"  # override manuel

Prérequis:
  - data/missing/shifts.json produit par extract_missing_letters.py
  - data/rag/napoleon_clean.sqlite

Important:
  - Exécuter AVANT embed_insert_missing.py
  - Le décalage est permanent — vérifier avec --dry-run d'abord
  - Les embeddings ne bougent pas (liés au chunks.id, pas au chunk_key)
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

ROOT    = Path(__file__).parent.parent
SHIFTS_FILE = ROOT / "data" / "missing" / "shifts.json"
DB_PATH     = ROOT / "data" / "rag" / "napoleon_clean.sqlite"

CHUNK_KEY_RE = re.compile(r'^correspondance_(\d+)_(\d+)$')


def load_shifts(path: Path) -> dict[int, int]:
    """Charge les shifts depuis shifts.json ({tome_str: n_chunks})."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return {int(k): int(v) for k, v in data.items() if int(v) > 0}


def parse_shifts_arg(arg: str) -> dict[int, int]:
    """Parse '12:8,14:46' en {12: 8, 14: 46}."""
    result = {}
    for part in arg.split(","):
        part = part.strip()
        if ":" in part:
            k, v = part.split(":", 1)
            result[int(k.strip())] = int(v.strip())
    return result


def renumber_tome(conn: sqlite3.Connection, tome: int, shift: int, dry_run: bool) -> int:
    """
    Décale les chunk_keys du tome de +shift.
    Traite les clés en ordre DESCENDANT pour éviter les collisions UNIQUE.
    Retourne le nombre de chunks mis à jour.
    """
    # Récupérer toutes les clés du tome, triées par num décroissant
    rows = conn.execute(
        "SELECT id, chunk_key FROM chunks WHERE chunk_key LIKE ? ORDER BY chunk_key DESC",
        (f"correspondance_{tome}_%",)
    ).fetchall()

    if not rows:
        print(f"  Tome {tome}: aucun chunk trouvé")
        return 0

    updated = 0
    for row_id, key in rows:
        m = CHUNK_KEY_RE.match(key)
        if not m or int(m.group(1)) != tome:
            continue
        old_num  = int(m.group(2))
        new_num  = old_num + shift
        new_key  = f"correspondance_{tome}_{new_num:06d}"

        if not dry_run:
            conn.execute("UPDATE chunks SET chunk_key=? WHERE id=?", (new_key, row_id))
        updated += 1

    return updated


def main():
    parser = argparse.ArgumentParser(description="Renumérotation des chunks existants")
    parser.add_argument("--dry-run", action="store_true",
                        help="Afficher les changements sans modifier la base")
    parser.add_argument("--shifts", default=None,
                        help="Override manuel : '12:8,14:46,15:25' (tome:n_nouveaux_chunks)")
    parser.add_argument("--db", default=str(DB_PATH),
                        help=f"Chemin de la base SQLite (défaut: {DB_PATH})")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise FileNotFoundError(f"Base introuvable : {db_path}")

    if args.shifts:
        shifts = parse_shifts_arg(args.shifts)
        print("Shifts (manuel):", shifts)
    elif SHIFTS_FILE.exists():
        shifts = load_shifts(SHIFTS_FILE)
        print(f"Shifts depuis {SHIFTS_FILE}:", shifts)
    else:
        raise FileNotFoundError(
            f"Fichier shifts introuvable : {SHIFTS_FILE}\n"
            "Lancer d'abord : python3 pipeline/extract_missing_letters.py"
        )

    if not shifts:
        print("Aucun shift à appliquer.")
        return

    conn = sqlite3.connect(db_path)
    try:
        total = 0
        for tome in sorted(shifts):
            shift = shifts[tome]
            if shift <= 0:
                continue
            print(f"\nTome {tome:2d} : décalage +{shift}")
            n = renumber_tome(conn, tome, shift, args.dry_run)
            print(f"  → {n} chunks {'[DRY-RUN]' if args.dry_run else 'mis à jour'}")
            total += n

        if not args.dry_run:
            conn.commit()
            print(f"\n✓ {total} chunks renumérotés dans {db_path}")
            print("\nProchaine étape :")
            print("  python3 pipeline/embed_insert_missing.py")
        else:
            print(f"\n[DRY-RUN] {total} chunks seraient modifiés")
            print("Relancer sans --dry-run pour appliquer.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
