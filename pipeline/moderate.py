"""
Filtrage des exemples via l'API de modération OpenAI.
Lit napoleon_train.jsonl et napoleon_test.jsonl,
supprime les exemples flaggés, sauvegarde les versions nettoyées.
"""

import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
import openai
from tqdm import tqdm

load_dotenv(Path(__file__).parent.parent / ".env")

OUTPUT_DIR = Path(__file__).parent.parent / "data" / "openai"
TRAIN_PATH = OUTPUT_DIR / "napoleon_train.jsonl"
TEST_PATH  = OUTPUT_DIR / "napoleon_test.jsonl"
TRAIN_CLEAN = OUTPUT_DIR / "napoleon_train_clean.jsonl"
TEST_CLEAN  = OUTPUT_DIR / "napoleon_test_clean.jsonl"
TRAIN_STRICT = OUTPUT_DIR / "napoleon_train_strict.jsonl"
TEST_STRICT = OUTPUT_DIR / "napoleon_test_strict.jsonl"
FLAGGED_PATH = OUTPUT_DIR / "flagged_examples.jsonl"
FLAGGED_STRICT_PATH = OUTPUT_DIR / "flagged_examples_strict.jsonl"


def load_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def get_text(example: dict) -> str:
    """Concatène tous les messages pour la modération."""
    return " ".join(m["content"] for m in example["messages"])


def moderation_result(client: openai.OpenAI, text: str):
    return client.moderations.create(input=text).results[0]


def moderation_results(client: openai.OpenAI, texts: list[str], retries: int = 6):
    delay = 2.0
    for attempt in range(retries):
        try:
            return client.moderations.create(input=texts).results
        except openai.RateLimitError:
            if attempt == retries - 1:
                raise
            print(f"  Rate limit, nouvelle tentative dans {delay:.1f}s...")
            time.sleep(delay)
            delay = min(delay * 2, 60)


def score(result, category: str) -> float:
    scores = result.category_scores
    if isinstance(scores, dict):
        return float(scores.get(category, 0) or 0)
    return float(getattr(scores, category.replace("/", "_"), 0) or 0)


def categories(result) -> dict:
    raw_categories = result.categories
    raw_scores = result.category_scores
    if hasattr(raw_categories, "model_dump"):
        cats = raw_categories.model_dump()
    elif isinstance(raw_categories, dict):
        cats = raw_categories
    else:
        cats = vars(raw_categories)

    if hasattr(raw_scores, "model_dump"):
        scores = raw_scores.model_dump()
    elif isinstance(raw_scores, dict):
        scores = raw_scores
    else:
        scores = vars(raw_scores)
    return {"categories": cats, "category_scores": scores}


def should_remove(result, hate_threshold: float | None, violence_threshold: float | None) -> bool:
    if result.flagged:
        return True
    if hate_threshold is not None and score(result, "hate") >= hate_threshold:
        return True
    if hate_threshold is not None and score(result, "hate/threatening") >= hate_threshold:
        return True
    if violence_threshold is not None and score(result, "violence") >= violence_threshold:
        return True
    if violence_threshold is not None and score(result, "violence/graphic") >= violence_threshold:
        return True
    return False


def moderate_batch(client: openai.OpenAI, texts: list[str]) -> list[bool]:
    """Retourne True si l'exemple est flaggé."""
    flagged = []
    for text in texts:
        try:
            result = moderation_result(client, text)
            flagged.append(result.flagged)
        except Exception as e:
            print(f"  Erreur modération: {e}")
            flagged.append(False)
        time.sleep(0.05)  # éviter le rate limit
    return flagged


def filter_file(client: openai.OpenAI, path: Path, clean_path: Path, label: str):
    examples = load_jsonl(path)
    print(f"\n{label}: {len(examples)} exemples")

    texts = [get_text(ex) for ex in examples]
    flagged_mask = []

    for i in tqdm(range(0, len(texts), 50), desc=f"Modération {label}"):
        batch = texts[i:i+50]
        flagged_mask.extend(moderate_batch(client, batch))

    clean = [ex for ex, f in zip(examples, flagged_mask) if not f]
    flagged = [ex for ex, f in zip(examples, flagged_mask) if f]

    print(f"  ✓ Conservés: {len(clean)} | Supprimés: {len(flagged)}")

    with open(clean_path, "w", encoding="utf-8") as f:
        for ex in clean:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")
    print(f"  → {clean_path.name}")

    return clean, flagged


