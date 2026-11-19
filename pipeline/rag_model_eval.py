"""
Compare deux modèles avec RAG sur le dataset d'évaluation.

Les mêmes sources RAG sont utilisées pour les deux modèles afin de comparer
uniquement le comportement générationnel.

Usage:
  python3 pipeline/rag_model_eval.py
  python3 pipeline/rag_model_eval.py --base-model gpt-4.1-mini --fine-tuned-model ft:gpt-4.1-mini-2025-04-14:organizations::DkstSMs5
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

sys.path.insert(0, str(Path(__file__).parent))
from rag_query import search as rag_search  # noqa: E402


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = ROOT_DIR / "data" / "eval" / "rag_eval_questions.jsonl"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "data" / "eval" / "runs"
DEFAULT_BASE_MODEL = os.getenv("RAG_BASE_MODEL", "gpt-4.1-mini")
DEFAULT_FINE_TUNED_MODEL = os.getenv(
    "RAG_FINE_TUNED_MODEL",
    "ft:gpt-4.1-mini-2025-04-14:organizations::DkstSMs5",
)
NO_RAG_SPEECH = "Je ne trouve point cela dans mes archives. Interrogez-moi sur les textes, les campagnes, les réformes ou les affaires que mes documents attestent."

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
    expect_rag_sources: bool
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
                expect_rag_sources=bool(raw["expect_rag_sources"]),
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


def format_rag_context(sources: list[dict[str, Any]]) -> str:
    blocks = []
    for index, source in enumerate(sources, start=1):
        blocks.append(
            "\n".join(
                [
                    f"[Source {index}]",
                    f"Titre: {source.get('title', '')}",
                    f"Chemin: {source.get('source_path', '')}",
                    f"Langue: {source.get('language', '')}",
                    f"Thème: {source.get('theme', '')}",
                    f"Extrait: {str(source.get('text', ''))[:1600]}",
                ]
            )
        )
    return "\n\n".join(blocks)


def build_rag_prompt(sources: list[dict[str, Any]]) -> str:
    return f"""{NAPOLEON_SYSTEM_PROMPT}

Base documentaire prioritaire :
- Réponds uniquement à partir des extraits ci-dessous.
- Privilégie les sources en français lorsque plusieurs extraits sont pertinents.
- Si les extraits ne permettent pas de répondre précisément à la question, dis que tu ne trouves pas cela dans tes archives.

Extraits disponibles :
{format_rag_context(sources)}"""


def parse_speech(content: str) -> str:
    try:
        parsed = json.loads(content)
        return str(parsed.get("speech", ""))
    except json.JSONDecodeError:
        return content


def generate_with_rag(client: OpenAI, model: str, question: str, sources: list[dict[str, Any]]) -> str:
    if not sources:
        return NO_RAG_SPEECH
    completion = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": build_rag_prompt(sources)},
            {"role": "user", "content": question},
        ],
    )
    return parse_speech(completion.choices[0].message.content or "{}")


def write_outputs(rows: list[dict], output_dir: Path, base_model: str, fine_tuned_model: str) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    jsonl_path = output_dir / f"rag_model_eval_{timestamp}.jsonl"
    md_path = output_dir / f"rag_model_eval_{timestamp}.md"

    with jsonl_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    passed = sum(1 for row in rows if row["source_expectation_ok"])
    with md_path.open("w", encoding="utf-8") as f:
        f.write(f"# RAG model eval {timestamp}\n\n")
        f.write(f"Base model: `{base_model}`\n\n")
        f.write(f"Fine-tuned model: `{fine_tuned_model}`\n\n")
        f.write(f"Source expectation: {passed}/{len(rows)} OK\n\n")
        f.write("Ce rapport compare deux modèles avec les mêmes sources RAG.\n\n")
        for row in rows:
            status = "OK" if row["source_expectation_ok"] else "FAIL"
            f.write(f"## {row['id']} [{status}]\n\n")
            f.write(f"Catégorie: `{row['category']}`\n\n")
            f.write(f"Question: {row['question']}\n\n")
            if row.get("notes"):
                f.write(f"Notes: {row['notes']}\n\n")
            f.write(f"Sources: {row['source_count']} / attendu: {row['expect_rag_sources']}\n\n")
            f.write(f"### Base avec RAG\n\n{row['base_answer']}\n\n")
            f.write(f"### Fine-tuné avec RAG\n\n{row['fine_tuned_answer']}\n\n")
            if row["sources"]:
                f.write("### Sources top\n\n")
                for source in row["sources"]:
                    f.write(f"- {source.get('score')}: {source.get('source_path')} ({source.get('theme')})\n\n")
                    excerpt = str(source.get("text", "")).strip()
                    if excerpt:
                        f.write("> " + excerpt.replace("\n", "\n> ") + "\n\n")
    return jsonl_path, md_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Comparer deux modèles avec RAG.")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--base-model", default=DEFAULT_BASE_MODEL)
    parser.add_argument("--fine-tuned-model", default=DEFAULT_FINE_TUNED_MODEL)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--rag-limit", type=int, default=6)
    args = parser.parse_args()

    cases = load_cases(Path(args.dataset), args.limit)
    client = make_client()
    rows: list[dict] = []
    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] {case.id}: {case.question}")
        sources = rag_search(case.question, limit=args.rag_limit)
        source_count = len(sources)
        rows.append(
            {
                "id": case.id,
                "category": case.category,
                "question": case.question,
                "notes": case.notes,
                "expect_rag_sources": case.expect_rag_sources,
                "source_count": source_count,
                "source_expectation_ok": (source_count > 0) == case.expect_rag_sources,
                "base_model": args.base_model,
                "fine_tuned_model": args.fine_tuned_model,
                "base_answer": generate_with_rag(client, args.base_model, case.question, sources),
                "fine_tuned_answer": generate_with_rag(client, args.fine_tuned_model, case.question, sources),
                "sources": [
                    {
                        "id": source.get("id"),
                        "score": source.get("score"),
                        "title": source.get("title"),
                        "source_path": source.get("source_path"),
                        "theme": source.get("theme"),
                        "text": str(source.get("text", ""))[:2200],
                    }
                    for source in sources[:5]
                ],
            }
        )

    jsonl_path, md_path = write_outputs(rows, Path(args.output_dir), args.base_model, args.fine_tuned_model)
    print(f"\nSource expectation: {sum(1 for row in rows if row['source_expectation_ok'])}/{len(rows)} OK")
    print(f"JSONL: {jsonl_path}")
    print(f"Markdown: {md_path}")


if __name__ == "__main__":
    main()
