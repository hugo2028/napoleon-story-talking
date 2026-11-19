"""
Fine-tuning Mistral AI — Napoleon Bonaparte

Etapes :
  1. Consolider tous les JSONL de napoleon-corpus/datasets/sft/training/
  2. Nettoyer et valider le format chat
  3. Shuffle + split 90/10 train / test
  4. Uploader sur Mistral AI
  5. Creer un job de fine-tuning
  6. Surveiller le statut
"""

import json
import os
import random
import time
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

try:
    from mistralai import Mistral
except ImportError:
    try:
        from mistralai.client import Mistral
    except ImportError:  # pragma: no cover
        Mistral = None

load_dotenv(Path(__file__).parent.parent / ".env")

TRAINING_DIR = Path(__file__).parent.parent / "napoleon-corpus" / "datasets" / "sft" / "training"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "mistral"
TRAIN_PATH = OUTPUT_DIR / "napoleon_train.jsonl"
TEST_PATH = OUTPUT_DIR / "napoleon_test.jsonl"

BASE_MODEL = "open-mistral-nemo"
TEST_RATIO = 0.10
SEED = 42

TERMINAL_STATUSES = {
    "SUCCESS",
    "FAILED",
    "CANCELLED",
    "CANCELED",
    "TIMEOUT_EXCEEDED",
    "FAILED_VALIDATION",
}


def load_all_examples() -> list[dict]:
    examples = []
    for path in sorted(TRAINING_DIR.glob("*.jsonl")):
        count = 0
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                ex = json.loads(line)
                ex.pop("_meta", None)
                examples.append(ex)
                count += 1
        print(f"  {path.name}: {count} exemples")
    return examples


def validate(examples: list[dict]) -> list[dict]:
    valid = []
    skipped = 0
    for ex in examples:
        msgs = ex.get("messages", [])
        if len(msgs) < 2:
            skipped += 1
            continue
        roles = [m.get("role") for m in msgs]
        if roles[-1] != "assistant" or "user" not in roles:
            skipped += 1
            continue
        if not all(str(m.get("content", "")).strip() for m in msgs):
            skipped += 1
            continue
        valid.append({"messages": msgs})
    if skipped:
        print(f"  Attention: {skipped} exemples invalides ignores")
    return valid


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
    print(f"  -> {path.name}: {len(examples)} exemples")


