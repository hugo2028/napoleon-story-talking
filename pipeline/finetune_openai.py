"""
Fine-tuning OpenAI — Napoléon Bonaparte

Étapes :
  1. Consolider tous les JSONL de napoleon-corpus/datasets/sft/training/
  2. Nettoyer (supprimer _meta, valider format)
  3. Shuffle + split 90/10 train / test
  4. Uploader sur OpenAI
  5. Lancer le job fine-tuning gpt-4o-mini-2024-07-18
  6. Surveiller le statut
"""

import json
import os
import random
import time
from pathlib import Path

from dotenv import load_dotenv
import openai

load_dotenv(Path(__file__).parent.parent / ".env")

TRAINING_DIR = Path(__file__).parent.parent / "napoleon-corpus" / "datasets" / "sft" / "training"
OUTPUT_DIR   = Path(__file__).parent.parent / "data" / "openai"
TRAIN_PATH   = OUTPUT_DIR / "napoleon_train.jsonl"
TEST_PATH    = OUTPUT_DIR / "napoleon_test.jsonl"

BASE_MODEL   = "gpt-4.1-mini-2025-04-14"
TEST_RATIO   = 0.10
SEED         = 42


# ---------------------------------------------------------------------------
# 1. Chargement + nettoyage
# ---------------------------------------------------------------------------

def load_all_examples() -> list[dict]:
    examples = []
    for path in sorted(TRAINING_DIR.glob("*.jsonl")):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                ex = json.loads(line)
                # Supprimer _meta (OpenAI le rejette)
                ex.pop("_meta", None)
                examples.append(ex)
        print(f"  {path.name}: {sum(1 for _ in open(path))} exemples")
    return examples


def validate(examples: list[dict]) -> list[dict]:
    valid = []
    skipped = 0
    for ex in examples:
        msgs = ex.get("messages", [])
        if len(msgs) != 3:
            skipped += 1
            continue
        roles = [m.get("role") for m in msgs]
        if roles != ["system", "user", "assistant"]:
            skipped += 1
            continue
        if not all(m.get("content", "").strip() for m in msgs):
            skipped += 1
            continue
        valid.append(ex)
    if skipped:
        print(f"  ⚠ {skipped} exemples invalides ignorés")
    return valid


# ---------------------------------------------------------------------------
# 2. Split train / test
# ---------------------------------------------------------------------------

def split(examples: list[dict], test_ratio: float, seed: int):
    random.seed(seed)
    shuffled = examples[:]
    random.shuffle(shuffled)
    n_test = max(1, int(len(shuffled) * test_ratio))
    return shuffled[n_test:], shuffled[:n_test]


