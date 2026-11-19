"""
Construit napoleon-corpus/metadata/manifest.jsonl depuis napoleon-corpus/processed/passages/*.json.

Le manifeste garde un lien vers les fichiers existants au lieu de déplacer les
sources. Il fournit le schéma commun pour RAG, timelines, CPT, SFT et DPO.
"""

import json
import re
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).parent.parent
CORPUS_DIR = ROOT / "napoleon-corpus"
PASSAGES_DIR = CORPUS_DIR / "processed" / "passages"
MANIFEST_PATH = CORPUS_DIR / "metadata" / "manifest.jsonl"

MONTHS = {
    "janvier": "01",
    "février": "02",
    "fevrier": "02",
    "mars": "03",
    "avril": "04",
    "mai": "05",
    "juin": "06",
    "juillet": "07",
    "août": "08",
    "aout": "08",
    "septembre": "09",
    "octobre": "10",
    "novembre": "11",
    "décembre": "12",
    "decembre": "12",
}

FRENCH_DATE_RE = re.compile(
    r"\b(?P<day>\d{1,2})\s+(?P<month>janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre)\s+(?P<year>\d{4})\b",
    re.IGNORECASE,
)
YEAR_RE = re.compile(r"\b(?P<year>1[789]\d{2})\b")


def normalize_date(text: str) -> str | None:
    matches = list(FRENCH_DATE_RE.finditer(text))
    if matches:
        match = matches[-1]
        day = int(match.group("day"))
        month = MONTHS[match.group("month").lower()]
        year = int(match.group("year"))
        try:
            return date(year, int(month), day).isoformat()
        except ValueError:
            return None

    year_matches = list(YEAR_RE.finditer(text))
    if year_matches:
        return year_matches[-1].group("year")
    return None


def period_for(date_iso: str | None, theme: str) -> str | None:
    if not date_iso:
        return None
    year = int(date_iso[:4])
    if year <= 1794:
        return "Toulon et jeunesse révolutionnaire"
    if year <= 1797:
        return "Première campagne d'Italie"
    if year <= 1799:
        return "Campagne d'Égypte"
    if year <= 1804:
        return "Consulat"
    if year <= 1812:
        return "Empire"
    if year <= 1815:
        return "Chute de l'Empire"
    if theme == "exil":
        return "Sainte-Hélène"
    return None


def source_type_for(path: Path) -> str:
    name = path.stem.lower()
    if name.startswith("correspondance"):
        return "correspondance"
    if name.startswith("bulletins_") or name.startswith("bulletin_"):
        return "bulletins"
    if name.startswith("proclamations_") or name == "misc_proclamations":
        return "proclamations"
    if name == "lettres_amour_imperiales":
        return "lettres-amour-imperiales"
    if name.startswith("campagne_") or name.startswith("misc_campagne_"):
        return "campagnes"
    if name.startswith("memoires_") or name.startswith("mémoires_"):
        return "memoires-proches"
    if name.startswith("bulletin"):
        return "bulletins"
    if "souper_beaucaire" in name or "jeunesse" in name or "hakem" in name:
        return "jeunesse"
    if "memoire" in name or "mémoires" in name or name.startswith("pg"):
        return "memoires-proches"
    return "source"


def title_for(item: dict[str, Any]) -> str:
    section = item.get("section") or ""
    return section.split(" (", 1)[0].strip() or "Document sans titre"


def reliability_for(source_type: str) -> str:
    if source_type in {"correspondance", "bulletins", "code-civil", "proclamations", "lettres-amour-imperiales"}:
        return "primary"
    if source_type in {"memoires-proches", "biographies"}:
        return "secondary"
    return "unknown"


def build_manifest() -> list[dict[str, Any]]:
    rows = []
    for path in sorted(PASSAGES_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        source_type = source_type_for(path)
        cleaned_path = f"cleaned/{source_type}/{path.stem}.jsonl"
        for index, item in enumerate(data, 1):
            date_iso = normalize_date(
                (item.get("section") or "")
                + " "
                + (item.get("date") or "")
            )
            rows.append({
                "id": f"{path.stem}_{index:06d}",
                "title": title_for(item),
                "author": "Napoléon Bonaparte",
                "date": date_iso,
                "date_text": item.get("date_text") or item.get("date"),
                "place": item.get("place"),
                "recipient": item.get("recipient"),
                "recipient_raw": item.get("recipient_raw"),
                "recipient_place": item.get("recipient_place"),
                "document_id": item.get("document_id"),
                "document_title": item.get("document_title"),
                "letter_id": item.get("letter_id") or item.get("source_id"),
                "part_index": item.get("part_index"),
                "part_count": item.get("part_count"),
                "period": period_for(date_iso, item.get("theme", "")),
                "theme": item.get("theme"),
                "source_type": source_type,
                "source_url": None,
                "reliability": reliability_for(source_type),
                "language": "fr",
                "rights": "public_domain",
                "text_path": cleaned_path,
                "source_file": item.get("source_file") or str(path),
                "passage_file": str(path),
                "passage_id": item.get("id"),
                "word_count": item.get("word_count"),
                "extraction_flags": item.get("extraction_flags"),
                "dropped_remainder": item.get("dropped_remainder"),
            })
    return rows


def export_cleaned(rows: list[dict[str, Any]]) -> None:
    passage_cache: dict[str, list[dict[str, Any]]] = {}
    handles = {}
    try:
        for row in rows:
            passage_file = row["passage_file"]
            if passage_file not in passage_cache:
                passage_cache[passage_file] = json.loads(Path(passage_file).read_text(encoding="utf-8"))
            passage = passage_cache[passage_file][row["passage_id"]]

            output_path = CORPUS_DIR / row["text_path"]
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if output_path not in handles:
                handles[output_path] = open(output_path, "w", encoding="utf-8")

            handles[output_path].write(json.dumps({
                "id": row["id"],
                "title": row["title"],
                "date": row["date"],
                "date_text": row.get("date_text"),
                "place": row.get("place"),
                "recipient": row.get("recipient"),
                "recipient_raw": row.get("recipient_raw"),
                "recipient_place": row.get("recipient_place"),
                "document_id": row.get("document_id"),
                "document_title": row.get("document_title"),
                "letter_id": row.get("letter_id"),
                "part_index": row.get("part_index"),
                "part_count": row.get("part_count"),
                "period": row["period"],
                "theme": row["theme"],
                "source_type": row["source_type"],
                "text": passage.get("text", ""),
                "word_count": row["word_count"],
                "extraction_flags": row.get("extraction_flags"),
                "dropped_remainder": row.get("dropped_remainder"),
                "metadata_id": row["id"],
            }, ensure_ascii=False) + "\n")
    finally:
        for handle in handles.values():
            handle.close()


def main():
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows = build_manifest()
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Manifest écrit: {MANIFEST_PATH}")
    print(f"Documents: {len(rows)}")
    export_cleaned(rows)
    print("Cleaned exports écrits dans napoleon-corpus/cleaned/")


if __name__ == "__main__":
    main()
