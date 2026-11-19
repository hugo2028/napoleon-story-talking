"""
Nettoyage LLM conservateur du corpus Napoleon.

Cette etape prend des chunks existants, demande au modele de reconstruire ou
rejeter chaque passage, puis ecrit des sorties reutilisables pour CPT et SFT.

Usage:
  python3 pipeline/llm_clean_corpus.py --dry-run --limit 3
  python3 pipeline/llm_clean_corpus.py --source-type bulletins --limit 100
  python3 pipeline/llm_clean_corpus.py --glob "napoleon-corpus/cleaned/bulletins/*.jsonl"
  python3 pipeline/llm_clean_corpus.py --source-type memoires-proches --prompt napoleon-corpus/metadata/llm_cleaning_books_prompt.md
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from tqdm import tqdm


ROOT = Path(__file__).parent.parent
CORPUS_DIR = ROOT / "napoleon-corpus"
PROMPT_PATH = CORPUS_DIR / "metadata" / "llm_cleaning_prompt.md"
DEFAULT_GLOB = str(CORPUS_DIR / "cleaned" / "*" / "*.jsonl")
OUTPUT_DIR = CORPUS_DIR / "datasets" / "llm_clean"
SYSTEM_PROMPT = "Tu reponds uniquement avec un objet JSON valide."


def load_jsonl(path: Path):
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if line.strip():
                yield line_no, json.loads(line)


def write_jsonl_line(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_done(path: Path) -> set[str]:
    done: set[str] = set()
    if not path.exists():
        return done
    for _, row in load_jsonl(path):
        source_id = row.get("id") or row.get("source_id")
        if source_id:
            done.add(source_id)
    return done


def write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


COLLECTION_CONTEXTS = {
    "bulletins": (
        "Les bulletins de la Grande armée : précédés des rapports sur l'armée française, "
        "depuis Toulon jusqu'à Waterloo, extraits textuellement du Moniteur et des Annales "
        "de l'empire : histoire militaire du général Bonaparte et de l'empereur Napoléon, "
        "avec des notes historiques et biographiques sur chaque officier."
    ),
    "lettres-amour-imperiales": (
        "Note du transcripteur: ce livre présente des lettres de Napoléon Bonaparte à sa "
        "première femme, Joséphine de Beauharnais, et à la Comtesse Marie de Walewska. "
        "Napoléon épouse Joséphine Tascher de la Pagerie en 1796 et divorce en 1809; "
        "il épouse Marie-Louise d'Autriche en 1810. Les lettres à Marie de Walewska "
        "s'inscrivent notamment dans le contexte des pourparlers et suites du Traité de "
        "Tilsitt signé en 1807 entre Napoléon Ier et le tsar Alexandre Ier de Russie. "
        "Repères: mars 1796, Bonaparte général en chef de l'armée d'Italie; victoires "
        "de Castiglione, Arcole, Rivoli; Traité de Campoformio en octobre 1797; "
        "Campagne d'Égypte en 1798-1799; deuxième campagne d'Italie et Marengo en 1800; "
        "18 brumaire an VIII, 9 novembre 1799; sacre le 2 décembre 1804; Austerlitz "
        "en 1805; Iéna en 1806; Eylau et Friedland en 1807; Wagram et Paix de Vienne "
        "en 1809; Campagne de Russie en 1812; Leipzig en 1813; abdication de "
        "Fontainebleau en avril 1814; Cent-Jours en 1815; Waterloo en juin 1815; "
        "Sainte-Hélène jusqu'à sa mort en 1821."
    )
}


def date_policy_for(source_type: str | None) -> str:
    if source_type in {"bulletins", "correspondance", "lettres-amour-imperiales"}:
        return "letter_date_required"
    if source_type in {
        "jeunesse",
        "campagnes",
        "memoires-proches",
        "proclamations",
        "biographies",
        "sainte-helene",
        "source",
        "misc",
    }:
        return "book_date_not_required"
    return "source_date_optional"


def build_user_prompt(base_prompt: str, row: dict[str, Any]) -> str:
    payload = {
        "id": row.get("id"),
        "title": row.get("title"),
        "existing_date": row.get("date"),
        "date_text": row.get("date_text"),
        "place": row.get("place"),
        "recipient": row.get("recipient"),
        "recipient_place": row.get("recipient_place"),
        "letter_id": row.get("letter_id"),
        "part_index": row.get("part_index"),
        "part_count": row.get("part_count"),
        "period": row.get("period"),
        "theme": row.get("theme"),
        "source_type": row.get("source_type"),
        "collection_context": COLLECTION_CONTEXTS.get(row.get("source_type")),
        "date_policy": date_policy_for(row.get("source_type")),
        "word_count": row.get("word_count"),
        "text": row.get("text"),
    }
    return (
        base_prompt.strip()
        + "\n\n## Passage A Traiter\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def parse_json_response(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(text)


def call_openai(client: Any, model: str, prompt: str) -> dict[str, Any]:
    kwargs = dict(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )
    if model not in ("gpt-5-nano",):
        kwargs["temperature"] = 0
    response = client.chat.completions.create(**kwargs)
    return parse_json_response(response.choices[0].message.content or "")


def normalize_date_text(date_text: Any, date_evidence: Any) -> Any:
    """Prefer the complete place-date quote when the model shortened date_text."""
    if not isinstance(date_evidence, str) or not date_evidence.strip():
        return date_text
    if date_evidence.strip().lower().startswith("existing_date"):
        return date_text
    if not isinstance(date_text, str) or not date_text.strip():
        return date_evidence.strip()

    date_text_clean = date_text.strip()
    evidence_clean = date_evidence.strip()
    if date_text_clean in evidence_clean and len(evidence_clean) > len(date_text_clean):
        return evidence_clean
    return date_text_clean


def normalize_result(source: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    decision = result.get("decision")
    confidence = float(result.get("confidence") or 0)
    if decision != "keep" or confidence < 0.65:
        return {
            "id": source.get("id"),
            "decision": "reject",
            "reject_reason": result.get("reject_reason") or "low_confidence",
            "confidence": confidence,
            "source_type": source.get("source_type"),
            "title": source.get("title"),
            "text": source.get("text"),
            "model_result": result,
        }

    cleaned_text = str(result.get("cleaned_text") or "").strip()
    spoken_text = str(result.get("spoken_text") or "").strip()
    if not cleaned_text:
        return {
            "id": source.get("id"),
            "decision": "reject",
            "reject_reason": "empty_cleaned_text",
            "confidence": confidence,
            "source_type": source.get("source_type"),
            "title": source.get("title"),
            "text": source.get("text"),
            "model_result": result,
        }

    quality_flags = result.get("quality_flags") or []
    date_iso = result.get("date_iso")
    date_evidence = result.get("date_evidence")
    date_text = normalize_date_text(result.get("date_text"), date_evidence)
    if not date_iso and source.get("date"):
        date_iso = source.get("date")
        date_text = date_text or source.get("date")
        quality_flags.append("existing_date_restored")

    return {
        "id": source.get("id"),
        "decision": "keep",
        "cleaned_text": cleaned_text,
        "spoken_text": spoken_text or cleaned_text,
        "date_iso": date_iso,
        "date_text": date_text,
        "date_evidence": date_evidence or ("existing_date restaurée" if source.get("date") else None),
        "source_kind": result.get("source_kind"),
        "confidence": confidence,
        "quality_flags": quality_flags,
        "source_type": source.get("source_type"),
        "title": source.get("title"),
        "theme": source.get("theme"),
        "original_text": source.get("text"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--glob", default=DEFAULT_GLOB, help="Fichiers JSONL cleaned a traiter")
    parser.add_argument("--source-type", default=None, help="Filtrer par source_type")
    parser.add_argument("--id", default=None, help="Traiter un seul id de cleaned, utile pour debugger")
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--prompt", default=str(PROMPT_PATH), help="Prompt de nettoyage LLM a utiliser")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR), help="Dossier de sortie des decisions LLM")
    parser.add_argument("--log-every", type=int, default=0, help="Afficher aussi un log texte tous les N passages")
    parser.add_argument("--no-progress", action="store_true", help="Desactiver la barre de progression tqdm")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    base_prompt = Path(args.prompt).read_text(encoding="utf-8")

    output_dir = Path(args.output_dir)
    output_clean = output_dir / "cleaned_cpt.jsonl"
    output_reject = output_dir / "rejected.jsonl"
    output_state = output_dir / "state.json"
    done = set() if args.no_resume else load_done(output_clean) | load_done(output_reject)

    paths = sorted(Path().glob(args.glob) if not args.glob.startswith("/") else Path("/").glob(args.glob[1:]))
    count = 0
    skipped_done = 0
    skipped_filter = 0
    tasks: list[tuple[Path, dict[str, Any]]] = []

    for path in paths:
        for _, row in load_jsonl(path):
            if args.source_type and row.get("source_type") != args.source_type:
                skipped_filter += 1
                continue
            if args.id and row.get("id") != args.id:
                skipped_filter += 1
                continue
            if row.get("id") in done:
                skipped_done += 1
                continue
            tasks.append((path, row))

    if args.limit:
        tasks = tasks[:args.limit]

    print("=== Nettoyage LLM corpus ===")
    print(f"Prompt: {Path(args.prompt)}")
    print(f"Modele: {args.model}")
    print(f"Source type: {args.source_type or 'tous'}")
    print(f"Fichiers trouves: {len(paths)}")
    print(f"Output: {output_dir}")
    print(f"Resume: {'non' if args.no_resume else 'oui'} ({len(done)} deja traites)")
    print(f"Passages a traiter: {len(tasks)}")
    print(f"Ignores deja traites: {skipped_done}")
    if args.limit:
        print(f"Limite: {args.limit}")
    if not args.no_resume:
        print("Reprise: relancez la meme commande sans --no-resume; les IDs deja ecrits seront ignores.")

    write_state(output_state, {
        "status": "running",
        "started_at": time.time(),
        "prompt": str(Path(args.prompt)),
        "model": args.model,
        "source_type": args.source_type,
        "output_dir": str(output_dir),
        "total_pending_at_start": len(tasks),
        "already_done_at_start": len(done),
        "processed_this_run": 0,
        "last_id": None,
    })

    client = None
    if not args.dry_run:
        from openai import OpenAI

        api_key = os.getenv("OPEN_AI_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
        if not api_key:
            raise RuntimeError("OPEN_AI_KEY, OPENAI_API_KEY ou LLM_API_KEY introuvable dans .env")
        client = OpenAI(api_key=api_key)

    iterator = tasks
    progress = None
    if not args.no_progress and not args.dry_run:
        progress = tqdm(total=len(tasks), desc="Nettoyage LLM", unit="passage")
        iterator = tasks

    try:
        for path, row in iterator:
            prompt = build_user_prompt(base_prompt, row)
            if args.dry_run:
                print(prompt)
                return

            assert client is not None
            result = call_openai(client, args.model, prompt)
            normalized = normalize_result(row, result)

            if normalized["decision"] == "keep":
                write_jsonl_line(output_clean, normalized)
            else:
                write_jsonl_line(output_reject, normalized)

            count += 1
            write_state(output_state, {
                "status": "running",
                "updated_at": time.time(),
                "prompt": str(Path(args.prompt)),
                "model": args.model,
                "source_type": args.source_type,
                "output_dir": str(output_dir),
                "total_pending_at_start": len(tasks),
                "already_done_at_start": len(done),
                "processed_this_run": count,
                "last_id": row.get("id"),
                "last_decision": normalized["decision"],
            })
            if progress is not None:
                progress.set_postfix({
                    "id": str(row.get("id"))[:24],
                    "decision": normalized["decision"],
                })
                progress.update(1)
            if args.log_every and count % args.log_every == 0:
                print(f"{count} passages traites | keep/reject ecrits dans {output_dir}", flush=True)
            if args.sleep:
                time.sleep(args.sleep)
    except KeyboardInterrupt:
        if progress is not None:
            progress.close()
        write_state(output_state, {
            "status": "interrupted",
            "updated_at": time.time(),
            "prompt": str(Path(args.prompt)),
            "model": args.model,
            "source_type": args.source_type,
            "output_dir": str(output_dir),
            "processed_this_run": count,
            "resume_hint": "Relancez la meme commande sans --no-resume.",
        })
        print(f"\nInterrompu. Etat sauvegarde: {output_state}")
        print("Pour reprendre, relancez la meme commande sans --no-resume.")
        return

    if progress is not None:
        progress.close()
    write_state(output_state, {
        "status": "complete",
        "completed_at": time.time(),
        "prompt": str(Path(args.prompt)),
        "model": args.model,
        "source_type": args.source_type,
        "output_dir": str(output_dir),
        "processed_this_run": count,
        "skipped_done": skipped_done,
        "skipped_filter": skipped_filter,
    })
    print(f"\nTermine: {count} passages traites. Skipped done={skipped_done}, skipped filter={skipped_filter}")


if __name__ == "__main__":
    main()
