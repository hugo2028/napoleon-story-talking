"""Corrige prudemment les dates de la base RAG (data/rag/napoleon_clean.sqlite).

1. Tomes 29 à 32 de la Correspondance (Œuvres de Sainte-Hélène) : récits écrits après coup, pas des
   lettres. Passés en source_kind='memoir', date non fiable (hors des recherches par période et du tirage).
2. Tomes 1 à 28 : ils suivent l'ordre chronologique. Dans chaque tome, la plus longue suite de dates
   croissantes (dans l'ordre des passages) sert de fil. Un passage nettement hors de ce fil (plus de
   60 jours) est corrigé si son jour et son mois, avec l'année d'un voisin du fil, tombent entre ses
   deux voisins (± 31 jours) ; sinon sa date est marquée non fiable.
3. Années impossibles (avant 1769 ou après 1821) : date non fiable.

Chaque changement est consigné dans napoleon-corpus/metadata/date_fixes.csv.

Usage : python scripts/fix_corpus_dates.py [--dry-run] [--db base.sqlite] [--log journal.csv]
À lancer une seule fois sur une base non corrigée (par exemple la Release data-v2).
"""
from __future__ import annotations

import argparse
import bisect
import csv
import datetime as dt
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "rag" / "napoleon_clean.sqlite"
LOG = ROOT / "napoleon-corpus" / "metadata" / "date_fixes.csv"
KEY = re.compile(r"^correspondance_(\d+)_(\d+)$")
SAINTE_HELENE = (29, 30, 31, 32)
ECART = dt.timedelta(days=60)
MARGE = dt.timedelta(days=31)


def to_date(d: str | None) -> dt.date | None:
    try:
        return dt.date.fromisoformat(d) if d and len(d) == 10 else None
    except ValueError:
        return None


def longest_nondecreasing(values: list[dt.date]) -> set[int]:
    """Indices de la plus longue sous-suite croissante (au sens large)."""
    tails, tails_idx, parent = [], [], [-1] * len(values)
    for i, v in enumerate(values):
        k = bisect.bisect_right(tails, v)
        if k == len(tails):
            tails.append(v); tails_idx.append(i)
        else:
            tails[k] = v; tails_idx[k] = i
        parent[i] = tails_idx[k - 1] if k else -1
    out, i = set(), tails_idx[-1] if tails_idx else -1
    while i != -1:
        out.add(i); i = parent[i]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", type=Path, default=DB, help="base à corriger (défaut : data/rag/napoleon_clean.sqlite)")
    ap.add_argument("--log", type=Path, default=LOG, help="journal CSV des changements")
    ap.add_argument("--force", action="store_true", help="relancer sur une base déjà corrigée")
    args = ap.parse_args()
    conn = sqlite3.connect(args.db)
    log: list[tuple] = []

    # 1. Œuvres de Sainte-Hélène
    for vol in SAINTE_HELENE:
        for cid, key, d in conn.execute(
                "SELECT id, chunk_key, date_iso FROM chunks WHERE chunk_key LIKE ? AND "
                "(source_kind != 'memoir' OR date_reliable != 0)", (f"correspondance_{vol}_%",)).fetchall():
            log.append((cid, key, d, d, "oeuvre_sainte_helene"))
    # À appliquer une seule fois : sur une base déjà corrigée, le fil de chaque tome a changé et un second
    # passage corrigerait encore quelques dates en cascade.
    if not log and not args.force:
        print("Base déjà corrigée (tomes 29 à 32 déjà neutralisés) : rien à faire. --force pour relancer.")
        return
    if not args.dry_run:
        for vol in SAINTE_HELENE:
            conn.execute("UPDATE chunks SET source_kind='memoir', date_reliable=0 WHERE chunk_key LIKE ?",
                         (f"correspondance_{vol}_%",))

    # 2. Fil chronologique des tomes 1 à 28
    par_tome: dict[int, list] = {}
    for cid, key, d in conn.execute(
            "SELECT id, chunk_key, date_iso FROM chunks WHERE chunk_key LIKE 'correspondance_%' "
            "AND source_kind != 'memoir' AND date_reliable != 0").fetchall():
        m = KEY.match(key or "")
        if m and 1 <= int(m.group(1)) <= 28 and to_date(d):
            par_tome.setdefault(int(m.group(1)), []).append((int(m.group(2)), cid, key, to_date(d)))
    corrections, non_fiables = [], []
    for vol, rows in par_tome.items():
        rows.sort()
        dates = [r[3] for r in rows]
        fil = sorted(longest_nondecreasing(dates))
        fil_set = set(fil)
        for i, (_, cid, key, d) in enumerate(rows):
            if i in fil_set:
                continue
            k = bisect.bisect_left(fil, i)
            prev = dates[fil[k - 1]] if k > 0 else None
            nxt = dates[fil[k]] if k < len(fil) else None
            if (prev is None or d >= prev - ECART) and (nxt is None or d <= nxt + ECART):
                continue          # léger désordre de quelques jours : rien à corriger
            lo = (prev or nxt) - MARGE
            hi = (nxt or prev) + MARGE
            nouvelle = None
            for annee in dict.fromkeys(a.year for a in (prev, nxt) if a):
                try:
                    cand = d.replace(year=annee)
                except ValueError:
                    continue
                if lo <= cand <= hi:
                    nouvelle = cand
                    break
            if nouvelle:
                corrections.append((nouvelle.isoformat(), nouvelle.year, cid))
                log.append((cid, key, d.isoformat(), nouvelle.isoformat(), "annee_corrigee"))
            else:
                non_fiables.append((cid,))
                log.append((cid, key, d.isoformat(), "", "date_non_fiable"))

    # 3. Années impossibles : confusion d'OCR sur le premier chiffre (4814 → 1814), sinon non fiables
    impossibles = []
    for cid, key, d in conn.execute("SELECT id, chunk_key, date_iso FROM chunks WHERE source_kind != 'memoir' "
                                    "AND date_reliable != 0 AND (date_year < 1769 OR date_year > 1821)").fetchall():
        ocr = "1" + d[1:] if d and len(d) >= 4 and d[0] in "47" else None
        if ocr and 1769 <= int(ocr[:4]) <= 1821:
            corrections.append((ocr, int(ocr[:4]), cid))
            log.append((cid, key, d, ocr, "annee_ocr"))
        else:
            impossibles.append((cid, key, d))
            log.append((cid, key, d, "", "annee_impossible"))

    print(f"Œuvres de Sainte-Hélène : {sum(1 for l in log if l[4] == 'oeuvre_sainte_helene')} passages")
    print(f"Années corrigées : {len(corrections)} (dont OCR {sum(1 for l in log if l[4] == 'annee_ocr')}) | dates non fiables : {len(non_fiables)} | "
          f"années impossibles : {len(impossibles)}")
    if args.dry_run:
        for l in log[-12:]:
            print("  ", l)
        return
    conn.executemany("UPDATE chunks SET date_iso=?, date_year=? WHERE id=?", corrections)
    conn.executemany("UPDATE chunks SET date_reliable=0 WHERE id=?", non_fiables + [(i[0],) for i in impossibles])
    conn.commit()
    with args.log.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "chunk_key", "date_avant", "date_apres", "action"])
        w.writerows(log)
    print(f"Journal : {args.log}")


if __name__ == "__main__":
    main()
