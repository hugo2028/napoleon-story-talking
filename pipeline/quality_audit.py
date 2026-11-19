"""
Audit qualité pour fine-tuning local.

Cet audit ne filtre pas pour les politiques OpenAI. Il cherche uniquement les
exemples faibles pour un modèle local : mauvais format, réponse peu
napoléonienne, traces éditoriales, anachronismes, réponses trop courtes ou
questions trop vagues.

Usage :
  python pipeline/quality_audit.py --input napoleon-corpus/datasets/sft/training/*.jsonl
  python pipeline/quality_audit.py --input data/openai/napoleon_train_flags_false.jsonl data/openai/napoleon_test_flags_false.jsonl
"""

import argparse
import glob
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).parent.parent
DEFAULT_OUTPUT = ROOT / "data" / "quality"

EXPECTED_SYSTEM = "Tu es Napoléon Bonaparte, Empereur des Français. Tu réponds toujours à la première personne."

FIRST_PERSON = re.compile(r"\b(je|j'|moi|mon|ma|mes|me|m'|nous|notre|nos)\b", re.IGNORECASE)
EDITORIAL = re.compile(
    r"\b(note de l'[ée]diteur|table des mati[èe]res|chapitre|tome|volume|"
    r"page suivante|voir plus haut|l'auteur|le lecteur|napol[ée]on bonaparte n'existe plus|"
    r"sa vie appartient [aà] l'histoire)\b",
    re.IGNORECASE,
)
ANACHRONISM = re.compile(
    r"\b(internet|ordinateur|smartphone|r[ée]seaux sociaux|intelligence artificielle|"
    r"transhumanisme|blockchain|cryptomonnaie|startup|email|e-mail|application mobile)\b",
    re.IGNORECASE,
)
GENERIC_QUESTION = re.compile(
    r"^(que pensez-vous|qu'en pensez-vous|pouvez-vous expliquer|pouvez-vous d[ée]crire|"
    r"comment voyez-vous|que pouvez-vous nous dire)\s*\??$",
    re.IGNORECASE,
)
WEAK_STYLE = re.compile(
    r"\b(en tant que|je suis une intelligence artificielle|selon le passage|dans ce texte|"
    r"il semble que|on peut dire que)\b",
    re.IGNORECASE,
)


def iter_input_paths(patterns: list[str]) -> list[Path]:
    paths: list[Path] = []
    for pattern in patterns:
        matches = glob.glob(pattern)
        if matches:
            paths.extend(Path(match) for match in matches)
        else:
            paths.append(Path(pattern))
    return sorted(dict.fromkeys(paths))


def load_jsonl(path: Path):
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if line.strip():
                yield line_no, json.loads(line)


def fingerprint(example: dict[str, Any]) -> str:
    normalized = dict(example)
    normalized.pop("_meta", None)
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def get_messages(example: dict[str, Any]) -> tuple[str, str, str]:
    messages = example.get("messages", [])
    system = messages[0].get("content", "") if len(messages) > 0 and isinstance(messages[0], dict) else ""
    user = messages[1].get("content", "") if len(messages) > 1 and isinstance(messages[1], dict) else ""
    assistant = messages[2].get("content", "") if len(messages) > 2 and isinstance(messages[2], dict) else ""
    return system, user, assistant


def score_quality(example: dict[str, Any], duplicate: bool) -> tuple[int, list[str]]:
    reasons: list[str] = []
    score = 100

    messages = example.get("messages")
    if not isinstance(messages, list) or len(messages) != 3:
        return 0, ["invalid_message_shape"]

    roles = [message.get("role") for message in messages if isinstance(message, dict)]
    if roles != ["system", "user", "assistant"]:
        score -= 40
        reasons.append("invalid_roles")

    system, user, assistant = get_messages(example)

    if system != EXPECTED_SYSTEM:
        score -= 10
        reasons.append("unexpected_system_prompt")
    if duplicate:
        score -= 35
        reasons.append("duplicate")
    if not user.strip() or not assistant.strip():
        score -= 60
        reasons.append("empty_user_or_assistant")
    if len(user.strip()) < 20:
        score -= 10
        reasons.append("question_too_short")
    if GENERIC_QUESTION.search(user.strip()):
        score -= 15
        reasons.append("question_too_generic")
    if len(assistant.strip()) < 120:
        score -= 25
        reasons.append("assistant_too_short")
    if len(assistant.strip()) > 3500:
        score -= 10
        reasons.append("assistant_very_long")
    if not FIRST_PERSON.search(assistant):
        score -= 25
        reasons.append("weak_first_person")
    if EDITORIAL.search(assistant):
        score -= 30
        reasons.append("editorial_trace")
    if WEAK_STYLE.search(assistant):
        score -= 25
        reasons.append("weak_or_meta_style")
    if ANACHRONISM.search(user) or ANACHRONISM.search(assistant):
        score -= 20
        reasons.append("anachronism")
    if assistant.count("\n") > 8:
        score -= 5
        reasons.append("too_many_line_breaks")

    return max(score, 0), reasons


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", nargs="+", required=True)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--min-score", type=int, default=75)
    parser.add_argument("--max-review", type=int, default=300)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    paths = iter_input_paths(args.input)

    seen: set[str] = set()
    totals = Counter()
    reason_counts = Counter()
    review_rows: list[dict[str, Any]] = []

    for path in paths:
        for line_no, example in load_jsonl(path):
            totals["examples"] += 1
            fp = fingerprint(example)
            duplicate = fp in seen
            seen.add(fp)

            score, reasons = score_quality(example, duplicate)
            totals["score_sum"] += score
            if score < args.min_score:
                totals["review_needed"] += 1
                reason_counts.update(reasons)
                review_rows.append({
                    "source_file": str(path),
                    "line": line_no,
                    "quality_score": score,
                    "reasons": reasons,
                    "example": example,
                })

    review_rows.sort(key=lambda row: row["quality_score"])
    limited_review = review_rows[:args.max_review]

    review_path = output_dir / "quality_review_priority.jsonl"
    report_path = output_dir / "quality_audit.md"
    write_jsonl(review_path, limited_review)

    avg = totals["score_sum"] / max(totals["examples"], 1)
    report = [
        "# Quality audit",
        "",
        f"- Input files: {len(paths)}",
        f"- Total examples: {totals['examples']}",
        f"- Average score: {avg:.1f}/100",
        f"- Review needed (< {args.min_score}): {totals['review_needed']}",
        f"- Priority review exported: {len(limited_review)}",
        f"- Review file: `{review_path}`",
        "",
        "## Reasons",
        "",
    ]
    for reason, count in reason_counts.most_common():
        report.append(f"- `{reason}`: {count}")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(report) + "\n", encoding="utf-8")

    print(f"Audit qualité terminé: {totals['examples']} exemples")
    print(f"Score moyen: {avg:.1f}/100")
    print(f"À revoir: {totals['review_needed']} exemples")
    print(f"Rapport: {report_path}")
    print(f"Revue prioritaire: {review_path}")


if __name__ == "__main__":
    main()
