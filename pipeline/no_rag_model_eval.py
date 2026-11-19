"""
Compare deux modèles sans RAG sur le dataset d'évaluation.

Usage:
  python3 pipeline/no_rag_model_eval.py
  python3 pipeline/no_rag_model_eval.py --base-model gpt-4.1-mini --fine-tuned-model ft:gpt-4.1-mini-2025-04-14:organizations::DkstSMs5
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = ROOT_DIR / "data" / "eval" / "rag_eval_questions.jsonl"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "data" / "eval" / "runs"
DEFAULT_BASE_MODEL = os.getenv("NO_RAG_BASE_MODEL", "gpt-4.1-mini")
DEFAULT_FINE_TUNED_MODEL = os.getenv(
    "NO_RAG_FINE_TUNED_MODEL",
    "ft:gpt-4.1-mini-2025-04-14:organizations::DkstSMs5",
)

NAPOLEON_SYSTEM_PROMPT = """Tu es Napoléon Bonaparte lui-même. Tu t'exprimes en français, avec le style éloquent, assertif et passionné de l'Empereur.

Règles :
- Parle toujours à la première personne, comme Napoléon.
- Utilise un français soutenu mais accessible.
- Sois précis historiquement.
- Garde tes réponses concises : 2 à 4 phrases.

Réponds UNIQUEMENT en JSON valide avec cette structure :
{
  "speech": "ce que Napoléon dit en français"
}"""


@dataclass
class EvalCase:
    id: str
    category: str
    question: str
    notes: str


def load_cases(path: Path, limit: int | None = None) -> list[EvalCase]:
    cases: list[EvalCase] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        cases.append(
            EvalCase(
                id=raw["id"],
                category=raw["category"],
                question=raw["question"],
                notes=raw.get("notes", ""),
            )
        )
    return cases[:limit] if limit else cases


def make_client() -> OpenAI:
    load_dotenv(ROOT_DIR / ".env")
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("LLM_BASE_URL")
    if not api_key:
        raise RuntimeError("LLM_API_KEY ou OPENAI_API_KEY requis.")
    return OpenAI(api_key=api_key, base_url=base_url)


def parse_speech(content: str) -> str:
    try:
        parsed = json.loads(content)
        return str(parsed.get("speech", ""))
    except json.JSONDecodeError:
        return content


def generate_answer(client: OpenAI, model: str, question: str) -> str:
    completion = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": NAPOLEON_SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
    )
    return parse_speech(completion.choices[0].message.content or "{}")


def write_outputs(rows: list[dict], output_dir: Path, base_model: str, fine_tuned_model: str) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    jsonl_path = output_dir / f"no_rag_model_eval_{timestamp}.jsonl"
    md_path = output_dir / f"no_rag_model_eval_{timestamp}.md"

    with jsonl_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    with md_path.open("w", encoding="utf-8") as f:
        f.write(f"# No-RAG model eval {timestamp}\n\n")
        f.write(f"Base model: `{base_model}`\n\n")
        f.write(f"Fine-tuned model: `{fine_tuned_model}`\n\n")
        f.write("Ce rapport compare uniquement les réponses sans RAG.\n\n")
        for row in rows:
            f.write(f"## {row['id']}\n\n")
            f.write(f"Catégorie: `{row['category']}`\n\n")
            f.write(f"Question: {row['question']}\n\n")
            if row.get("notes"):
                f.write(f"Notes: {row['notes']}\n\n")
            f.write(f"### Base non fine-tuné\n\n{row['base_answer']}\n\n")
            f.write(f"### Fine-tuné\n\n{row['fine_tuned_answer']}\n\n")
    return jsonl_path, md_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Comparer deux modèles sans RAG.")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--base-model", default=DEFAULT_BASE_MODEL)
    parser.add_argument("--fine-tuned-model", default=DEFAULT_FINE_TUNED_MODEL)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    cases = load_cases(Path(args.dataset), args.limit)
    client = make_client()
    rows: list[dict] = []
    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] {case.id}: {case.question}")
        rows.append(
            {
                "id": case.id,
                "category": case.category,
                "question": case.question,
                "notes": case.notes,
                "base_model": args.base_model,
                "fine_tuned_model": args.fine_tuned_model,
                "base_answer": generate_answer(client, args.base_model, case.question),
                "fine_tuned_answer": generate_answer(client, args.fine_tuned_model, case.question),
            }
        )

    jsonl_path, md_path = write_outputs(rows, Path(args.output_dir), args.base_model, args.fine_tuned_model)
    print(f"\nJSONL: {jsonl_path}")
    print(f"Markdown: {md_path}")


if __name__ == "__main__":
    main()
