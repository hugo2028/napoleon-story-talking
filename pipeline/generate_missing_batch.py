"""
Génère les exemples SFT manquants via OpenAI Batch API.

Workflow:
  1. submit  : crée et envoie un batch par fichier de passages.
  2. status  : affiche l'état des batches.
  3. collect : récupère les sorties terminées et les ajoute aux fichiers training/state.

Le mode Batch est asynchrone. Les résultats ne sont donc pas disponibles
immédiatement, mais le coût est réduit.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from generator import (
    GENERATION_PROMPT,
    REVIEW_DIR,
    STATE_DIR,
    TRAINING_DIR,
    _create_review_sample,
    parse_generation_response,
)


ROOT = Path(__file__).parent.parent
PASSAGES_DIR = ROOT / "napoleon-corpus" / "processed" / "passages"
BATCH_DIR = ROOT / "napoleon-corpus" / "datasets" / "sft" / "batch"
REQUESTS_DIR = BATCH_DIR / "requests"
RESPONSES_DIR = BATCH_DIR / "responses"
MANIFESTS_DIR = BATCH_DIR / "manifests"


def openai_client():
    import openai

    key = os.getenv("OPEN_AI_KEY") or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPEN_AI_KEY, LLM_API_KEY ou OPENAI_API_KEY est requis dans .env")
    return openai.OpenAI(api_key=key)


def load_passages(path: Path) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_done_ids(stem: str) -> set[Any]:
    done: set[Any] = set()
    training_path = TRAINING_DIR / f"{stem}_training.jsonl"
    state_path = STATE_DIR / f"{stem}_state.jsonl"

    if training_path.exists():
        with open(training_path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                ex = json.loads(line)
                passage_id = ex.get("_meta", {}).get("passage_id")
                if passage_id is not None:
                    done.add(passage_id)

    if state_path.exists():
        with open(state_path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                item = json.loads(line)
                if item.get("status") in {"generated", "skipped"}:
                    done.add(item.get("passage_id"))

    return done


def make_request(stem: str, passage: dict[str, Any], model: str) -> dict[str, Any]:
    prompt = GENERATION_PROMPT.format(
        section=passage.get("section", ""),
        text=passage.get("text", ""),
    )
    return {
        "custom_id": f"{stem}:{passage['id']}",
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": {
            "model": model,
            "max_tokens": 1500,
            "messages": [{"role": "user", "content": prompt}],
        },
    }


def submit_one(client, path: Path, model: str, max_passages: int | None) -> Path | None:
    stem = path.stem
    passages = load_passages(path)
    done = read_done_ids(stem)
    to_process = [p for p in passages if p["id"] not in done]
    if max_passages is not None:
        to_process = to_process[:max_passages]

    print(f"\n{stem}: {len(to_process)} passages à envoyer / {len(passages)}")
    if not to_process:
        return None

    REQUESTS_DIR.mkdir(parents=True, exist_ok=True)
    MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    request_path = REQUESTS_DIR / f"{stem}_{timestamp}.jsonl"
    manifest_path = MANIFESTS_DIR / f"{stem}_{timestamp}.json"

    with open(request_path, "w", encoding="utf-8") as f:
        for passage in to_process:
            f.write(json.dumps(make_request(stem, passage, model), ensure_ascii=False) + "\n")

    with open(request_path, "rb") as f:
        uploaded = client.files.create(file=f, purpose="batch")

    batch = client.batches.create(
        input_file_id=uploaded.id,
        endpoint="/v1/chat/completions",
        completion_window="24h",
        metadata={"source": stem, "model": model},
    )

    manifest = {
        "batch_id": batch.id,
        "input_file_id": uploaded.id,
        "status": batch.status,
        "source": stem,
        "model": model,
        "passages_path": str(path),
        "request_path": str(request_path),
        "created_at": timestamp,
        "requested": len(to_process),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"  batch_id: {batch.id}")
    print(f"  manifest: {manifest_path}")
    return manifest_path


def submit(args: argparse.Namespace) -> None:
    client = openai_client()
    paths = sorted(PASSAGES_DIR.glob(args.glob))
    if not paths:
        raise RuntimeError(f"Aucun fichier trouvé avec --glob {args.glob!r}")
    for path in paths:
        submit_one(client, path, args.model, args.max_passages)


def load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def manifest_paths(args: argparse.Namespace) -> list[Path]:
    if args.manifest:
        return [Path(args.manifest)]
    paths = sorted(MANIFESTS_DIR.glob("*.json"))
    if args.all:
        return paths
    return [p for p in paths if load_manifest(p).get("status") not in {"completed", "failed", "cancelled", "expired"}]


def print_status(args: argparse.Namespace) -> None:
    client = openai_client()
    paths = manifest_paths(args)
    if not paths:
        print("Aucun batch à afficher.")
        return
    for path in paths:
        manifest = load_manifest(path)
        batch = client.batches.retrieve(manifest["batch_id"])
        manifest["status"] = batch.status
        manifest["output_file_id"] = getattr(batch, "output_file_id", None)
        manifest["error_file_id"] = getattr(batch, "error_file_id", None)
        save_manifest(path, manifest)
        print(f"{path.name}: {manifest['source']} -> {batch.status}")


def file_content_bytes(client, file_id: str) -> bytes:
    response = client.files.content(file_id)
    if hasattr(response, "content"):
        return response.content
    if hasattr(response, "read"):
        data = response.read()
        return data if isinstance(data, bytes) else data.encode("utf-8")
    return str(response).encode("utf-8")


def response_text_from_batch_line(line: dict[str, Any]) -> str | None:
    response = line.get("response") or {}
    if response.get("status_code") != 200:
        return None
    body = response.get("body") or {}
    choices = body.get("choices") or []
    if not choices:
        return None
    return choices[0].get("message", {}).get("content")


def index_passages(path: Path) -> dict[Any, dict[str, Any]]:
    return {p["id"]: p for p in load_passages(path)}


def passage_id_from_custom_id(custom_id: str) -> str:
    return custom_id.split(":", 1)[1]


def resolve_passage(passages_by_id: dict[Any, dict[str, Any]], custom_id: str) -> dict[str, Any] | None:
    raw_id = passage_id_from_custom_id(custom_id)
    if raw_id in passages_by_id:
        return passages_by_id[raw_id]
    try:
        int_id = int(raw_id)
    except ValueError:
        return None
    return passages_by_id.get(int_id)


def collect_one(client, manifest_path: Path) -> None:
    manifest = load_manifest(manifest_path)
    batch = client.batches.retrieve(manifest["batch_id"])
    manifest["status"] = batch.status
    manifest["output_file_id"] = getattr(batch, "output_file_id", None)
    manifest["error_file_id"] = getattr(batch, "error_file_id", None)
    save_manifest(manifest_path, manifest)

    if batch.status != "completed":
        print(f"{manifest_path.name}: pas terminé ({batch.status})")
        return

    if not batch.output_file_id:
        print(f"{manifest_path.name}: terminé sans output_file_id")
        return

    RESPONSES_DIR.mkdir(parents=True, exist_ok=True)
    response_path = RESPONSES_DIR / f"{manifest_path.stem}_output.jsonl"
    response_path.write_bytes(file_content_bytes(client, batch.output_file_id))
    manifest["response_path"] = str(response_path)
    save_manifest(manifest_path, manifest)

    stem = manifest["source"]
    passages_by_id = index_passages(Path(manifest["passages_path"]))
    training_path = TRAINING_DIR / f"{stem}_training.jsonl"
    review_path = REVIEW_DIR / f"{stem}_review.jsonl"
    state_path = STATE_DIR / f"{stem}_state.jsonl"
    done = read_done_ids(stem)

    TRAINING_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    generated = 0
    skipped = 0
    errors = 0
    already_done = 0

    with (
        open(response_path, encoding="utf-8") as in_f,
        open(training_path, "a", encoding="utf-8") as training_f,
        open(state_path, "a", encoding="utf-8") as state_f,
    ):
        for raw_line in in_f:
            if not raw_line.strip():
                continue
            line = json.loads(raw_line)
            custom_id = line.get("custom_id", "")
            passage = resolve_passage(passages_by_id, custom_id)
            if passage is None:
                errors += 1
                continue

            passage_id = passage["id"]
            if passage_id in done:
                already_done += 1
                continue

            text = response_text_from_batch_line(line)
            if text is None:
                errors += 1
                state_f.write(json.dumps({
                    "passage_id": passage_id,
                    "status": "error",
                    "source": stem,
                    "model": manifest["model"],
                    "batch_id": manifest["batch_id"],
                    "custom_id": custom_id,
                    "error": line.get("error") or line.get("response"),
                }, ensure_ascii=False) + "\n")
                continue

            try:
                examples = parse_generation_response(text)
            except json.JSONDecodeError as e:
                examples = None
                parse_error = str(e)
            else:
                parse_error = None

            if examples is None:
                errors += 1
                state_f.write(json.dumps({
                    "passage_id": passage_id,
                    "status": "error",
                    "source": stem,
                    "model": manifest["model"],
                    "batch_id": manifest["batch_id"],
                    "custom_id": custom_id,
                    "error": parse_error or "Réponse JSON invalide",
                }, ensure_ascii=False) + "\n")
            elif examples == []:
                skipped += 1
                state_f.write(json.dumps({
                    "passage_id": passage_id,
                    "status": "skipped",
                    "source": stem,
                    "model": manifest["model"],
                    "batch_id": manifest["batch_id"],
                    "custom_id": custom_id,
                }, ensure_ascii=False) + "\n")
            else:
                for ex in examples:
                    ex["_meta"] = {
                        "type": "roleplay",
                        "passage_id": passage_id,
                        "theme": passage.get("theme"),
                        "section": passage.get("section"),
                    }
                    training_f.write(json.dumps(ex, ensure_ascii=False) + "\n")
                generated += len(examples)
                state_f.write(json.dumps({
                    "passage_id": passage_id,
                    "status": "generated",
                    "source": stem,
                    "model": manifest["model"],
                    "batch_id": manifest["batch_id"],
                    "custom_id": custom_id,
                    "examples": len(examples),
                }, ensure_ascii=False) + "\n")

    _create_review_sample(training_path, review_path)
    manifest["collected_at"] = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    manifest["collect_counts"] = {
        "generated": generated,
        "skipped": skipped,
        "errors": errors,
        "already_done": already_done,
    }
    save_manifest(manifest_path, manifest)
    print(
        f"{manifest_path.name}: {generated} générés, {skipped} skippés, "
        f"{errors} erreurs, {already_done} déjà présents"
    )


def collect(args: argparse.Namespace) -> None:
    client = openai_client()
    paths = manifest_paths(args)
    if not paths:
        print("Aucun batch à collecter.")
        return
    for path in paths:
        collect_one(client, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    submit_parser = subparsers.add_parser("submit")
    submit_parser.add_argument("--model", default="gpt-4.1-mini")
    submit_parser.add_argument("--max-passages", type=int, default=None)
    submit_parser.add_argument("--glob", default="*.json")
    submit_parser.set_defaults(func=submit)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--manifest", default=None)
    status_parser.add_argument("--all", action="store_true")
    status_parser.set_defaults(func=print_status)

    collect_parser = subparsers.add_parser("collect")
    collect_parser.add_argument("--manifest", default=None)
    collect_parser.add_argument("--all", action="store_true")
    collect_parser.set_defaults(func=collect)

    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    args.func(args)


if __name__ == "__main__":
    main()
