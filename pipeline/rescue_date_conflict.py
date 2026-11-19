"""
Récupère les passages rejetés pour date_conflict dont une lettre sœur
(même source_type + même title) a une date validée dans cleaned_cpt.jsonl.

Workflow:
  python3 pipeline/rescue_date_conflict.py prepare
  python3 pipeline/rescue_date_conflict.py submit
  python3 pipeline/rescue_date_conflict.py status
  python3 pipeline/rescue_date_conflict.py process
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
CORPUS_DIR = ROOT / "napoleon-corpus"
BASE = CORPUS_DIR / "datasets" / "llm_clean"
PROMPT_PATH = CORPUS_DIR / "metadata" / "llm_cleaning_prompt.md"
BATCH_DIR = ROOT / "data" / "batch"
SYSTEM_PROMPT = "Tu reponds uniquement avec un objet JSON valide."

import sys
sys.path.insert(0, str(Path(__file__).parent))
from llm_clean_corpus import normalize_result, write_jsonl_line, load_done


def load_env():
    load_dotenv(ROOT / ".env")
    key = os.getenv("OPEN_AI_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    if not key:
        raise RuntimeError("Clé API introuvable dans .env")
    return key


def build_validated_dates() -> dict[tuple[str, str], str]:
    """Construit la map (source_type, title) -> date_iso depuis tous les cleaned_cpt.jsonl."""
    validated = {}
    for f in sorted(BASE.rglob("cleaned_cpt.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            title = r.get("title", "").strip()
            source_type = r.get("source_type", "")
            date_iso = r.get("date_iso")
            if title and date_iso and date_iso != "null":
                key = (source_type, title)
                if key not in validated:
                    validated[key] = date_iso
    return validated


def collect_rescuable(validated: dict) -> list[dict]:
    """Trouve les rejected date_conflict rescuables."""
    # IDs déjà traités dans le dossier rescue
    rescue_dir = BASE / "rescue"
    done = load_done(rescue_dir / "cleaned_cpt.jsonl") | load_done(rescue_dir / "rejected.jsonl")

    rescuable = []
    seen_ids = set()
    for f in sorted(BASE.rglob("rejected.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("reject_reason") != "date_conflict":
                continue
            rid = r.get("id", "")
            if rid in done or rid in seen_ids:
                continue
            seen_ids.add(rid)
            title = r.get("title", "").strip()
            source_type = r.get("source_type", "")
            key = (source_type, title)
            if key in validated:
                r["_rescue_date"] = validated[key]
                rescuable.append(r)
    return rescuable


def build_user_prompt(base_prompt: str, row: dict, rescue_date: str) -> str:
    """Prompt de nettoyage avec date injectée comme certaine."""
    from llm_clean_corpus import build_user_prompt as _build
    prompt = _build(base_prompt, row)
    # Injecter la date validée pour éviter le date_conflict
    injection = (
        f"\n\nNOTE IMPORTANTE : La date de cette lettre est connue avec certitude : {rescue_date}. "
        f"Tu dois utiliser cette date comme date_iso. Ne pas la rejeter pour date_conflict."
    )
    return prompt + injection


# ---------------------------------------------------------------------------
# prepare
# ---------------------------------------------------------------------------

def cmd_prepare(args):
    base_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    BATCH_DIR.mkdir(parents=True, exist_ok=True)

    validated = build_validated_dates()
    print(f"Lettres avec date validée : {len(validated)}")

    rescuable = collect_rescuable(validated)
    print(f"Passages rescuables       : {len(rescuable)}")

    if not rescuable:
        print("Rien à faire.")
        return

    lines_batch = []
    lines_meta = []
    for r in rescuable:
        rescue_date = r["_rescue_date"]
        row = {
            "id": r["id"],
            "source_type": r.get("source_type", ""),
            "title": r.get("title", ""),
            "text": r.get("text", ""),
            "date_iso": rescue_date,
        }
        prompt = build_user_prompt(base_prompt, row, rescue_date)
        request = {
            "custom_id": r["id"],
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
        lines_meta.append(json.dumps({
            "id": r["id"],
            "source_type": r.get("source_type"),
            "rescue_date": rescue_date,
            "original": row,
        }, ensure_ascii=False))

    batch_file = BATCH_DIR / "batch_rescue_01.jsonl"
    meta_file = BATCH_DIR / "batch_rescue_meta.jsonl"
    batch_file.write_text("\n".join(lines_batch) + "\n", encoding="utf-8")
    meta_file.write_text("\n".join(lines_meta) + "\n", encoding="utf-8")
    print(f"\n✓ Batch prêt : {batch_file} ({len(lines_batch)} requêtes)")
    print(f"Prochaine étape : python3 pipeline/rescue_date_conflict.py submit")


# ---------------------------------------------------------------------------
# submit
# ---------------------------------------------------------------------------

def cmd_submit(args):
    key = load_env()
    from openai import OpenAI
    client = OpenAI(api_key=key)

    batch_file = BATCH_DIR / "batch_rescue_01.jsonl"
    state_file = BATCH_DIR / "batch_rescue_state.json"

    print(f"Upload {batch_file} ...")
    with open(batch_file, "rb") as f:
        uploaded = client.files.create(file=f, purpose="batch")
    batch = client.batches.create(
        input_file_id=uploaded.id,
        endpoint="/v1/chat/completions",
        completion_window="24h",
    )
    print(f"  Batch ID : {batch.id}  status={batch.status}")
    state = {"batch_id": batch.id, "file_id": uploaded.id, "status": batch.status}
    state_file.write_text(json.dumps(state, indent=2))
    print(f"\n✓ Soumis. Vérifier : python3 pipeline/rescue_date_conflict.py status")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def cmd_status(args):
    key = load_env()
    from openai import OpenAI
    client = OpenAI(api_key=key)

    state = json.loads((BATCH_DIR / "batch_rescue_state.json").read_text())
    batch = client.batches.retrieve(state["batch_id"])
    c = batch.request_counts
    print(f"Status : {batch.status}  |  {c.completed}/{c.total} ({c.failed} failed)")
    state["status"] = batch.status
    state["output_file_id"] = batch.output_file_id
    (BATCH_DIR / "batch_rescue_state.json").write_text(json.dumps(state, indent=2))
    if batch.status == "completed":
        print("✓ Terminé. Lancer : python3 pipeline/rescue_date_conflict.py process")


# ---------------------------------------------------------------------------
# process
# ---------------------------------------------------------------------------

def cmd_process(args):
    key = load_env()
    from openai import OpenAI
    client = OpenAI(api_key=key)

    state = json.loads((BATCH_DIR / "batch_rescue_state.json").read_text())
    output_file_id = state.get("output_file_id")
    if not output_file_id:
        raise RuntimeError("output_file_id absent — vérifiez le status.")

    meta = {}
    for line in (BATCH_DIR / "batch_rescue_meta.jsonl").read_text().splitlines():
        if line.strip():
            m = json.loads(line)
            meta[m["id"]] = m

    rescue_dir = BASE / "rescue"
    rescue_dir.mkdir(parents=True, exist_ok=True)
    output_clean = rescue_dir / "cleaned_cpt.jsonl"
    output_reject = rescue_dir / "rejected.jsonl"

    print(f"Téléchargement résultats ({output_file_id}) ...")
    content = client.files.content(output_file_id).text

    kept = rejected = errors = 0
    for line in content.splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        custom_id = r.get("custom_id")
        m = meta.get(custom_id, {})
        source_row = m.get("original", {})
        # Forcer la date validée
        source_row["date_iso"] = m.get("rescue_date")

        try:
            body = r["response"]["body"]
            result_text = body["choices"][0]["message"]["content"]
            result = json.loads(result_text)
        except Exception as e:
            errors += 1
            write_jsonl_line(output_reject, {
                "id": custom_id, "decision": "reject",
                "reject_reason": f"parse_error: {e}",
            })
            continue

        normalized = normalize_result(source_row, result)
        # Forcer la date même si le LLM l'a changée
        if normalized.get("date_iso") is None or normalized.get("date_iso") == "null":
            normalized["date_iso"] = m.get("rescue_date")

        if normalized["decision"] == "keep":
            write_jsonl_line(output_clean, normalized)
            kept += 1
        else:
            write_jsonl_line(output_reject, normalized)
            rejected += 1

    print(f"\n✓ Rescue terminé")
    print(f"  Keep    : {kept}")
    print(f"  Reject  : {rejected}")
    print(f"  Erreurs : {errors}")
    print(f"  Output  : {rescue_dir}")
    print(f"\nPour ajouter au RAG :")
    print(f"  python3 napoleon-corpus/scripts/build_rag_from_cleaned.py")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "submit", "status", "process"])
    parser.add_argument("--model", default="gpt-5-nano")
    args = parser.parse_args()

    {
        "prepare": cmd_prepare,
        "submit": cmd_submit,
        "status": cmd_status,
        "process": cmd_process,
    }[args.command](args)


if __name__ == "__main__":
    main()
