"""
Nettoyage LLM via OpenAI Batch API (50% moins cher, pas de rate limit).

Workflow:
  python3 pipeline/batch_clean.py prepare --source-type correspondance
  python3 pipeline/batch_clean.py submit   --batch-file data/batch_correspondance.jsonl
  python3 pipeline/batch_clean.py status   --batch-id batch_xxx
  python3 pipeline/batch_clean.py process  --batch-id batch_xxx

Usage typique:
  python3 pipeline/batch_clean.py prepare --source-type correspondance --model gpt-5-nano
  python3 pipeline/batch_clean.py submit
  python3 pipeline/batch_clean.py status
  python3 pipeline/batch_clean.py process
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
CORPUS_DIR = ROOT / "napoleon-corpus"
PROMPT_PATH = CORPUS_DIR / "metadata" / "llm_cleaning_prompt.md"
DEFAULT_GLOB = str(CORPUS_DIR / "cleaned" / "*" / "*.jsonl")
BATCH_DIR = ROOT / "data" / "batch"
SYSTEM_PROMPT = "Tu reponds uniquement avec un objet JSON valide."

sys.path.insert(0, str(Path(__file__).parent))
from llm_clean_corpus import (
    build_user_prompt,
    normalize_result,
    load_jsonl,
    write_jsonl_line,
    load_done,
    write_state,
)


def load_env():
    load_dotenv(ROOT / ".env")
    key = os.getenv("OPEN_AI_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    if not key:
        raise RuntimeError("OPEN_AI_KEY / OPENAI_API_KEY / LLM_API_KEY introuvable dans .env")
    return key


# ---------------------------------------------------------------------------
# prepare
# ---------------------------------------------------------------------------

def collect_all_done(output_dir: Path, source_type: str | None) -> set[str]:
    """Collecte les IDs déjà traités dans output_dir ET dans tous les sous-dossiers source_type_XX."""
    done: set[str] = set()
    # Dossier batch courant
    done |= load_done(output_dir / "cleaned_cpt.jsonl")
    done |= load_done(output_dir / "rejected.jsonl")
    # Dossiers de shards existants (ex: correspondance_01 ... correspondance_10)
    if source_type:
        parent = output_dir.parent
        for shard_dir in sorted(parent.glob(f"{source_type}_*")):
            done |= load_done(shard_dir / "cleaned_cpt.jsonl")
            done |= load_done(shard_dir / "rejected.jsonl")
    # Dossier par défaut (llm_clean/) pour les sources sans sous-dossier
    default_dir = CORPUS_DIR / "datasets" / "llm_clean"
    done |= load_done(default_dir / "cleaned_cpt.jsonl")
    done |= load_done(default_dir / "rejected.jsonl")
    return done


def cmd_prepare(args):
    base_prompt = Path(args.prompt).read_text(encoding="utf-8")
    output_dir = Path(args.output_dir)
    BATCH_DIR.mkdir(parents=True, exist_ok=True)

    # Collecter les IDs déjà traités (shards + batch + défaut)
    done = collect_all_done(output_dir, args.source_type)
    print(f"IDs déjà traités : {len(done)}")

    glob_pattern = args.glob or DEFAULT_GLOB
    paths = sorted(
        Path().glob(glob_pattern)
        if not glob_pattern.startswith("/")
        else Path("/").glob(glob_pattern[1:])
    )

    tasks = []
    for path in paths:
        for _, row in load_jsonl(path):
            if args.source_type and row.get("source_type") != args.source_type:
                continue
            if row.get("id") in done:
                continue
            tasks.append(row)

    if args.limit:
        tasks = tasks[: args.limit]

    print(f"Passages à soumettre : {len(tasks)}")
    if not tasks:
        print("Rien à faire.")
        return

    MAX_REQUESTS = args.max_requests  # limite par chunk (token limit OpenAI ~40M)
    source = args.source_type or "all"
    meta_file = BATCH_DIR / f"batch_{source}_meta.jsonl"

    # Préparer toutes les lignes
    lines_batch = []
    lines_meta = []
    for row in tasks:
        prompt = build_user_prompt(base_prompt, row)
        request = {
            "custom_id": row["id"],
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {
                "model": args.model,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            },
        }
        lines_batch.append(json.dumps(request, ensure_ascii=False))
        lines_meta.append(json.dumps({"id": row["id"], "source_type": row.get("source_type"),
                                       "original": row}, ensure_ascii=False))

    # Écrire les métadonnées (un seul fichier)
    meta_file.write_text("\n".join(lines_meta) + "\n", encoding="utf-8")

    # Découper en chunks de MAX_REQUESTS requêtes
    batch_files = []
    for chunk_idx, start in enumerate(range(0, len(lines_batch), MAX_REQUESTS), 1):
        chunk_lines = lines_batch[start:start + MAX_REQUESTS]
        path = BATCH_DIR / f"batch_{source}_{chunk_idx:02d}.jsonl"
        path.write_text("\n".join(chunk_lines) + "\n", encoding="utf-8")
        size_mb = path.stat().st_size / 1_048_576
        print(f"  Chunk {chunk_idx:02d} : {len(chunk_lines)} requêtes, {size_mb:.1f} MB → {path.name}")
        batch_files.append(path)

    print(f"\n✓ {len(batch_files)} fichier(s) batch prêts dans {BATCH_DIR}")
    print(f"  Métadonnées : {meta_file}")
    print(f"\nProchaine étape :")
    print(f"  python3 pipeline/batch_clean.py submit --source-type {source}")


# ---------------------------------------------------------------------------
# submit
# ---------------------------------------------------------------------------

def cmd_submit(args):
    key = load_env()
    from openai import OpenAI
    client = OpenAI(api_key=key)

    source = args.source_type or "all"
    state_file = BATCH_DIR / f"batch_{source}_state.json"

    # Trouver tous les chunks batch_SOURCE_NN.jsonl
    chunk_files = sorted(BATCH_DIR.glob(f"batch_{source}_??.jsonl"))
    if not chunk_files:
        raise FileNotFoundError(f"Aucun fichier batch_{source}_NN.jsonl dans {BATCH_DIR}\nLancer d'abord: prepare")

    batches = []
    for chunk_file in chunk_files:
        print(f"Upload {chunk_file.name} ...")
        with open(chunk_file, "rb") as f:
            uploaded = client.files.create(file=f, purpose="batch")
        batch = client.batches.create(
            input_file_id=uploaded.id,
            endpoint="/v1/chat/completions",
            completion_window="24h",
        )
        print(f"  Batch ID : {batch.id}  status={batch.status}")
        batches.append({"batch_id": batch.id, "file_id": uploaded.id,
                         "chunk": chunk_file.name, "status": batch.status})

    state = {
        "source_type": source,
        "submitted_at": time.time(),
        "batches": batches,
    }
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(f"\n✓ {len(batches)} batch(s) soumis. État : {state_file}")
    print(f"\nProchaine étape :")
    print(f"  python3 pipeline/batch_clean.py status --source-type {source}")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def cmd_resubmit(args):
    """Resoumet uniquement les chunks échoués, un par un."""
    key = load_env()
    from openai import OpenAI
    client = OpenAI(api_key=key)

    source = args.source_type or "all"
    state_file = BATCH_DIR / f"batch_{source}_state.json"
    state = json.loads(state_file.read_text())

    # Collecter les IDs déjà traités
    output_dir = Path(args.output_dir)
    done = collect_all_done(output_dir, source)
    print(f"IDs déjà traités : {len(done)}")

    # Soumettre UN SEUL batch à la fois (limite ~40M tokens par chunk)
    for b in state["batches"]:
        if b.get("status") not in ("failed", "expired", "cancelled"):
            continue
        chunk_file = BATCH_DIR / b["chunk"]
        if not chunk_file.exists():
            print(f"  {b['chunk']} : fichier introuvable, skip")
            continue

        # Filtrer les IDs déjà traités
        original_lines = [l for l in chunk_file.read_text().splitlines() if l.strip()]
        filtered_lines = [l for l in original_lines
                          if json.loads(l)["custom_id"] not in done]
        if not filtered_lines:
            print(f"  {b['chunk']} : tous les IDs déjà traités, skip")
            b["status"] = "completed"
            continue

        skipped = len(original_lines) - len(filtered_lines)
        print(f"Resoumission de {b['chunk']} ({len(filtered_lines)} requêtes, {skipped} déjà traitées skippées) ...")

        # Écrire un chunk filtré temporaire
        filtered_file = BATCH_DIR / f"filtered_{b['chunk']}"
        filtered_file.write_text("\n".join(filtered_lines) + "\n", encoding="utf-8")

        with open(filtered_file, "rb") as f:
            uploaded = client.files.create(file=f, purpose="batch")
        batch = client.batches.create(
            input_file_id=uploaded.id,
            endpoint="/v1/chat/completions",
            completion_window="24h",
        )
        print(f"  Nouveau batch ID : {batch.id}  status={batch.status}")
        b["batch_id"] = batch.id
        b["file_id"] = uploaded.id
        b["status"] = batch.status
        b["output_file_id"] = None
        b["chunk"] = filtered_file.name  # pointer vers le fichier filtré
        state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
        print(f"\n✓ 1 batch soumis (un seul à la fois — limite 40M tokens).")
        print(f"Attendre la fin puis relancer : python3 pipeline/batch_clean.py resubmit --source-type {source}")
        return  # Sortir après le premier

    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print("Tous les batches déjà traités.")


def cmd_status(args):
    key = load_env()
    from openai import OpenAI
    client = OpenAI(api_key=key)

    source = args.source_type or "all"
    state_file = BATCH_DIR / f"batch_{source}_state.json"

    if not state_file.exists():
        raise FileNotFoundError(f"State introuvable : {state_file}\nLancer d'abord: submit")

    state = json.loads(state_file.read_text())
    all_done = True

    for b in state["batches"]:
        batch = client.batches.retrieve(b["batch_id"])
        b["status"] = batch.status
        b["output_file_id"] = batch.output_file_id
        counts = batch.request_counts
        print(f"  {b['chunk']:<35} {batch.status:<15} {counts.completed}/{counts.total} ({counts.failed} failed)")
        if batch.status not in ("completed", "failed", "expired", "cancelled"):
            all_done = False

    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

    if all_done:
        print(f"\n✓ Tous les batches terminés.")
        print(f"Prochaine étape :")
        print(f"  python3 pipeline/batch_clean.py process --source-type {source}")
    else:
        print(f"\nPas encore terminé. Relancez dans quelques minutes.")


# ---------------------------------------------------------------------------
# process
# ---------------------------------------------------------------------------

def cmd_process(args):
    key = load_env()
    from openai import OpenAI
    client = OpenAI(api_key=key)

    source = args.source_type or "all"
    state_file = BATCH_DIR / f"batch_{source}_state.json"
    meta_file  = BATCH_DIR / f"batch_{source}_meta.jsonl"
    output_dir = Path(args.output_dir)

    if not state_file.exists():
        raise FileNotFoundError(f"State introuvable : {state_file}")

    state = json.loads(state_file.read_text())

    # Charger les métadonnées source
    meta = {}
    for line in meta_file.read_text().splitlines():
        if line.strip():
            m = json.loads(line)
            meta[m["id"]] = m["original"]

    output_dir.mkdir(parents=True, exist_ok=True)
    output_clean  = output_dir / "cleaned_cpt.jsonl"
    output_reject = output_dir / "rejected.jsonl"

    kept = rejected = errors = 0
    for b in state["batches"]:
        output_file_id = b.get("output_file_id")
        if not output_file_id:
            print(f"  {b['chunk']} : pas d'output_file_id (skipped)")
            continue
        print(f"Téléchargement {b['chunk']} ({output_file_id}) ...")
        content = client.files.content(output_file_id).text

        for line in content.splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            custom_id = r.get("custom_id")
            source_row = meta.get(custom_id, {})
            try:
                body = r["response"]["body"]
                result_text = body["choices"][0]["message"]["content"]
                result = json.loads(result_text)
            except Exception as e:
                errors += 1
                write_jsonl_line(output_reject, {
                    "id": custom_id, "decision": "reject",
                    "reject_reason": f"batch_parse_error: {e}",
                    "source_type": source_row.get("source_type"),
                })
                continue
            normalized = normalize_result(source_row, result)
            if normalized["decision"] == "keep":
                write_jsonl_line(output_clean, normalized)
                kept += 1
            else:
                write_jsonl_line(output_reject, normalized)
                rejected += 1

    print(f"\n✓ Traitement terminé")
    print(f"  Keep    : {kept}")
    print(f"  Reject  : {rejected}")
    print(f"  Erreurs : {errors}")
    print(f"  Output  : {output_dir}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Nettoyage LLM via OpenAI Batch API")
    parser.add_argument("command", choices=["prepare", "submit", "resubmit", "status", "process"])
    parser.add_argument("--source-type", default=None)
    parser.add_argument("--glob", default=None)
    parser.add_argument("--model", default="gpt-5-nano")
    parser.add_argument("--prompt", default=str(PROMPT_PATH))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-requests", type=int, default=5000, help="Requêtes max par chunk (défaut: 5000)")
    parser.add_argument("--output-dir", default=str(CORPUS_DIR / "datasets" / "llm_clean" / "batch"))
    parser.add_argument("--batch-id", default=None, help="Batch ID (optionnel, lu depuis state sinon)")
    parser.add_argument("--output-file-id", default=None, help="Output file ID (optionnel)")
    args = parser.parse_args()

    if args.command == "prepare":
        cmd_prepare(args)
    elif args.command == "submit":
        cmd_submit(args)
    elif args.command == "resubmit":
        cmd_resubmit(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "process":
        cmd_process(args)


if __name__ == "__main__":
    main()
