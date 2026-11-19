"""
Audit et reconstruction des datasets de fine-tuning.

Exemples :
  python pipeline/dataset_curator.py audit --input data/openai/napoleon_train_flags_false.jsonl data/openai/napoleon_test_flags_false.jsonl
  python pipeline/dataset_curator.py build --exclude-suspicious
"""

import argparse
import glob
import hashlib
import json
import random
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).parent.parent
SYSTEM_PROMPT = "Tu es Napoléon Bonaparte, Empereur des Français. Tu réponds toujours à la première personne."

DEFAULT_TRAINING_GLOB = str(ROOT / "data" / "training" / "*.jsonl")
DEFAULT_OUTPUT_DIR = ROOT / "data" / "openai"

PROTECTED_GROUP_TERMS = re.compile(
    r"\b(anglais|autrichiens|prussiens|russes|turcs|arabes|juifs|cophtes|"
    r"musulmans|mahom[ée]tans|b[ée]douins|albanais|grecs|race|peuple)\b",
    re.IGNORECASE,
)
DEGRADING_TERMS = re.compile(
    r"\b(barbare|barbares|sauvage|sauvages|f[ée]roce|f[ée]roces|"
    r"inf[ée]rieur|inf[ée]rieurs|fanatique|fanatiques|hideux|"
    r"extermin|massacr|ch[aâ]tier|souill)\w*\b",
    re.IGNORECASE,
)
VIOLENCE_TERMS = re.compile(
    r"\b(tuer|tu[ée]s?|mort|morts|mourir|fusill|pend|ex[ée]cut|"
    r"massacr|[ée]gorg|br[ûu]l|d[ée]truire|d[ée]truit|sang|"
    r"bombes?|canons?|fusils?|cartouches?|attaque|bataille)\w*\b",
    re.IGNORECASE,
)
EDITORIAL_TERMS = re.compile(
    r"\b(napol[ée]on bonaparte n'existe plus|sa vie appartient [aà] l'histoire|"
    r"l'auteur|ce volume|note de l'[ée]diteur|table des mati[èe]res)\b",
    re.IGNORECASE,
)
FIRST_PERSON_TERMS = re.compile(r"\b(je|j'|moi|mon|ma|mes|me|m'|nous|notre|nos)\b", re.IGNORECASE)


def load_jsonl(path: Path) -> list[tuple[int, dict[str, Any]]]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if line.strip():
                rows.append((line_no, json.loads(line)))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def normalize_example(ex: dict[str, Any]) -> dict[str, Any]:
    ex = dict(ex)
    ex.pop("_meta", None)
    return ex


def fingerprint(ex: dict[str, Any]) -> str:
    normalized = normalize_example(ex)
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def text_of(ex: dict[str, Any]) -> tuple[str, str, str]:
    messages = ex.get("messages", [])
    system = messages[0].get("content", "") if len(messages) > 0 else ""
    user = messages[1].get("content", "") if len(messages) > 1 else ""
    assistant = messages[2].get("content", "") if len(messages) > 2 else ""
    return system, user, assistant


def audit_example(ex: dict[str, Any]) -> list[str]:
    reasons = []
    messages = ex.get("messages")
    if not isinstance(messages, list) or len(messages) != 3:
        return ["invalid_messages_shape"]

    roles = [message.get("role") for message in messages]
    if roles != ["system", "user", "assistant"]:
        reasons.append("invalid_roles")

    system, user, assistant = text_of(ex)
    if system != SYSTEM_PROMPT:
        reasons.append("system_prompt_changed")
    if not user.strip() or not assistant.strip():
        reasons.append("empty_content")
    if len(user) < 12:
        reasons.append("user_too_short")
    if len(assistant) < 80:
        reasons.append("assistant_too_short")
    if len(assistant) > 4500:
        reasons.append("assistant_too_long")
    if not FIRST_PERSON_TERMS.search(assistant):
        reasons.append("weak_first_person")
    if EDITORIAL_TERMS.search(assistant):
        reasons.append("editorial_or_not_napoleon")
    if PROTECTED_GROUP_TERMS.search(assistant) and DEGRADING_TERMS.search(assistant):
        reasons.append("protected_group_degrading_language")
    elif DEGRADING_TERMS.search(assistant):
        reasons.append("degrading_language")
    if VIOLENCE_TERMS.search(assistant):
        reasons.append("violence_terms")

    return reasons


