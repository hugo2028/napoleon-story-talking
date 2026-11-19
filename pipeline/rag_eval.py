"""
Compare les réponses avec et sans RAG sur un petit dataset d'évaluation.

Modes:
  direct: appelle le LLM depuis Python et utilise rag_query.py localement.
  server: appelle le backend Express /api/chat avec useRag true/false.
  retrieval-only: ne contacte aucun LLM, teste seulement si le RAG trouve des sources.

Exemples:
  python3 pipeline/rag_eval.py --mode retrieval-only
  python3 pipeline/rag_eval.py --mode direct --limit 3
  python3 pipeline/rag_eval.py --mode server --server-url http://127.0.0.1:3002
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

import httpx
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from rag_query import search as rag_search  # noqa: E402


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = ROOT_DIR / "data" / "eval" / "rag_eval_questions.jsonl"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "data" / "eval" / "runs"

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
    expected_terms: list[str]
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
                expected_terms=list(raw.get("expected_terms", [])),
                notes=raw.get("notes", ""),
            )
        )
    return cases[:limit] if limit else cases


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


def direct_llm(messages: list[dict[str, str]], model: str) -> str:
    load_dotenv(ROOT_DIR / ".env")
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("LLM_BASE_URL")
    if not api_key:
        raise RuntimeError("LLM_API_KEY ou OPENAI_API_KEY requis pour --mode direct.")

    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url)
    completion = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=messages,
    )
    return parse_speech(completion.choices[0].message.content or "{}")


def run_direct_case(case: EvalCase, model: str, rag_limit: int) -> dict[str, Any]:
    sources = rag_search(case.question, limit=rag_limit)
    with_rag = NO_RAG_SPEECH
    if sources:
        with_rag = direct_llm(
            [
                {"role": "system", "content": build_rag_prompt(sources)},
                {"role": "user", "content": case.question},
            ],
            model,
        )

    without_rag = direct_llm(
        [
            {"role": "system", "content": NAPOLEON_SYSTEM_PROMPT},
            {"role": "user", "content": case.question},
        ],
        model,
    )
    return {"with_rag": with_rag, "without_rag": without_rag, "sources": sources}


def run_server_case(case: EvalCase, server_url: str) -> dict[str, Any]:
    payload = {"messages": [{"role": "user", "content": case.question}]}
    with httpx.Client(timeout=60) as client:
        rag_response = client.post(f"{server_url.rstrip('/')}/api/chat", json={**payload, "useRag": True})
        rag_response.raise_for_status()
        no_rag_response = client.post(f"{server_url.rstrip('/')}/api/chat", json={**payload, "useRag": False})
        no_rag_response.raise_for_status()
    rag_json = rag_response.json()
    no_rag_json = no_rag_response.json()
    return {
        "with_rag": rag_json.get("speech", ""),
        "without_rag": no_rag_json.get("speech", ""),
        "sources": rag_json.get("sources", []),
    }


def run_retrieval_only_case(case: EvalCase, rag_limit: int) -> dict[str, Any]:
    sources = rag_search(case.question, limit=rag_limit)
    return {
        "with_rag": NO_RAG_SPEECH if not sources else "[sources trouvées; réponse LLM non exécutée]",
        "without_rag": "[non exécuté en retrieval-only]",
        "sources": sources,
    }


def contains_expected_terms(answer: str, terms: list[str]) -> bool | None:
    if not terms:
        return None
    lower = answer.lower()
    return any(term.lower() in lower for term in terms)


def evaluate_case(case: EvalCase, result: dict[str, Any]) -> dict[str, Any]:
    sources = result.get("sources", [])
    source_count = len(sources)
    source_expectation_ok = (source_count > 0) == case.expect_rag_sources
    terms_ok = contains_expected_terms(result.get("with_rag", ""), case.expected_terms)
    return {
        "id": case.id,
        "category": case.category,
        "question": case.question,
        "expect_rag_sources": case.expect_rag_sources,
        "source_count": source_count,
        "source_expectation_ok": source_expectation_ok,
        "with_rag_terms_ok": terms_ok,
        "with_rag": result.get("with_rag", ""),
        "without_rag": result.get("without_rag", ""),
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
        "notes": case.notes,
    }


def write_outputs(rows: list[dict[str, Any]], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    jsonl_path = output_dir / f"rag_eval_{timestamp}.jsonl"
    md_path = output_dir / f"rag_eval_{timestamp}.md"

    with jsonl_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    passed = sum(1 for row in rows if row["source_expectation_ok"])
    with md_path.open("w", encoding="utf-8") as f:
        f.write(f"# RAG eval {timestamp}\n\n")
        f.write(f"Source expectation: {passed}/{len(rows)} OK\n\n")
        for row in rows:
            status = "OK" if row["source_expectation_ok"] else "FAIL"
            f.write(f"## {row['id']} [{status}]\n\n")
            f.write(f"Question: {row['question']}\n\n")
            f.write(f"Sources: {row['source_count']} / attendu: {row['expect_rag_sources']}\n\n")
            f.write(f"Avec RAG: {row['with_rag']}\n\n")
            f.write(f"Sans RAG: {row['without_rag']}\n\n")
            if row["sources"]:
                f.write("Sources top:\n")
                for source in row["sources"]:
                    f.write(f"- {source.get('score')}: {source.get('source_path')} ({source.get('theme')})\n")
                    excerpt = str(source.get("text", "")).strip()
                    if excerpt:
                        f.write("\n")
                        f.write("> " + excerpt.replace("\n", "\n> ") + "\n\n")
                f.write("\n")
    return jsonl_path, md_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Comparer les réponses avec et sans RAG.")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--mode", choices=["direct", "server", "retrieval-only"], default="retrieval-only")
    parser.add_argument("--server-url", default="http://127.0.0.1:3002")
    parser.add_argument("--model", default=os.getenv("LLM_MODEL", "gpt-4o-mini"))
    parser.add_argument("--limit", type=int, default=None, help="Limiter le nombre de cas évalués")
    parser.add_argument("--rag-limit", type=int, default=6)
    args = parser.parse_args()

    cases = load_cases(Path(args.dataset), args.limit)
    rows: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] {case.id}: {case.question}")
        if args.mode == "direct":
            result = run_direct_case(case, args.model, args.rag_limit)
        elif args.mode == "server":
            result = run_server_case(case, args.server_url)
        else:
            result = run_retrieval_only_case(case, args.rag_limit)
        rows.append(evaluate_case(case, result))

    jsonl_path, md_path = write_outputs(rows, Path(args.output_dir))
    passed = sum(1 for row in rows if row["source_expectation_ok"])
    print(f"\nSource expectation: {passed}/{len(rows)} OK")
    print(f"JSONL: {jsonl_path}")
    print(f"Markdown: {md_path}")


if __name__ == "__main__":
    main()
