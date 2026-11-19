"""
Embedding et insertion des lettres manquantes dans napoleon_clean.sqlite.

Lit les entrées nettoyées dans data/missing/cleaned_cpt.jsonl,
assigne des chunk_keys définitifs (positions 1..N pour chaque tome),
embarque via OpenAI text-embedding-3-small et insère dans la base.

Usage:
  python3 pipeline/embed_insert_missing.py
  python3 pipeline/embed_insert_missing.py --dry-run
  python3 pipeline/embed_insert_missing.py --input data/missing/cleaned_cpt.jsonl

Prérequis (dans l'ordre):
  1. extract_missing_letters.py  → data/missing/raw_tome_*.jsonl
  2. batch_clean.py prepare/submit/status/process → data/missing/cleaned_cpt.jsonl
  3. renumber_chunks.py          → chunk_keys décalés dans napoleon_clean.sqlite
  4. CE SCRIPT                   → nouvelles lettres insérées

Idempotent : vérifie si le chunk_key existe avant d'insérer (reprise sur interruption).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import time
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

ROOT     = Path(__file__).parent.parent
DB_PATH  = ROOT / "data" / "rag" / "napoleon_clean.sqlite"
INPUT    = ROOT / "data" / "missing" / "cleaned_cpt.jsonl"

EMBED_MODEL  = "text-embedding-3-small"
BATCH_SIZE   = 96

PERIODS = [
    (1769, 1792, 1, "Jeunesse"),
    (1793, 1795, 2, "Révolution & Toulon"),
    (1796, 1797, 3, "Première campagne d'Italie"),
    (1798, 1799, 4, "Campagne d'Égypte"),
    (1800, 1804, 5, "Consulat"),
    (1805, 1814, 6, "Empire"),
    (1815, 1821, 7, "Sainte-Hélène"),
]

# id format: correspondance_{tome:02d}_miss_{letter_id:05d}_{part_index:02d}
TEMP_ID_RE = re.compile(r'^correspondance_(\d+)_miss_(\d+)_(\d+)$')


def get_period(year: int) -> tuple[str, int]:
    for y1, y2, order, label in PERIODS:
        if y1 <= year <= y2:
            return label, order
    return "Inconnu", 99


def load_cleaned(path: Path) -> list[dict]:
    """Charge les entrées 'keep' de cleaned_cpt.jsonl."""
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if row.get("decision") != "keep":
            continue
        entry_id = row.get("id", "")
        m = TEMP_ID_RE.match(entry_id)
        if not m:
            print(f"  [WARN] ID non parseable : {entry_id!r} — ignoré")
            continue
        tome      = int(m.group(1))
        letter_id = int(m.group(2))
        part_idx  = int(m.group(3))
        text = (row.get("cleaned_text") or "").strip()
        if len(text.split()) < 10:
            continue
        entries.append({
            "id":           entry_id,
            "tome":         tome,
            "letter_id":    letter_id,
            "part_index":   part_idx,
            "source_type":  row.get("source_type", "correspondance"),
            "source_kind":  row.get("source_kind"),
            "title":        row.get("title", ""),
            "text":         text,
            "date_iso":     row.get("date_iso", ""),
            "date_year":    None,
            "period":       None,
            "period_order": None,
            "date_reliable": 1 if row.get("date_iso") else 0,
        })
    return entries


def assign_chunk_keys(entries: list[dict]) -> list[dict]:
    """
    Groupe par tome, trie par (letter_id, part_index),
    et assigne chunk_key = correspondance_{tome}_{pos:06d} commençant à 1.
    """
    by_tome: dict[int, list[dict]] = {}
    for e in entries:
        by_tome.setdefault(e["tome"], []).append(e)

    result = []
    for tome in sorted(by_tome):
        tome_entries = sorted(by_tome[tome], key=lambda x: (x["letter_id"], x["part_index"]))
        for pos, entry in enumerate(tome_entries, 1):
            entry["chunk_key"] = f"correspondance_{tome}_{pos:06d}"
        result.extend(tome_entries)
    return result


def embed_batch(client, texts: list[str]) -> list[list[float]]:
    resp = client.embeddings.create(input=texts, model=EMBED_MODEL)
    return [e.embedding for e in resp.data]


def main():
    parser = argparse.ArgumentParser(description="Embedding et insertion des lettres manquantes")
    parser.add_argument("--dry-run", action="store_true",
                        help="Afficher sans insérer dans la base")
    parser.add_argument("--input", default=str(INPUT),
                        help=f"Chemin de cleaned_cpt.jsonl (défaut: {INPUT})")
    parser.add_argument("--db", default=str(DB_PATH),
                        help=f"Chemin de la base SQLite (défaut: {DB_PATH})")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(
            f"Fichier introuvable : {input_path}\n"
            "Lancer d'abord :\n"
            "  python3 pipeline/batch_clean.py prepare --glob 'data/missing/raw_tome_*.jsonl'\n"
            "  python3 pipeline/batch_clean.py submit\n"
            "  python3 pipeline/batch_clean.py status\n"
            "  python3 pipeline/batch_clean.py process --output-dir data/missing"
        )

    entries = load_cleaned(input_path)
    print(f"Entrées valides : {len(entries)}")
    if not entries:
        print("Rien à insérer.")
        return

    entries = assign_chunk_keys(entries)

    # Enrichir avec date_year, period, period_order
    for e in entries:
        iso = e["date_iso"]
        if iso and len(iso) >= 4:
            try:
                year = int(iso[:4])
                e["date_year"] = year
                period, order = get_period(year)
                e["period"]       = period
                e["period_order"] = order
            except ValueError:
                pass
        if not e["date_iso"]:
            e["date_reliable"] = 0

    # Afficher le récapitulatif
    by_tome = {}
    for e in entries:
        by_tome.setdefault(e["tome"], []).append(e)
    for tome in sorted(by_tome):
        print(f"  Tome {tome:2d}: {len(by_tome[tome])} nouveaux chunks → "
              f"{by_tome[tome][0]['chunk_key']} … {by_tome[tome][-1]['chunk_key']}")

    if args.dry_run:
        print("\n[DRY-RUN] Rien inséré.")
        return

    # Chargement des clés env
    load_dotenv(ROOT / ".env")
    key = os.getenv("OPEN_AI_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    if not key:
        raise RuntimeError("Clé API OpenAI introuvable dans .env (OPEN_AI_KEY / LLM_API_KEY)")

    from openai import OpenAI
    client = OpenAI(api_key=key)

    db_path = Path(args.db)
    if not db_path.exists():
        raise FileNotFoundError(f"Base introuvable : {db_path}")

    conn = sqlite3.connect(db_path)
    try:
        # Récupérer les chunk_keys déjà présents (reprise sur interruption)
        done_keys = {r[0] for r in conn.execute("SELECT chunk_key FROM chunks").fetchall()}
        to_insert = [e for e in entries if e["chunk_key"] not in done_keys]
        print(f"\nDéjà insérés : {len(entries) - len(to_insert)}")
        print(f"À insérer    : {len(to_insert)}")

        if not to_insert:
            print("Rien à faire.")
            return

        total = len(to_insert)
        inserted = 0
        for batch_start in range(0, total, BATCH_SIZE):
            batch = to_insert[batch_start:batch_start + BATCH_SIZE]
            texts = [e["text"] for e in batch]
            vecs  = embed_batch(client, texts)

            for entry, vec in zip(batch, vecs):
                date_iso = entry["date_iso"] or "1800-01-01"
                year     = entry["date_year"] or 1800
                period   = entry["period"] or "Inconnu"
                period_o = entry["period_order"] or 99

                conn.execute(
                    "INSERT INTO chunks "
                    "(chunk_key, source_type, source_kind, title, text, "
                    " date_iso, date_year, period, period_order, date_reliable) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        entry["chunk_key"],
                        entry["source_type"],
                        entry["source_kind"],
                        entry["title"],
                        entry["text"],
                        date_iso, year, period, period_o,
                        entry["date_reliable"],
                    )
                )
                chunk_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                vec_blob = np.array(vec, dtype=np.float32).tobytes()
                conn.execute(
                    "INSERT INTO embeddings (chunk_id, model, dim, vector) VALUES (?,?,?,?)",
                    (chunk_id, EMBED_MODEL, len(vec), vec_blob)
                )
                inserted += 1

            conn.commit()
            done = min(batch_start + BATCH_SIZE, total)
            print(f"  {done}/{total} embeddings ({done/total*100:.1f}%)", end="\r")
            time.sleep(0.05)

        size_mb = db_path.stat().st_size / 1_048_576
        print(f"\n\n✓ {inserted} chunks insérés dans {db_path} ({size_mb:.1f} MB)")
        print("\nÉtape suivante :")
        print("  Mettre à jour _TOME_META dans pipeline/napoleon_api.py (max_letter)")
        print("  Redémarrer le serveur Flask pour recharger la matrice d'embeddings")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