def audit(paths: list[Path], suspicious_path: Path, report_path: Path) -> None:
    counts = Counter()
    reason_counts = Counter()
    seen = {}
    suspicious = []

    for path in paths:
        for line_no, ex in load_jsonl(path):
            counts["total"] += 1
            fp = fingerprint(ex)
            if fp in seen:
                counts["duplicates"] += 1
                reasons = ["duplicate"]
            else:
                seen[fp] = (str(path), line_no)
                reasons = audit_example(ex)

            if reasons:
                counts["suspicious"] += 1
                reason_counts.update(reasons)
                suspicious.append({
                    "source_file": str(path),
                    "line": line_no,
                    "reasons": reasons,
                    "example": ex,
                })

    write_jsonl(suspicious_path, suspicious)

    lines = [
        "# Dataset audit",
        "",
        f"- Total examples: {counts['total']}",
        f"- Duplicates: {counts['duplicates']}",
        f"- Suspicious examples: {counts['suspicious']}",
        f"- Suspicious output: `{suspicious_path}`",
        "",
        "## Reasons",
        "",
    ]
    for reason, count in reason_counts.most_common():
        lines.append(f"- `{reason}`: {count}")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Audit terminé: {counts['total']} exemples, {counts['suspicious']} suspects")
    print(f"Rapport: {report_path}")
    print(f"Suspects: {suspicious_path}")


def load_excluded_fingerprints(paths: list[Path]) -> set[str]:
    excluded = set()
    for path in paths:
        if not path.exists():
            continue
        for _, row in load_jsonl(path):
            ex = row.get("example", row)
            excluded.add(fingerprint(ex))
    return excluded


def build(
    source_glob: str,
    output_train: Path,
    output_test: Path,
    excluded_paths: list[Path],
    exclude_suspicious: bool,
    test_ratio: float,
    seed: int,
) -> None:
    excluded = load_excluded_fingerprints(excluded_paths)
    seen = set()
    rows = []
    removed = Counter()

    for source in sorted(glob.glob(source_glob)):
        for _, ex in load_jsonl(Path(source)):
            normalized = normalize_example(ex)
            fp = fingerprint(normalized)
            if fp in seen:
                removed["duplicate"] += 1
                continue
            seen.add(fp)
            if fp in excluded:
                removed["moderation_excluded"] += 1
                continue
            reasons = audit_example(normalized)
            if exclude_suspicious and reasons:
                removed["suspicious"] += 1
                continue
            rows.append(normalized)

    random.seed(seed)
    random.shuffle(rows)
    n_test = max(1, int(len(rows) * test_ratio))
    test = rows[:n_test]
    train = rows[n_test:]

    write_jsonl(output_train, train)
    write_jsonl(output_test, test)

    print(f"Dataset reconstruit: {len(train)} train / {len(test)} test")
    if removed:
        print("Exclus:")
        for reason, count in removed.most_common():
            print(f"  {reason}: {count}")
    print(f"Train: {output_train}")
    print(f"Test:  {output_test}")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--input", nargs="+", required=True)
    audit_parser.add_argument("--suspicious-output", default=str(DEFAULT_OUTPUT_DIR / "dataset_suspicious.jsonl"))
    audit_parser.add_argument("--report", default=str(DEFAULT_OUTPUT_DIR / "dataset_audit.md"))

    build_parser = sub.add_parser("build")
    build_parser.add_argument("--source-glob", default=DEFAULT_TRAINING_GLOB)
    build_parser.add_argument("--output-train", default=str(DEFAULT_OUTPUT_DIR / "napoleon_train_curated.jsonl"))
    build_parser.add_argument("--output-test", default=str(DEFAULT_OUTPUT_DIR / "napoleon_test_curated.jsonl"))
    build_parser.add_argument(
        "--exclude",
        nargs="*",
        default=[
            str(DEFAULT_OUTPUT_DIR / "flagged_examples.jsonl"),
            str(DEFAULT_OUTPUT_DIR / "flagged_examples_flags_false.jsonl"),
        ],
    )
    build_parser.add_argument("--exclude-suspicious", action="store_true")
    build_parser.add_argument("--test-ratio", type=float, default=0.10)
    build_parser.add_argument("--seed", type=int, default=42)

    args = parser.parse_args()
    if args.command == "audit":
        audit(
            paths=[Path(path) for path in args.input],
            suspicious_path=Path(args.suspicious_output),
            report_path=Path(args.report),
        )
    elif args.command == "build":
        build(
            source_glob=args.source_glob,
            output_train=Path(args.output_train),
            output_test=Path(args.output_test),
            excluded_paths=[Path(path) for path in args.exclude],
            exclude_suspicious=args.exclude_suspicious,
            test_ratio=args.test_ratio,
            seed=args.seed,
        )


if __name__ == "__main__":
    main()