def save_jsonl(examples: list[dict], path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")
    print(f"  → {path.name}: {len(examples)} exemples")


# ---------------------------------------------------------------------------
# 3. Upload + fine-tuning
# ---------------------------------------------------------------------------

def upload_file(client: openai.OpenAI, path: Path, purpose: str) -> str:
    print(f"  Upload {path.name}...")
    with open(path, "rb") as f:
        response = client.files.create(file=f, purpose=purpose)
    print(f"  ✓ file_id: {response.id}")
    return response.id


def start_finetune(client: openai.OpenAI, train_file_id: str, val_file_id: str, model: str) -> str:
    print(f"\nLancement fine-tuning sur {model}...")
    job = client.fine_tuning.jobs.create(
        training_file=train_file_id,
        validation_file=val_file_id,
        model=model,
        hyperparameters={"n_epochs": "auto"},
    )
    print(f"  ✓ job_id: {job.id}")
    print(f"  Statut initial: {job.status}")
    return job.id


def monitor(client: openai.OpenAI, job_id: str):
    print("\nSurveillance du job (Ctrl+C pour arrêter le monitoring)...")
    last_event_id = None
    try:
        while True:
            job = client.fine_tuning.jobs.retrieve(job_id)
            status = job.status

            # Afficher les nouveaux events
            events = client.fine_tuning.jobs.list_events(fine_tuning_job_id=job_id, limit=10)
            new_events = []
            for ev in reversed(list(events.data)):
                if ev.id != last_event_id:
                    new_events.append(ev)
            for ev in new_events:
                print(f"  [{ev.created_at}] {ev.message}")
                last_event_id = ev.id

            if status in ("succeeded", "failed", "cancelled"):
                print(f"\n{'✓' if status == 'succeeded' else '✗'} Job terminé : {status}")
                if status == "succeeded":
                    job = client.fine_tuning.jobs.retrieve(job_id)
                    print(f"  Modèle fine-tuné : {job.fine_tuned_model}")
                break

            time.sleep(30)
    except KeyboardInterrupt:
        print(f"\n(monitoring arrêté — job_id: {job_id})")
        print("Relancez avec : python pipeline/finetune_openai.py --monitor <job_id>")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-only", action="store_true",
                        help="Préparer les fichiers sans uploader")
    parser.add_argument("--monitor", metavar="JOB_ID",
                        help="Surveiller un job existant")
    parser.add_argument("--dry-run", action="store_true",
                        help="Afficher les stats sans rien faire")
    parser.add_argument("--train-file", default=None,
                        help="Fichier train custom (ex: après modération)")
    parser.add_argument("--test-file", default=None,
                        help="Fichier test custom (ex: après modération)")
    parser.add_argument("--model", default=BASE_MODEL,
                        help=f"Modèle OpenAI de base (défaut: {BASE_MODEL})")
    parser.add_argument("--no-monitor", action="store_true",
                        help="Créer le job puis s'arrêter sans monitoring")
    args = parser.parse_args()

    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        print("✗ LLM_API_KEY non trouvée dans .env")
        return

    client = openai.OpenAI(api_key=api_key)

    # Mode monitoring uniquement
    if args.monitor:
        monitor(client, args.monitor)
        return

    using_custom_files = bool(args.train_file and args.test_file)
    train = []
    test = []

    if using_custom_files:
        print("=== 1. Fichiers custom ===")
        upload_train = Path(args.train_file)
        upload_test = Path(args.test_file)
        train_count = sum(1 for line in open(upload_train, encoding="utf-8") if line.strip())
        test_count = sum(1 for line in open(upload_test, encoding="utf-8") if line.strip())
        print(f"  Train: {upload_train} ({train_count} exemples)")
        print(f"  Test:  {upload_test} ({test_count} exemples)")
        if args.dry_run:
            print("\nDry-run: fichiers custom valides, pas d'upload")
            return
    else:
        # 1. Charger
        print("=== 1. Chargement des exemples ===")
        examples = load_all_examples()
        print(f"Total brut: {len(examples)}")

        # 2. Valider
        print("\n=== 2. Validation ===")
        examples = validate(examples)
        print(f"Total valide: {len(examples)}")

        if args.dry_run:
            print(f"\nSplit prévu: {int(len(examples)*0.9)} train / {int(len(examples)*0.1)} test")
            return

        # 3. Split + sauvegarder
        print("\n=== 3. Split train/test (90/10) ===")
        train, test = split(examples, TEST_RATIO, SEED)
        save_jsonl(train, TRAIN_PATH)
        save_jsonl(test, TEST_PATH)
        upload_train = TRAIN_PATH
        upload_test = TEST_PATH

    if args.prepare_only:
        print("\n✓ Fichiers prêts (--prepare-only, pas d'upload)")
        return

    # 4. Upload
    print("\n=== 4. Upload sur OpenAI ===")
    train_file_id = upload_file(client, upload_train, "fine-tune")
    val_file_id   = upload_file(client, upload_test,  "fine-tune")

    # 5. Lancer
    print("\n=== 5. Lancement fine-tuning ===")
    job_id = start_finetune(client, train_file_id, val_file_id, args.model)

    # Sauvegarder le job_id localement
    job_info = {
        "job_id": job_id,
        "model": args.model,
        "train_file": str(upload_train),
        "test_file": str(upload_test),
        "train_file_id": train_file_id,
        "val_file_id": val_file_id,
        "n_train": len(train) if train else train_count,
        "n_test": len(test) if test else test_count,
    }
    job_path = OUTPUT_DIR / "finetune_job.json"
    with open(job_path, "w") as f:
        json.dump(job_info, f, indent=2)
    print(f"\n  Info sauvegardée dans {job_path}")

    if args.no_monitor:
        print(f"\n✓ Job créé. Monitoring:")
        print(f"  python pipeline/finetune_openai.py --monitor {job_id}")
        return

    # 6. Monitoring
    print("\n=== 6. Monitoring ===")
    monitor(client, job_id)


if __name__ == "__main__":
    main()
