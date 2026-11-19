"""
Étape 2 : Génération des paires d'entraînement avec Claude.

Pour chaque passage, génère :
  - 1 continuation directe (Type 2)
  - 2 questions roleplay + réponses (Type 3)

Produit napoleon-corpus/datasets/sft/training/<source>_training.jsonl
"""

import json
import os
import random
import time
from pathlib import Path

import anthropic
import httpx
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv(Path(__file__).parent.parent / ".env")

SYSTEM_PROMPT = (
    "Tu es Napoléon Bonaparte, Empereur des Français. "
    "Tu réponds toujours à la première personne."
)

DEFAULT_PASSAGES_PATH = (
    Path(__file__).parent.parent
    / "napoleon-corpus"
    / "processed"
    / "passages"
    / "memoires_1.json"
)
SFT_DIR = Path(__file__).parent.parent / "napoleon-corpus" / "datasets" / "sft"
TRAINING_DIR = SFT_DIR / "training"
REVIEW_DIR = SFT_DIR / "review"
STATE_DIR = SFT_DIR / "state"

GENERATION_PROMPT = """\
Voici un passage tiré des œuvres de Napoléon Bonaparte.

PASSAGE (section: {section}):
{text}

Évalue ce passage :
- S'il n'est PAS du tout de Napoléon (texte éditorial, liste de dates, note de bas de page, \
préface, généalogie, biographie à la 3ème personne), retourne : {{"skip": true}}
- S'il contient des paroles authentiques de Napoléon, génère UNE question qui amène \
Napoléon à dire ce passage, et retourne le passage adapté pour être lu à voix haute \
par un avatar de Napoléon s'exprimant à la première personne : \
supprime les en-têtes non prononcés (dates, lieux, destinataires, formules d'adresse \
comme "Au quartier-général...", "Bonaparte, général en chef...", "Paris, le 3 fructidor..."), \
reformule OBLIGATOIREMENT pour que la réponse soit entièrement à la première personne \
de Napoléon, comme s'il racontait directement à son interlocuteur. \
écris les chiffres en toutes lettres (1° → premièrement, 2° → deuxièmement, \
29e → vingt-neuvième), développe les abréviations, \
supprime les caractères spéciaux (°, §, —, *), remplace les tirets par des virgules ou \
des points. Le texte final doit être entièrement à la première personne et \
pouvoir être lu naturellement à voix haute sans ambiguïté.

Réponds UNIQUEMENT avec ce JSON (sans markdown, sans commentaires) :
{{"skip": true}}
ou
{{
  "question": "[question directe adressée à Napoléon, en français]",
  "reponse": "[passage nettoyé des en-têtes, texte prononcé uniquement]"
}}
"""


def _build_response(original_text: str, adapted_opening: str) -> str:
    """Remplace la 1ère phrase par la version adaptée, conserve le reste verbatim."""
    if not adapted_opening:
        return original_text

    # Trouver la fin de la 1ère phrase (premier . ! ? suivi d'un espace ou fin)
    first_sentence_end = -1
    for i, ch in enumerate(original_text):
        if ch in ".!?" and (i + 1 >= len(original_text) or original_text[i + 1] in (" ", "\n")):
            first_sentence_end = i + 1
            break

    if first_sentence_end == -1:
        return adapted_opening

    original_first = original_text[:first_sentence_end].strip()
    rest = original_text[first_sentence_end:].strip()

    # Si l'ouverture adaptée est quasi-identique à l'originale, garder l'original
    orig_words = set(original_first.lower().split())
    adapted_words = set(adapted_opening.lower().split())
    similarity = len(orig_words & adapted_words) / max(len(orig_words), 1)
    if similarity > 0.85:
        return original_text

    if rest:
        return adapted_opening + " " + rest
    return adapted_opening


def make_training_example(role_user: str, role_assistant: str) -> dict:
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": role_user},
            {"role": "assistant", "content": role_assistant},
        ]
    }


