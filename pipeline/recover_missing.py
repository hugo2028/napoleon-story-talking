"""
Récupère les passages manquants d'un batch partiellement complété.
Identifie les IDs non traités et les retraite via l'API synchrone.

Usage:
  python3 pipeline/recover_missing.py --chunk data/batch/batch_correspondance_02.jsonl
"""

import argparse
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
BATCH_DIR = ROOT / "data" / "batch"
CORPUS_DIR = ROOT / "napoleon-corpus"
PROMPT_PATH = CORPUS_DIR / "metadata" / "llm_cleaning_prompt.md"
OUTPUT_DIR = CORPUS_DIR / "datasets" / "llm_clean" / "batch"

import sys
sys.path.insert(0, str(Path(__file__).parent))
from llm_clean_corpus import (
    build_user_prompt, normalize_result,
    write_jsonl_line, load_done, call_openai,
)

SYSTEM_PROMPT = "Tu reponds uniquement avec un objet JSON valide."


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunk", required=True, help="Fichier batch JSONL du chunk partiellement traité")
    parser.add_argument("--model", default="gpt-5-nano")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--sleep", type=float, default=0.5)
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    key = os.getenv("OPEN_AI_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")

    from openai import OpenAI
    client = OpenAI(api_key=key)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_clean  = output_dir / "cleaned_cpt.jsonl"
    output_reject = output_dir / "rejected.jsonl"

    # IDs déjà traités
    done = load_done(output_clean) | load_done(output_reject)
    print(f"IDs déjà traités : {len(done)}")

    # Lire les métadonnées du chunk pour récupérer les rows originaux
    source = args.chunk.replace("batch_", "").replace(".jsonl", "").split("_")[0]
    meta_file = BATCH_DIR / f"batch_{source}_meta.jsonl"
    meta = {}
    for line in meta_file.read_text().splitlines():
        if line.strip():
            m = json.loads(line)
            meta[m["id"]] = m["original"]

    # Identifier les IDs du chunk non encore traités
    chunk_ids = []
    for line in Path(args.chunk).read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            cid = r["custom_id"]
            if cid not in done:
                chunk_ids.append(cid)

    print(f"IDs manquants dans ce chunk : {len(chunk_ids)}")
    if not chunk_ids:
        print("Rien à faire.")
        return

    base_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    kept = rejected = errors = 0

    for i, cid in enumerate(chunk_ids):
        row = meta.get(cid)
        if not row:
            print(f"  [{cid}] métadonnées introuvables, skip")
            continue

        prompt = build_user_prompt(base_prompt, row)
        try:
            result = call_openai(client, args.model, prompt)
            normalized = normalize_result(row, result)
        except Exception as e:
            errors += 1
            print(f"  [{cid}] erreur: {e}")
            write_jsonl_line(output_reject, {
                "id": cid, "decision": "reject",
                "reject_reason": f"api_error: {e}",
                "source_type": row.get("source_type"),
            })
            time.sleep(args.sleep)
            continue

        if normalized["decision"] == "keep":
            write_jsonl_line(output_clean, normalized)
            kept += 1
        else:
            write_jsonl_line(output_reject, normalized)
            rejected += 1

        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{len(chunk_ids)} — keep={kept} reject={rejected}")
        time.sleep(args.sleep)

    print(f"\n✓ Terminé : keep={kept} reject={rejected} errors={errors}")


if __name__ == "__main__":
    main()
