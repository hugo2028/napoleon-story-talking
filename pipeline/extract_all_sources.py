"""
Étape 1 canonique : convertir napoleon-corpus/sources/ vers
napoleon-corpus/processed/passages/.

Chaque source brute peut avoir une structure différente. Ce script choisit
l'extracteur adapté et produit toujours le même format intermédiaire :
napoleon-corpus/processed/passages/<stem>.json

Usage :
  python3 pipeline/extract_all_sources.py --dry-run
  python3 pipeline/extract_all_sources.py
  python3 pipeline/extract_all_sources.py --only correspondance
"""

import json
from pathlib import Path

from extractor import extract_passages
from extract_bulletins import extract_bulletin_file
from extract_correspondances import extract_correspondance_file
from extract_special_correspondances import (
    extract_adieux_marie_file,
    extract_inedites_file,
    extract_marine_1_file,
    extract_marine_2_file,
)
from extract_tendresses import extract_tendresses_file


ROOT = Path(__file__).parent.parent
SOURCES_DIR = ROOT / "napoleon-corpus" / "sources"
LEGACY_LIVRES_DIR = ROOT / "livres"
PASSAGES_DIR = ROOT / "napoleon-corpus" / "processed" / "passages"


def default_sources_dir() -> Path:
    if SOURCES_DIR.exists():
        return SOURCES_DIR
    return LEGACY_LIVRES_DIR


def source_type_for(path: Path, base_dir: Path) -> str:
    parts = [part.lower() for part in path.relative_to(base_dir).parts]
    joined = "/".join(parts)

    if "correspondances" in parts:
        return "correspondance"
    if "bulletin_armée" in parts or "bulletin_armee" in parts:
        return "bulletins"
    if "proclamations" in parts:
        return "proclamations"
    if "tendresses impériales" in parts or "tendresses imperiales" in joined:
        return "lettres-amour-imperiales"
    if "campagne italie" in parts or "campagne_italie" in joined:
        return "campagnes"
    if "mémoires" in parts or "memoires" in joined:
        return "memoires-proches"
    if "jeunesse" in parts or "souper_beaucaire" in parts:
        return "jeunesse"
    if "sainte" in joined or "helene" in joined or "hélène" in joined:
        return "sainte-helene"
    if "code" in joined and "civil" in joined:
        return "code-civil"
    if "biograph" in joined:
        return "biographies"
    return "misc"


def output_stem_for(path: Path, base_dir: Path) -> str:
    source_type = source_type_for(path, base_dir)
    stem = path.stem

    if source_type == "correspondance":
        # Les 32 tomes ont déjà des noms stables: correspondance_1, etc.
        if stem.startswith("correspondance_"):
            return stem
        parent = path.parent.name.lower().replace(" ", "_")
        return f"correspondance_{parent}_{stem}"

    if source_type == "memoires-proches":
        return stem

    if source_type == "lettres-amour-imperiales":
        return "lettres_amour_imperiales"

    if source_type in {"campagnes", "proclamations", "jeunesse"}:
        return f"misc_{stem}"

    return f"{source_type}_{stem}"


def extract_one(path: Path, base_dir: Path) -> list[dict]:
    source_type = source_type_for(path, base_dir)
    if source_type == "correspondance":
        if path.name == "adieux_marie.html":
            passages = extract_adieux_marie_file(path)
            if passages:
                return passages
        if path.name == "inedites.html":
            passages = extract_inedites_file(path)
            if passages:
                return passages
        if path.name == "marine_1.html":
            passages = extract_marine_1_file(path)
            if passages:
                return passages
        if path.name == "marine_2.html":
            passages = extract_marine_2_file(path)
            if passages:
                return passages
        passages = extract_correspondance_file(path)
        if passages:
            return passages
    if source_type == "bulletins":
        passages = extract_bulletin_file(path)
        if passages:
            return passages
    if source_type == "lettres-amour-imperiales":
        passages = extract_tendresses_file(path)
        if passages:
            return passages

    return extract_passages(path)


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", default=str(default_sources_dir()))
    parser.add_argument("--output-dir", default=str(PASSAGES_DIR))
    parser.add_argument("--only", default=None, help="Filtrer par source_type: correspondance, bulletins, etc.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true", help="Réécrire les fichiers déjà présents")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    files = sorted(path for path in input_dir.rglob("*") if path.suffix.lower() in {".html", ".htm", ".txt"})

    planned = []
    for path in files:
        source_type = source_type_for(path, input_dir)
        if args.only and source_type != args.only:
            continue
        output_path = output_dir / f"{output_stem_for(path, input_dir)}.json"
        planned.append((path, source_type, output_path))

    print(f"Sources trouvées: {len(planned)}")
    for path, source_type, output_path in planned:
        status = "exists" if output_path.exists() else "new"
        print(f"  [{source_type:<16}] {path} -> {output_path} ({status})")

    if args.dry_run:
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    skipped = 0
    for path, source_type, output_path in planned:
        if output_path.exists() and not args.overwrite:
            skipped += 1
            continue

        print(f"\nExtraction {path} ({source_type})")
        passages = extract_one(path, input_dir)
        output_path.write_text(json.dumps(passages, ensure_ascii=False, indent=2), encoding="utf-8")
        total += len(passages)
        print(f"  -> {output_path} ({len(passages)} passages)")

    print(f"\nTerminé: {total} passages écrits, {skipped} fichiers ignorés car existants")


if __name__ == "__main__":
    main()