def _call_model(client, model: str, prompt: str) -> str:
    """Appelle Anthropic ou OpenAI selon le client."""
    import openai
    if isinstance(client, openai.OpenAI):
        response = client.chat.completions.create(
            model=model,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content
    else:
        with client.messages.stream(
            model=model,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            return stream.get_final_message().content[0].text


def parse_generation_response(response_text: str) -> list[dict] | None:
    """Parse la réponse JSON du modèle.

    Retourne [] pour un skip, None pour une réponse invalide.
    """
    response_text = response_text.strip()
    if response_text.startswith("```"):
        response_text = response_text.split("\n", 1)[1]
        response_text = response_text.rsplit("```", 1)[0]

    data = json.loads(response_text)

    if data.get("skip"):
        return []

    question = data.get("question", "").strip()
    if not question:
        return None

    reponse = data.get("reponse", "").strip()
    if not reponse:
        return None

    return [make_training_example(question, reponse)]


def generate_for_passage(
    client,
    passage: dict,
    model: str,
    max_retries: int = 3,
) -> list[dict] | None:
    prompt = GENERATION_PROMPT.format(
        section=passage["section"],
        text=passage["text"],
    )

    for attempt in range(max_retries):
        try:
            response_text = _call_model(client, model, prompt)
            examples = parse_generation_response(response_text)
            if examples is None:
                return None
            if examples == []:
                return []

            return [
                {
                    **ex,
                    "_meta": {
                        "type": "roleplay",
                        "passage_id": passage["id"],
                        "theme": passage["theme"],
                        "section": passage["section"],
                    },
                }
                for ex in examples
            ]

        except json.JSONDecodeError as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"\n  ✗ Passage {passage['id']}: JSON invalide ({e})")
                return None
        except anthropic.RateLimitError:
            wait = 60 * (attempt + 1)
            print(f"\n  Rate limit – attente {wait}s...")
            time.sleep(wait)
        except (anthropic.APIConnectionError, httpx.RemoteProtocolError, httpx.ReadError, httpx.ReadTimeout):
            wait = 5 * (attempt + 1)
            print(f"\n  Connexion interrompue – retry dans {wait}s...")
            time.sleep(wait)
        except anthropic.APIStatusError as e:
            if e.status_code in (200, 529) or e.status_code >= 500:
                wait = 60 * (attempt + 1)
                print(f"\n  API indisponible ({e.status_code}) – attente {wait}s...")
                time.sleep(wait)
            else:
                print(f"\n  ✗ Passage {passage['id']}: API error ({e.status_code})")
                if attempt < max_retries - 1:
                    time.sleep(5)
                else:
                    return None
        except anthropic.APIError as e:
            print(f"\n  ✗ Passage {passage['id']}: API error ({e})")
            if attempt < max_retries - 1:
                time.sleep(5)
            else:
                return None

    return None


def generate_training_data(
    model: str = "claude-haiku-4-5",
    max_passages: int | None = None,
    offset: int = 0,
    resume: bool = True,
    passages_path: Path = None,
):
    openai_key = os.getenv("OPEN_AI_KEY") or os.getenv("LLM_API_KEY")
    is_openai = model.startswith(("gpt-", "o1", "o3", "o4"))
    if is_openai:
        import openai
        client = openai.OpenAI(api_key=openai_key)
    else:
        client = anthropic.Anthropic()

    passages_path = Path(passages_path) if passages_path else DEFAULT_PASSAGES_PATH
    stem = passages_path.stem  # ex: "memoires_1" ou "correspondance_13"
    training_path = TRAINING_DIR / f"{stem}_training.jsonl"
    review_path = REVIEW_DIR / f"{stem}_review.jsonl"
    state_path = STATE_DIR / f"{stem}_state.jsonl"

    with open(passages_path, "r", encoding="utf-8") as f:
        passages = json.load(f)

    if offset:
        passages = passages[offset:]
    if max_passages:
        passages = passages[:max_passages]

    # Reprendre là où on s'est arrêté. Le state garde aussi les passages skip.
    already_done: set[int] = set()
    generated_ids: set[int] = set()
    skipped_ids: set[int] = set()
    error_ids: set[int] = set()
    if resume and training_path.exists():
        with open(training_path, "r", encoding="utf-8") as f:
            for line in f:
                ex = json.loads(line)
                passage_id = ex["_meta"]["passage_id"]
                already_done.add(passage_id)
                generated_ids.add(passage_id)

    if resume and state_path.exists():
        with open(state_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                item = json.loads(line)
                passage_id = item.get("passage_id")
                status = item.get("status")
                if passage_id is not None and status in {"generated", "skipped"}:
                    already_done.add(passage_id)
                if status == "generated":
                    generated_ids.add(passage_id)
                elif status == "skipped":
                    skipped_ids.add(passage_id)
                elif status == "error":
                    error_ids.add(passage_id)

    if resume:
        print(
            "Reprise: "
            f"{len(already_done)} passages déjà traités "
            f"({len(generated_ids)} générés, {len(skipped_ids)} skippés, {len(error_ids)} erreurs à retenter)"
        )

    to_process = [p for p in passages if p["id"] not in already_done]
    print(f"Passages à traiter: {len(to_process)} / {len(passages)}")
    print(f"Modèle: {model}\n")

    training_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.parent.mkdir(parents=True, exist_ok=True)

    total_examples = 0
    skipped = 0
    errors = 0

    with (
        open(training_path, "a", encoding="utf-8") as out_f,
        open(state_path, "a", encoding="utf-8") as state_f,
    ):
        for passage in tqdm(to_process, desc="Génération"):
            result = generate_for_passage(client, passage, model)
            if result is None:
                errors += 1
                state_f.write(json.dumps({
                    "passage_id": passage["id"],
                    "status": "error",
                    "source": stem,
                    "model": model,
                }, ensure_ascii=False) + "\n")
                state_f.flush()
            elif result == []:
                skipped += 1
                state_f.write(json.dumps({
                    "passage_id": passage["id"],
                    "status": "skipped",
                    "source": stem,
                    "model": model,
                }, ensure_ascii=False) + "\n")
                state_f.flush()
            else:
                for ex in result:
                    out_f.write(json.dumps(ex, ensure_ascii=False) + "\n")
                out_f.flush()
                state_f.write(json.dumps({
                    "passage_id": passage["id"],
                    "status": "generated",
                    "source": stem,
                    "model": model,
                    "examples": len(result),
                }, ensure_ascii=False) + "\n")
                state_f.flush()
                total_examples += len(result)

    print(f"\n✓ {total_examples} exemples générés, {skipped} skippés, {errors} erreurs")
    print(f"→ Sauvegardé dans {training_path}")

    # Créer l'échantillon de vérification (10%)
    _create_review_sample(training_path, review_path)


def _create_review_sample(training_path: Path, review_path: Path):
    if not training_path.exists():
        return

    with open(training_path, "r", encoding="utf-8") as f:
        all_examples = [json.loads(line) for line in f if line.strip()]

    sample_size = max(1, len(all_examples) // 10)
    sample = random.sample(all_examples, min(sample_size, len(all_examples)))

    review_path.parent.mkdir(parents=True, exist_ok=True)
    with open(review_path, "w", encoding="utf-8") as f:
        for ex in sample:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    print(f"→ Échantillon de vérification ({len(sample)} exemples): {review_path}")


def rebuild_state_from_training() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    for training_path in sorted(TRAINING_DIR.glob("*_training.jsonl")):
        stem = training_path.name.removesuffix("_training.jsonl")
        passage_ids: set[int] = set()
        with open(training_path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                ex = json.loads(line)
                passage_id = ex.get("_meta", {}).get("passage_id")
                if passage_id is not None:
                    passage_ids.add(passage_id)

        state_path = STATE_DIR / f"{stem}_state.jsonl"
        existing: set[int] = set()
        if state_path.exists():
            with open(state_path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        item = json.loads(line)
                        if item.get("status") in {"generated", "skipped"}:
                            existing.add(item.get("passage_id"))

        new_ids = sorted(passage_ids - existing)
        if not new_ids:
            print(f"{stem}: state déjà à jour")
            continue

        with open(state_path, "a", encoding="utf-8") as f:
            for passage_id in new_ids:
                f.write(json.dumps({
                    "passage_id": passage_id,
                    "status": "generated",
                    "source": stem,
                    "model": "unknown",
                    "recovered_from_training": True,
                }, ensure_ascii=False) + "\n")
        print(f"{stem}: {len(new_ids)} passages generated ajoutés au state")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", "-i", default=None,
                        help="Chemin vers le fichier passages.json")
    parser.add_argument("--model", default="claude-haiku-4-5",
                        help="Modèle Claude (défaut: claude-haiku-4-5, qualité max: claude-opus-4-6)")
    parser.add_argument("--max-passages", type=int, default=None,
                        help="Limiter le nombre de passages (test)")
    parser.add_argument("--offset", type=int, default=0,
                        help="Sauter les N premiers passages")
    parser.add_argument("--no-resume", action="store_true",
                        help="Recommencer depuis le début")
    parser.add_argument("--rebuild-state", action="store_true",
                        help="Reconstruire napoleon-corpus/datasets/sft/state depuis les fichiers training")
    args = parser.parse_args()

    if args.rebuild_state:
        rebuild_state_from_training()
        raise SystemExit(0)

    generate_training_data(
        model=args.model,
        max_passages=args.max_passages,
        offset=args.offset,
        resume=not args.no_resume,
        passages_path=args.input,
    )
