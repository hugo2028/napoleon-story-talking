"""
Pipeline principale — Napoléon Fine-Tuning Dataset

Usage:
  python pipeline/main.py extract          # Étape 1 : extraire les passages
  python pipeline/main.py rag-index       # Construire la base Graph RAG SQLite
  python pipeline/main.py rag-eval        # Comparer avec/sans RAG sur un dataset de test
  python pipeline/main.py no-rag-model-eval # Comparer base vs fine-tuné sans RAG
  python pipeline/main.py rag-model-eval  # Comparer base vs fine-tuné avec RAG
  python pipeline/main.py generate         # Étape 2 : générer avec Claude
  python pipeline/main.py generate --model claude-opus-4-6  # qualité maximale
  python pipeline/main.py generate --max-passages 20        # test rapide
  python pipeline/main.py review           # Étape 3 : vérification humaine
  python pipeline/main.py stats            # Statistiques du dataset
  python pipeline/main.py all              # Étapes 1+2 enchaînées
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def cmd_extract(args):
    from extractor import main as extract_main
    extract_main(args.input)


def cmd_generate(args):
    from pathlib import Path
    from generator import generate_training_data

    passages_path = args.input
    # Si l'input est un HTML/TXT, lancer extract automatiquement
    if passages_path and Path(passages_path).suffix.lower() in (".html", ".htm", ".txt"):
        print("Fichier source détecté → extraction automatique des passages...\n")
        from extractor import main as extract_main
        passages_path = str(extract_main(passages_path))
        print()

    generate_training_data(
        model=args.model,
        max_passages=args.max_passages,
        offset=getattr(args, "offset", 0),
        resume=not args.no_resume,
        passages_path=passages_path,
    )


def cmd_review(args):
    from review import review_sample
    review_sample()


def cmd_stats(args):
    from review import show_stats
    show_stats()


def cmd_rag_index(args):
    from rag_index import build_index
    build_index(
        Path(args.source),
        Path(args.output),
        embedding_provider=args.embedding_provider,
        embedding_model=args.embedding_model,
    )


def cmd_rag_eval(args):
    from rag_eval import main as rag_eval_main
    argv = ["rag_eval.py", "--mode", args.mode, "--dataset", args.dataset, "--output-dir", args.output_dir]
    if args.server_url:
        argv.extend(["--server-url", args.server_url])
    if args.model:
        argv.extend(["--model", args.model])
    if args.limit is not None:
        argv.extend(["--limit", str(args.limit)])
    argv.extend(["--rag-limit", str(args.rag_limit)])
    old_argv = sys.argv
    try:
        sys.argv = argv
        rag_eval_main()
    finally:
        sys.argv = old_argv


def cmd_no_rag_model_eval(args):
    from no_rag_model_eval import main as no_rag_model_eval_main
    argv = [
        "no_rag_model_eval.py",
        "--dataset",
        args.dataset,
        "--output-dir",
        args.output_dir,
        "--base-model",
        args.base_model,
        "--fine-tuned-model",
        args.fine_tuned_model,
    ]
    if args.limit is not None:
        argv.extend(["--limit", str(args.limit)])
    old_argv = sys.argv
    try:
        sys.argv = argv
        no_rag_model_eval_main()
    finally:
        sys.argv = old_argv


def cmd_rag_model_eval(args):
    from rag_model_eval import main as rag_model_eval_main
    argv = [
        "rag_model_eval.py",
        "--dataset",
        args.dataset,
        "--output-dir",
        args.output_dir,
        "--base-model",
        args.base_model,
        "--fine-tuned-model",
        args.fine_tuned_model,
        "--rag-limit",
        str(args.rag_limit),
    ]
    if args.limit is not None:
        argv.extend(["--limit", str(args.limit)])
    old_argv = sys.argv
    try:
        sys.argv = argv
        rag_model_eval_main()
    finally:
        sys.argv = old_argv


def cmd_all(args):
    from extractor import main as extract_main
    passages_path = extract_main(args.input)
    print("\n" + "═" * 60)
    # Passer le fichier passages produit par extract à generate
    args.input = str(passages_path)
    cmd_generate(args)


def main():
    parser = argparse.ArgumentParser(
        description="Pipeline de génération de données fine-tuning Napoléon Bonaparte",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command")

    # extract
    ext_p = sub.add_parser("extract", help="Étape 1 : extraire les passages du HTML/TXT")
    ext_p.add_argument("--input", "-i", default=None,
                       help="Chemin vers le fichier source HTML ou TXT")

    # generate
    gen_p = sub.add_parser("generate", help="Étape 2 : générer avec Claude API")
    gen_p.add_argument(
        "--input", "-i", default=None,
        help="Chemin vers le fichier passages.json (produit par extract)",
    )
    gen_p.add_argument(
        "--model",
        default="claude-haiku-4-5",
        help=(
            "Modèle Claude. "
            "Défaut: claude-haiku-4-5 (rapide, économique). "
            "Qualité max: claude-opus-4-6."
        ),
    )
    gen_p.add_argument(
        "--max-passages",
        type=int,
        default=None,
        metavar="N",
        help="Traiter seulement les N premiers passages (test)",
    )
    gen_p.add_argument(
        "--offset",
        type=int,
        default=0,
        metavar="N",
        help="Sauter les N premiers passages",
    )
    gen_p.add_argument(
        "--no-resume",
        action="store_true",
        help="Recommencer depuis le début (ignore les fichiers existants)",
    )

    # review
    sub.add_parser("review", help="Étape 3 : vérification humaine interactive (10%)")

    # stats
    sub.add_parser("stats", help="Afficher les statistiques du dataset")

    # rag-index
    rag_p = sub.add_parser("rag-index", help="Construire la base SQLite Graph RAG")
    rag_p.add_argument("--source", default=str(Path(__file__).parent.parent / "napoleon-corpus" / "sources"))
    rag_p.add_argument("--output", default=str(Path(__file__).parent.parent / "data" / "rag" / "napoleon_rag.sqlite"))
    rag_p.add_argument(
        "--embedding-provider",
        choices=["openai", "hash"],
        default="openai",
        help="Provider d'embeddings. openai recommandé, hash utile pour tester sans API.",
    )
    rag_p.add_argument(
        "--embedding-model",
        default="text-embedding-3-small",
        help="Modèle d'embedding si --embedding-provider openai.",
    )

    # rag-eval
    eval_p = sub.add_parser("rag-eval", help="Comparer les réponses avec et sans RAG")
    eval_p.add_argument("--mode", choices=["direct", "server", "retrieval-only"], default="retrieval-only")
    eval_p.add_argument("--dataset", default=str(Path(__file__).parent.parent / "data" / "eval" / "rag_eval_questions.jsonl"))
    eval_p.add_argument("--output-dir", default=str(Path(__file__).parent.parent / "data" / "eval" / "runs"))
    eval_p.add_argument("--server-url", default="http://127.0.0.1:3002")
    eval_p.add_argument("--model", default="gpt-4o-mini")
    eval_p.add_argument("--limit", type=int, default=None)
    eval_p.add_argument("--rag-limit", type=int, default=6)

    # no-rag-model-eval
    no_rag_eval_p = sub.add_parser("no-rag-model-eval", help="Comparer un modèle base et un modèle fine-tuné sans RAG")
    no_rag_eval_p.add_argument("--dataset", default=str(Path(__file__).parent.parent / "data" / "eval" / "rag_eval_questions.jsonl"))
    no_rag_eval_p.add_argument("--output-dir", default=str(Path(__file__).parent.parent / "data" / "eval" / "runs"))
    no_rag_eval_p.add_argument("--base-model", default="gpt-4.1-mini")
    no_rag_eval_p.add_argument(
        "--fine-tuned-model",
        default="ft:gpt-4.1-mini-2025-04-14:organizations::DkstSMs5",
    )
    no_rag_eval_p.add_argument("--limit", type=int, default=None)

    # rag-model-eval
    rag_model_eval_p = sub.add_parser("rag-model-eval", help="Comparer un modèle base et un modèle fine-tuné avec RAG")
    rag_model_eval_p.add_argument("--dataset", default=str(Path(__file__).parent.parent / "data" / "eval" / "rag_eval_questions.jsonl"))
    rag_model_eval_p.add_argument("--output-dir", default=str(Path(__file__).parent.parent / "data" / "eval" / "runs"))
    rag_model_eval_p.add_argument("--base-model", default="gpt-4.1-mini")
    rag_model_eval_p.add_argument(
        "--fine-tuned-model",
        default="ft:gpt-4.1-mini-2025-04-14:organizations::DkstSMs5",
    )
    rag_model_eval_p.add_argument("--limit", type=int, default=None)
    rag_model_eval_p.add_argument("--rag-limit", type=int, default=6)

    # all
    all_p = sub.add_parser("all", help="Enchaîner extract + generate")
    all_p.add_argument("--input", "-i", default=None,
                       help="Chemin vers le fichier source HTML ou TXT")
    all_p.add_argument("--model", default="claude-haiku-4-5")
    all_p.add_argument("--max-passages", type=int, default=None)
    all_p.add_argument("--no-resume", action="store_true")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    commands = {
        "extract": cmd_extract,
        "generate": cmd_generate,
        "review": cmd_review,
        "stats": cmd_stats,
        "rag-index": cmd_rag_index,
        "rag-eval": cmd_rag_eval,
        "no-rag-model-eval": cmd_no_rag_model_eval,
        "rag-model-eval": cmd_rag_model_eval,
        "all": cmd_all,
    }

    print(f"\n{'═'*60}")
    print(f"  Pipeline Napoléon Fine-Tuning — {args.command.upper()}")
    print(f"{'═'*60}\n")

    commands[args.command](args)


if __name__ == "__main__":
    main()
