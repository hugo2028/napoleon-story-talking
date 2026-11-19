"""
Étape 3 : Outil de vérification humaine sur 10% du corpus.

Usage interactif : python pipeline/review.py
  - Affiche chaque exemple
  - Marquer comme ✓ valide, ✗ invalide, ou s modifier
  - Produit napoleon-corpus/datasets/sft/review/reviewed.jsonl (exemples validés uniquement)
"""

import json
from pathlib import Path

SFT_DIR = Path(__file__).parent.parent / "napoleon-corpus" / "datasets" / "sft"
REVIEW_PATH = SFT_DIR / "review" / "review_sample.jsonl"
TRAINING_PATH = SFT_DIR / "training" / "training_data.jsonl"
CLEAN_PATH = SFT_DIR / "training" / "training_clean.jsonl"


def display_example(ex: dict, idx: int, total: int):
    meta = ex.get("_meta", {})
    msgs = ex["messages"]

    print("\n" + "═" * 70)
    print(f"  Exemple {idx}/{total}  │  Type: {meta.get('type','?')}  │  Thème: {meta.get('theme','?')}")
    print(f"  Section: {meta.get('section','?')[:60]}")
    print("─" * 70)
    print(f"\n[SYSTEM]\n{msgs[0]['content']}\n")
    print(f"[USER]\n{msgs[1]['content']}\n")
    print(f"[ASSISTANT]\n{msgs[2]['content']}\n")
    print("─" * 70)
    print("  [v] Valide   [x] Invalide   [e] Éditer assistant   [q] Quitter")


def review_sample():
    if not REVIEW_PATH.exists():
        print(f"Fichier de revue introuvable: {REVIEW_PATH}")
        print("Lancez d'abord: python pipeline/generator.py")
        return

    with open(REVIEW_PATH, "r", encoding="utf-8") as f:
        examples = [json.loads(line) for line in f if line.strip()]

    print(f"\n{'═'*70}")
    print(f"  VÉRIFICATION HUMAINE — {len(examples)} exemples (10% du corpus)")
    print(f"{'═'*70}")
    print("\nObjectif: valider la qualité des paires générées par Claude.")
    print("Les exemples invalides seront exclus du dataset final.\n")

    valid = []
    invalid_ids: set[int] = set()

    for i, ex in enumerate(examples, 1):
        display_example(ex, i, len(examples))

        while True:
            choice = input("  → Choix: ").strip().lower()
            if choice in ("v", ""):
                valid.append(ex)
                break
            elif choice == "x":
                invalid_ids.add(ex["_meta"]["passage_id"])
                break
            elif choice == "e":
                print("  Nouveau texte assistant (Entrée pour terminer la saisie, ligne vide=fin):")
                lines = []
                while True:
                    line = input()
                    if line == "":
                        break
                    lines.append(line)
                if lines:
                    ex["messages"][2]["content"] = "\n".join(lines)
                    valid.append(ex)
                break
            elif choice == "q":
                break
        else:
            continue
        if choice == "q":
            break

    print(f"\n\nRésultats de la revue:")
    print(f"  ✓ Valides:   {len(valid)}")
    print(f"  ✗ Invalides: {len(examples) - len(valid)}")

    if invalid_ids:
        print(f"\n  Passages marqués invalides (IDs): {sorted(invalid_ids)}")
        answer = input("\n  Filtrer ces passages du training data complet? [o/n]: ").strip().lower()
        if answer == "o":
            _filter_training_data(invalid_ids)

    return valid, invalid_ids


def _filter_training_data(invalid_passage_ids: set[int]):
    """Retire les passages marqués invalides du dataset complet."""
    if not TRAINING_PATH.exists():
        return

    with open(TRAINING_PATH, "r", encoding="utf-8") as f:
        all_examples = [json.loads(line) for line in f if line.strip()]

    filtered = [
        ex for ex in all_examples
        if ex.get("_meta", {}).get("passage_id") not in invalid_passage_ids
    ]

    removed = len(all_examples) - len(filtered)

    CLEAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CLEAN_PATH, "w", encoding="utf-8") as f:
        for ex in filtered:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    print(f"\n✓ Dataset nettoyé: {len(filtered)} exemples ({removed} supprimés)")
    print(f"→ Sauvegardé dans {CLEAN_PATH}")


def show_stats():
    """Affiche les statistiques du dataset."""
    path = CLEAN_PATH if CLEAN_PATH.exists() else TRAINING_PATH
    if not path.exists():
        print("Aucun dataset trouvé.")
        return

    with open(path, "r", encoding="utf-8") as f:
        examples = [json.loads(line) for line in f if line.strip()]

    theme_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}

    for ex in examples:
        meta = ex.get("_meta", {})
        theme = meta.get("theme", "?")
        type_ = meta.get("type", "?")
        theme_counts[theme] = theme_counts.get(theme, 0) + 1
        type_counts[type_] = type_counts.get(type_, 0) + 1

    print(f"\n{'═'*50}")
    print(f"  Dataset: {path.name}")
    print(f"  Total exemples: {len(examples)}")
    print(f"{'─'*50}")
    print("  Par thème:")
    for theme, count in sorted(theme_counts.items(), key=lambda x: -x[1]):
        print(f"    {theme:<20} {count:>4}")
    print(f"{'─'*50}")
    print("  Par type:")
    for type_, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"    {type_:<20} {count:>4}")
    print(f"{'═'*50}\n")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "stats":
        show_stats()
    else:
        review_sample()
