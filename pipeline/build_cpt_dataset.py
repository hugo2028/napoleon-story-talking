"""
Construit le dataset CPT (Continued Pretraining) à partir de tous les cleaned_cpt.jsonl.

Format de sortie JSONL : {"text": "...", "id": "...", "source_type": "...", "date_iso": "..."}

Usage:
  python3 pipeline/build_cpt_dataset.py
  python3 pipeline/build_cpt_dataset.py --output napoleon-corpus/datasets/cpt/napoleon_cpt.jsonl
"""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
BASE = ROOT / "napoleon-corpus" / "datasets"

PERIOD_LABELS = {
    (1769, 1792): "Jeunesse",
    (1793, 1795): "Révolution & Toulon",
    (1796, 1797): "Première campagne d'Italie",
    (1798, 1799): "Campagne d'Égypte",
    (1800, 1804): "Consulat",
    (1805, 1814): "Empire",
    (1815, 1821): "Sainte-Hélène",
}

SOURCE_LABELS = {
    "correspondance": "Correspondance",
    "bulletins": "Bulletins",
    "campagnes": "Campagnes",
    "proclamations": "Proclamations",
    "memoires": "Mémoires",
    "lettres-amour-imperiales": "Lettres",
    "jeunesse": "Jeunesse",
}


def get_period(year: int | None) -> str | None:
    if not year:
        return None
    for (y1, y2), label in PERIOD_LABELS.items():
        if y1 <= year <= y2:
            return label
    return None


def build_prefix(entry: dict) -> str:
    parts = []
    date_iso = entry.get("date_iso")
    source_type = entry.get("source_type", "")

    if date_iso:
        parts.append(date_iso)
        year = int(date_iso[:4]) if date_iso else None
        period = get_period(year)
        if period:
            parts.append(period)

    source_label = SOURCE_LABELS.get(source_type, source_type)
    if source_label:
        parts.append(source_label)

    if parts:
        return "[" + " | ".join(parts) + "]\n"
    return ""


def collect_sources() -> list[Path]:
    """Retourne tous les cleaned_cpt.jsonl dans l'ordre naturel des sources."""
    sources = []

    # Correspondance — shards 01-10
    for p in sorted((BASE / "llm_clean").glob("correspondance_*/cleaned_cpt.jsonl")):
        sources.append(p)

    # Correspondance — batch
    p = BASE / "llm_clean" / "batch" / "cleaned_cpt.jsonl"
    if p.exists():
        sources.append(p)

    # Bulletins + campagnes (dossier llm_clean racine)
    p = BASE / "llm_clean" / "cleaned_cpt.jsonl"
    if p.exists():
        sources.append(p)

    # Proclamations
    p = BASE / "llm_clean_proclamations" / "cleaned_cpt.jsonl"
    if p.exists():
        sources.append(p)

    # Mémoires
    p = BASE / "llm_clean_books" / "cleaned_cpt.jsonl"
    if p.exists():
        sources.append(p)

    # Lettres amour
    p = BASE / "llm_clean" / "lettres" / "cleaned_cpt.jsonl"
    if p.exists():
        sources.append(p)

    # Jeunesse
    p = BASE / "llm_clean_jeunesse" / "cleaned_cpt.jsonl"
    if p.exists():
        sources.append(p)

    return sources


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(BASE / "cpt" / "napoleon_cpt.jsonl"))
    parser.add_argument("--min-words", type=int, default=20)
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    sources = collect_sources()
    print(f"Sources trouvées : {len(sources)}")

    seen_ids = set()
    total = duplicates = short = 0

    with open(output, "w", encoding="utf-8") as f:
        for source_path in sources:
            count = 0
            for line in source_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                entry = json.loads(line)
                entry_id = entry.get("id", "")

                if entry_id in seen_ids:
                    duplicates += 1
                    continue
                seen_ids.add(entry_id)

                text = entry.get("cleaned_text") or ""
                if len(text.split()) < args.min_words:
                    short += 1
                    continue

                out = {"text": text}
                f.write(json.dumps(out, ensure_ascii=False) + "\n")
                count += 1
                total += 1

            print(f"  {source_path.parent.name}/{source_path.name}: {count}")

    print(f"\n✓ Dataset CPT : {output}")
    print(f"  Total     : {total}")
    print(f"  Doublons  : {duplicates}")
    print(f"  Trop courts: {short}")


if __name__ == "__main__":
    main()