def filter_file_strict(
    client: openai.OpenAI,
    path: Path,
    clean_path: Path,
    label: str,
    hate_threshold: float | None,
    violence_threshold: float | None,
    batch_size: int,
    sleep_seconds: float,
):
    examples = load_jsonl(path)
    print(f"\n{label}: {len(examples)} exemples")

    clean = []
    flagged = []
    for start in tqdm(range(0, len(examples), batch_size), desc=f"Modération stricte {label}"):
        batch = examples[start:start + batch_size]
        texts = [get_text(ex) for ex in batch]
        try:
            results = moderation_results(client, texts)
        except Exception as e:
            raise RuntimeError(f"Erreur modération batch ligne {start + 1}: {e}") from e

        for offset, ex in enumerate(batch):
            result = results[offset]
            if result is None:
                flagged.append({
                    "source_file": str(path),
                    "line": start + offset + 1,
                    "moderation": {"error": "batch moderation failed"},
                    "example": ex,
                })
                continue

            remove = should_remove(result, hate_threshold, violence_threshold)
            details = categories(result)
            if remove:
                flagged.append({
                    "source_file": str(path),
                    "line": start + offset + 1,
                    "moderation": details,
                    "example": ex,
                })
            else:
                clean.append(ex)
        time.sleep(sleep_seconds)

    print(f"  Conservés: {len(clean)} | Supprimés: {len(flagged)}")

    with open(clean_path, "w", encoding="utf-8") as f:
        for ex in clean:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")
    print(f"  → {clean_path.name}")

    return clean, flagged


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true", help="Filtrer aussi par scores de catégories")
    parser.add_argument("--flagged-only", action="store_true",
                        help="Ne supprimer que les exemples avec flagged=true")
    parser.add_argument("--hate-threshold", type=float, default=0.05,
                        help="Supprimer aussi si hate ou hate/threatening dépasse ce score")
    parser.add_argument("--violence-threshold", type=float, default=None,
                        help="Optionnel: supprimer aussi si violence ou violence/graphic dépasse ce score")
    parser.add_argument("--input-train", default=str(TRAIN_CLEAN))
    parser.add_argument("--input-test", default=str(TEST_CLEAN))
    parser.add_argument("--output-train", default=str(TRAIN_STRICT))
    parser.add_argument("--output-test", default=str(TEST_STRICT))
    parser.add_argument("--flagged-output", default=str(FLAGGED_STRICT_PATH))
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--sleep", type=float, default=1.0)
    args = parser.parse_args()

    api_key = os.getenv("LLM_API_KEY")
    client = openai.OpenAI(api_key=api_key)

    all_flagged = []
    hate_threshold = None if args.flagged_only else args.hate_threshold
    violence_threshold = None if args.flagged_only else args.violence_threshold

    if args.strict:
        train_clean, train_flagged = filter_file_strict(
            client,
            Path(args.input_train),
            Path(args.output_train),
            "Train",
            hate_threshold,
            violence_threshold,
            args.batch_size,
            args.sleep,
        )
        test_clean, test_flagged = filter_file_strict(
            client,
            Path(args.input_test),
            Path(args.output_test),
            "Test",
            hate_threshold,
            violence_threshold,
            args.batch_size,
            args.sleep,
        )
        flagged_path = Path(args.flagged_output)
    else:
        train_clean, train_flagged = filter_file(client, TRAIN_PATH, TRAIN_CLEAN, "Train")
        test_clean, test_flagged   = filter_file(client, TEST_PATH,  TEST_CLEAN,  "Test")
        flagged_path = FLAGGED_PATH

    all_flagged = train_flagged + test_flagged
    if all_flagged:
        with open(flagged_path, "w", encoding="utf-8") as f:
            for ex in all_flagged:
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")
        print(f"\n{len(all_flagged)} exemples flaggés sauvegardés dans {flagged_path}")

    print(f"\n=== Résumé ===")
    print(f"Train: {len(train_clean)} exemples propres")
    print(f"Test:  {len(test_clean)} exemples propres")
    if args.strict:
        print(f"\nRelancez le fine-tuning avec les fichiers _strict :")
        print(f"  python pipeline/finetune_openai.py --train-file {args.output_train} --test-file {args.output_test}")
    else:
        print(f"\nRelancez le fine-tuning avec les fichiers _clean :")
        print(f"  python pipeline/finetune_openai.py --train-file {TRAIN_CLEAN} --test-file {TEST_CLEAN}")


if __name__ == "__main__":
    main()
