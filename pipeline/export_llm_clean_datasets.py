"""
Exporte les datasets finaux depuis les decisions LLM.

Aucun filtre regex n'est applique ici. La source de verite est la decision du
modele dans napoleon-corpus/datasets/llm_clean/cleaned_cpt.jsonl.

Usage:
  python3 pipeline/export_llm_clean_datasets.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).parent.parent
CORPUS_DIR = ROOT / "napoleon-corpus"
LLM_DIR = CORPUS_DIR / "datasets" / "llm_clean"
INPUT_CLEAN = LLM_DIR / "cleaned_cpt.jsonl"
INPUT_SFT = LLM_DIR / "sft_candidates.jsonl"
OUTPUT_CPT_TXT = CORPUS_DIR / "datasets" / "cpt" / "llm_clean.raw.txt"
OUTPUT_CPT_JSONL = CORPUS_DIR / "datasets" / "cpt" / "llm_clean.raw.jsonl"
OUTPUT_CPT_META = CORPUS_DIR / "datasets" / "cpt" / "llm_clean.meta.jsonl"
OUTPUT_SPOKEN_TXT = CORPUS_DIR / "datasets" / "cpt" / "llm_clean.spoken.txt"
OUTPUT_SPOKEN_JSONL = CORPUS_DIR / "datasets" / "cpt" / "llm_clean.spoken.jsonl"
OUTPUT_SFT = CORPUS_DIR / "datasets" / "sft" / "llm_clean_sft.jsonl"


def load_jsonl(path: Path):
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    rows = list(load_jsonl(INPUT_CLEAN) or [])
    kept = [row for row in rows if row.get("decision") == "keep" and row.get("cleaned_text")]

    OUTPUT_CPT_TXT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_CPT_TXT, "w", encoding="utf-8") as f:
        for row in kept:
            f.write(str(row["cleaned_text"]).strip() + "\n\n")

    write_jsonl(OUTPUT_CPT_JSONL, [{"text": str(row["cleaned_text"]).strip()} for row in kept])
    write_jsonl(OUTPUT_CPT_META, kept)
    spoken_rows = [
        {"text": str(row.get("spoken_text") or row["cleaned_text"]).strip()}
        for row in kept
    ]
    write_jsonl(OUTPUT_SPOKEN_JSONL, spoken_rows)
    with open(OUTPUT_SPOKEN_TXT, "w", encoding="utf-8") as f:
        for row in spoken_rows:
            f.write(row["text"] + "\n\n")

    sft_rows = list(load_jsonl(INPUT_SFT) or [])
    write_jsonl(OUTPUT_SFT, sft_rows)

    print(f"CPT LLM clean: {len(kept)} passages -> {OUTPUT_CPT_TXT}")
    print(f"Spoken LLM clean: {len(spoken_rows)} passages -> {OUTPUT_SPOKEN_TXT}")
    print(f"SFT LLM clean: {len(sft_rows)} exemples -> {OUTPUT_SFT}")


if __name__ == "__main__":
    main()