def get_attr(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def to_jsonable(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if hasattr(obj, "dict"):
        return obj.dict()
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, list):
        return [to_jsonable(item) for item in obj]
    if isinstance(obj, dict):
        return {key: to_jsonable(value) for key, value in obj.items()}
    return str(obj)


def require_client() -> Any:
    if Mistral is None:
        raise RuntimeError(
            "Le package 'mistralai' n'est pas installe. Lancez: pip install -r requirements.txt"
        )

    api_key = os.getenv("MISTRAL_AI")
    if not api_key:
        raise RuntimeError("MISTRAL_AI non trouvee dans .env")

    return Mistral(api_key=api_key)


def upload_file(client: Any, path: Path) -> str:
    print(f"  Upload {path.name}...")
    with open(path, "rb") as f:
        uploaded = client.files.upload(
            file={
                "file_name": path.name,
                "content": f,
            },
            purpose="fine-tune",
        )
    file_id = get_attr(uploaded, "id")
    if not file_id:
        raise RuntimeError(f"Upload sans file_id: {uploaded}")
    print(f"  OK file_id: {file_id}")
    return file_id


def create_finetune_job(
    client: Any,
    train_file_id: str,
    val_file_id: str | None,
    model: str,
    training_steps: int | None,
    learning_rate: float | None,
    suffix: str | None,
    job_type: str | None,
    auto_start: bool,
    dry_run: bool,
) -> Any:
    hyperparameters: dict[str, Any] = {"learning_rate": learning_rate or 0.0001}
    if training_steps is not None:
        hyperparameters["training_steps"] = training_steps

    payload: dict[str, Any] = {
        "model": model,
        "training_files": [{"file_id": train_file_id, "weight": 1}],
        "auto_start": auto_start,
        "hyperparameters": hyperparameters,
    }
    if val_file_id:
        payload["validation_files"] = [val_file_id]
    if hyperparameters:
        payload["hyperparameters"] = hyperparameters
    if suffix:
        payload["suffix"] = suffix
    if job_type:
        payload["job_type"] = job_type

    print(f"\nCreation job Mistral sur {model}...")
    if dry_run:
        job = create_finetune_dry_run(payload)
    elif job_type and job_type not in {"completion", "classifier"}:
        job = create_finetune_job_rest(payload)
    else:
        job = client.fine_tuning.jobs.create(**payload)
    job_id = get_attr(job, "id")
    status = get_attr(job, "status", "inconnu")
    if dry_run:
        print("  Dry-run Mistral termine: aucun job d'entrainement lance")
    else:
        print(f"  OK job_id: {job_id}")
        print(f"  Statut initial: {status}")
    return job


def create_finetune_job_rest(payload: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("MISTRAL_AI")
    if not api_key:
        raise RuntimeError("MISTRAL_AI non trouvee dans .env")

    response = httpx.post(
        "https://api.mistral.ai/v1/fine_tuning/jobs",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json=payload,
        timeout=60,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Mistral refuse la creation ({response.status_code}): {response.text}")
    return response.json()


def create_finetune_dry_run(payload: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("MISTRAL_AI")
    if not api_key:
        raise RuntimeError("MISTRAL_AI non trouvee dans .env")

    url = "https://api.mistral.ai/v1/fine_tuning/jobs"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    response = httpx.post(url, params={"dry_run": "true"}, headers=headers, json=payload, timeout=60)
    if response.status_code >= 400:
        fallback_payload = {**payload, "dry_run": True}
        response = httpx.post(url, headers=headers, json=fallback_payload, timeout=60)
    if response.status_code >= 400:
        raise RuntimeError(f"Mistral dry-run refuse ({response.status_code}): {response.text}")
    response.raise_for_status()
    return response.json()


def list_finetunable_models():
    api_key = os.getenv("MISTRAL_AI")
    if not api_key:
        raise RuntimeError("MISTRAL_AI non trouvee dans .env")

    response = httpx.get(
        "https://api.mistral.ai/v1/models",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    models = response.json().get("data", [])
    print("Modeles avec capabilities.fine_tuning=true:")
    for model in models:
        capabilities = model.get("capabilities") or {}
        if capabilities.get("fine_tuning"):
            print(f"  - {model.get('id')} ({model.get('name')})")


def start_job(client: Any, job_id: str):
    job = client.fine_tuning.jobs.start(job_id=job_id)
    print(f"Job demarre: {get_attr(job, 'id', job_id)} ({get_attr(job, 'status', 'inconnu')})")


def monitor(client: Any, job_id: str):
    print("\nSurveillance du job (Ctrl+C pour arreter le monitoring)...")
    try:
        while True:
            job = client.fine_tuning.jobs.get(job_id=job_id)
            status = str(get_attr(job, "status", "UNKNOWN")).upper()
            fine_tuned_model = get_attr(job, "fine_tuned_model")
            print(f"  Statut: {status}")

            if fine_tuned_model:
                print(f"  Modele fine-tune: {fine_tuned_model}")

            if status == "VALIDATED":
                print("  Job valide. Lancez-le avec: python pipeline/finetune_mistral.py --start " + job_id)
                break

            if status in TERMINAL_STATUSES:
                print(f"\nJob termine: {status}")
                break

            time.sleep(30)
    except KeyboardInterrupt:
        print(f"\nMonitoring arrete. Relancez avec: python pipeline/finetune_mistral.py --monitor {job_id}")


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-only", action="store_true", help="Preparer les fichiers sans uploader")
    parser.add_argument("--dry-run", action="store_true", help="Valider cote Mistral sans lancer l'entrainement")
    parser.add_argument("--monitor", metavar="JOB_ID", help="Surveiller un job existant")
    parser.add_argument("--start", metavar="JOB_ID", help="Demarrer un job Mistral deja valide")
    parser.add_argument("--list-models", action="store_true", help="Lister les modeles Mistral fine-tunables")
    parser.add_argument("--train-file", default=None, help="Fichier train custom")
    parser.add_argument("--test-file", default=None, help="Fichier validation custom")
    parser.add_argument("--model", default=BASE_MODEL, help=f"Modele Mistral de base (defaut: {BASE_MODEL})")
    parser.add_argument("--suffix", default="napoleon", help="Suffixe du modele fine-tune")
    parser.add_argument("--training-steps", type=int, default=None, help="Nombre de steps d'entrainement")
    parser.add_argument("--learning-rate", type=float, default=None, help="Learning rate")
    parser.add_argument(
        "--job-type",
        default=None,
        help="Type de job Mistral. Par defaut, l'API choisit. Exemples: completion, classifier, chat",
    )
    parser.add_argument("--auto-start", action="store_true", help="Demarrer automatiquement apres validation")
    args = parser.parse_args()

    if args.list_models:
        list_finetunable_models()
        return

    if args.monitor or args.start:
        client = require_client()
        if args.start:
            start_job(client, args.start)
            return
        monitor(client, args.monitor)
        return

    print("=== 1. Chargement des exemples ===")
    examples = load_all_examples()
    print(f"Total brut: {len(examples)}")

    print("\n=== 2. Validation ===")
    examples = validate(examples)
    print(f"Total valide: {len(examples)}")

    print("\n=== 3. Split train/test (90/10) ===")
    train, test = split(examples, TEST_RATIO, SEED)
    save_jsonl(train, TRAIN_PATH)
    save_jsonl(test, TEST_PATH)

    if args.prepare_only:
        print("\nFichiers prets (--prepare-only, pas d'upload)")
        return

    client = require_client()

    print("\n=== 4. Upload sur Mistral AI ===")
    upload_train = Path(args.train_file) if args.train_file else TRAIN_PATH
    upload_test = Path(args.test_file) if args.test_file else TEST_PATH
    train_file_id = upload_file(client, upload_train)
    val_file_id = upload_file(client, upload_test) if upload_test.exists() else None

    print("\n=== 5. Creation fine-tuning ===")
    try:
        job = create_finetune_job(
            client=client,
            train_file_id=train_file_id,
            val_file_id=val_file_id,
            model=args.model,
            training_steps=args.training_steps,
            learning_rate=args.learning_rate,
            suffix=args.suffix,
            job_type=args.job_type,
            auto_start=args.auto_start,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"\nErreur Mistral: {exc}")
        print("Pour voir les modeles exposes par votre cle:")
        print("  python pipeline/finetune_mistral.py --list-models")
        return

    job_id = get_attr(job, "id")
    job_info = {
        "job_id": job_id,
        "provider": "mistral",
        "model": args.model,
        "train_file": str(upload_train),
        "test_file": str(upload_test) if upload_test else None,
        "train_file_id": train_file_id,
        "val_file_id": val_file_id,
        "n_train": len(train),
        "n_test": len(test),
        "dry_run": args.dry_run,
        "job": to_jsonable(job),
    }
    job_path = OUTPUT_DIR / "finetune_job.json"
    with open(job_path, "w", encoding="utf-8") as f:
        json.dump(job_info, f, ensure_ascii=False, indent=2)
    print(f"\nInfo sauvegardee dans {job_path}")

    if args.dry_run:
        return

    if job_id and args.auto_start:
        print("\n=== 6. Monitoring ===")
        monitor(client, job_id)
    elif job_id:
        print("\nJob cree. S'il passe en VALIDATED, demarrez-le avec:")
        print(f"  python pipeline/finetune_mistral.py --start {job_id}")
        print(f"  python pipeline/finetune_mistral.py --monitor {job_id}")


if __name__ == "__main__":
    main()
