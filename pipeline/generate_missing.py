"""
Génère des exemples d'entraînement pour tous les fichiers de passages existants.

Le générateur reprend automatiquement les passages déjà présents dans
napoleon-corpus/datasets/sft/training/<stem>_training.jsonl, donc cette commande
ajoute seulement les passages manquants.
"""

from pathlib import Path

from dotenv import load_dotenv

from generator import generate_training_data


ROOT = Path(__file__).parent.parent
PASSAGES_DIR = ROOT / "napoleon-corpus" / "processed" / "passages"


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--max-passages", type=int, default=None)
    parser.add_argument(
        "--glob",
        default="*.json",
        help="Pattern dans napoleon-corpus/processed/passages (ex: correspondance_*.json)",
    )
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")

    for path in sorted(PASSAGES_DIR.glob(args.glob)):
        print("\n" + "=" * 70)
        print(f"Génération manquante: {path}")
        print("=" * 70)
        generate_training_data(
            model=args.model,
            max_passages=args.max_passages,
            resume=True,
            passages_path=path,
        )


if __name__ == "__main__":
    main()
