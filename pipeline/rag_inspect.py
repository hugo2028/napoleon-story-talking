"""
rag_inspect.py — Diagnostic RAG : quelles lettres sont remontées pour une question donnée ?

Usage :
  # Questions du fichier d'évaluation standard
  python3 pipeline/rag_inspect.py

  # Questions personnalisées en ligne de commande
  python3 pipeline/rag_inspect.py "Quelle fut ta défaite navale en Égypte ?" "Raconte Austerlitz"

  # Avec classification LLM (event + sub_topic) — coûte des tokens
  python3 pipeline/rag_inspect.py --classify

  # Sortie HTML dans un fichier personnalisé
  python3 pipeline/rag_inspect.py --out /tmp/rapport.html

Génère un rapport HTML dans data/eval/rag_inspect_<timestamp>.html
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from napoleon_agent import (
    RAG_DB, MEMOIR_DB, EVENTS_FILE,
    load_db, embed_question, cosine_sim, fetch_chunks,
    classify_event, classify_sub_event,
)
import numpy as np
from openai import OpenAI

# ── Config ───────────────────────────────────────────────────────────────────

EVAL_QUESTIONS = ROOT / "data" / "eval" / "rag_eval_questions.jsonl"
OUT_DIR        = ROOT / "data" / "eval"

EXTRA_QUESTIONS = [
    {"question": "What was the naval defeat that isolated the expedition from France?",
     "category": "naval_egypt", "expect_rag_sources": True},
    {"question": "Raconte-moi la prise d'Alexandrie",
     "category": "military_egypt", "expect_rag_sources": True},
    {"question": "Parle-moi de la campagne d'Égypte",
     "category": "general_egypt", "expect_rag_sources": True},
    {"question": "Quel rôle as-tu joué lors du siège de Toulon ?",
     "category": "toulon", "expect_rag_sources": True},
    {"question": "Raconte-moi la bataille d'Austerlitz",
     "category": "austerlitz", "expect_rag_sources": True},
    {"question": "Comment as-tu rencontré Joséphine ?",
     "category": "josephine", "expect_rag_sources": True},
    {"question": "Quand es-tu né ?",
     "category": "biography", "expect_rag_sources": False},
]

# ── Chargement ────────────────────────────────────────────────────────────────

def load_eval_questions() -> list[dict]:
    if not EVAL_QUESTIONS.exists():
        return []
    questions = []
    with open(EVAL_QUESTIONS) as f:
        for line in f:
            line = line.strip()
            if line:
                questions.append(json.loads(line))
    return questions


def run_rag(client, conn, emb_matrix, chunk_ids, question: str,
            do_classify: bool, chat_client, events: list, model: str) -> dict:
    """Exécute le pipeline RAG et retourne les résultats pour une question."""
    q_vec = embed_question(client, question)
    sims  = cosine_sim(q_vec, emb_matrix)
    id_to_idx = {chunk_ids[i]: i for i in range(len(chunk_ids))}

    event     = None
    sub_topic = None

    if do_classify:
        event = classify_event(chat_client, question, events, model)
        sub_topic = classify_sub_event(chat_client, question, event, model) if event else None

    # Fenêtre événement ou mode thématique
    if event:
        rows = conn.execute(
            "SELECT id FROM chunks WHERE date_iso >= ? AND date_iso <= ?",
            (event["start"][:7], event["end"][:7] + "\xff")
        ).fetchall()
        ids     = [r[0] for r in rows]
        letters = fetch_chunks(conn, ids)
        win_size = len(letters)

        # Score principal
        for l in letters:
            idx = id_to_idx.get(l["id"])
            l["score"] = float(sims[idx]) if idx is not None else 0.0

        # Score sous-thème
        if sub_topic:
            from napoleon_agent import embed_question as eq
            sub_vec  = eq(client, sub_topic)
            sub_sims = cosine_sim(sub_vec, emb_matrix)
            for l in letters:
                idx = id_to_idx.get(l["id"])
                sub_s = float(sub_sims[idx]) if idx is not None else 0.0
                l["score"] = max(l["score"], sub_s)

            # Keyword boost
            keywords = [w for w in sub_topic.lower().split() if len(w) > 3]
            for kw in keywords:
                kw_rows = conn.execute(
                    "SELECT id FROM chunks WHERE id IN ({}) AND lower(text) LIKE ?".format(
                        ",".join("?" * len(ids))
                    ),
                    (*ids, f"%{kw}%")
                ).fetchall()
                kw_ids = {r[0] for r in kw_rows}
                for l in letters:
                    if l["id"] in kw_ids and l["score"] < 0.35:
                        l["score"] = 0.35

        retrieved = sorted(letters, key=lambda l: -l["score"])[:15]
        above_threshold = [l for l in letters if l["score"] >= 0.35]

    else:
        # Mode thématique : top-15 global
        top_idx = np.argsort(sims)[::-1][:20]
        retrieved = []
        for i in top_idx:
            cid = chunk_ids[i]
            row = conn.execute("SELECT * FROM chunks WHERE id=?", (cid,)).fetchone()
            if row:
                col = [d[0] for d in conn.execute("SELECT * FROM chunks LIMIT 0").description]
                d = dict(zip(col, row))
                d["score"] = float(sims[i])
                if d.get("date_iso", "9999")[:4] <= "1821":
                    retrieved.append(d)
        retrieved = retrieved[:15]
        win_size  = None
        above_threshold = retrieved

    return {
        "event":             event,
        "sub_topic":         sub_topic,
        "window_size":       win_size,
        "above_threshold":   len(above_threshold) if event else None,
        "retrieved":         retrieved,
    }


# ── Rapport HTML ──────────────────────────────────────────────────────────────

CSS = """
body { font-family: system-ui, sans-serif; max-width: 1100px; margin: 40px auto;
       padding: 0 20px; background: #0f0e0c; color: #e8dfc8; }
h1 { color: #c9a84c; letter-spacing: .15em; text-transform: uppercase; font-size: 18px; }
h2 { color: #c9a84c; font-size: 14px; margin-top: 40px; text-transform: uppercase;
     letter-spacing: .1em; border-bottom: 1px solid #2e2618; padding-bottom: 6px; }
.question-block { background: #15120d; border: 1px solid #2e2618; border-radius: 10px;
                  padding: 18px 22px; margin: 24px 0; }
.q-text { font-size: 16px; font-weight: 600; color: #e8dfc8; margin-bottom: 10px; }
.meta { font-size: 12px; color: #9a8e78; margin-bottom: 12px; }
.meta span { margin-right: 16px; }
.meta .event-tag { background: rgba(201,168,76,.15); color: #c9a84c;
                   padding: 2px 8px; border-radius: 4px; border: 1px solid rgba(201,168,76,.3); }
.meta .sub-tag   { background: rgba(100,180,100,.12); color: #8bc88b;
                   padding: 2px 8px; border-radius: 4px; border: 1px solid rgba(100,180,100,.3); }
.letters-grid { display: flex; flex-direction: column; gap: 8px; }
.letter-card { background: #1d1810; border: 1px solid #2e2618; border-radius: 8px;
               padding: 12px 16px; font-size: 12px; }
.letter-header { display: flex; gap: 12px; align-items: baseline; margin-bottom: 6px; }
.letter-date { color: #c9a84c; font-weight: 600; min-width: 90px; }
.letter-id   { color: #9a8e78; }
.score-bar-wrap { flex: 1; display: flex; align-items: center; gap: 8px; }
.score-val { color: #e8dfc8; min-width: 42px; text-align: right; }
.score-bar { height: 5px; border-radius: 3px; background: #2e2618; flex: 1; position: relative; }
.score-fill { height: 100%; border-radius: 3px; }
.score-high   { background: #c9a84c; }
.score-medium { background: #8b7a3a; }
.score-low    { background: #4a3e20; }
.letter-text { color: #9a8e78; line-height: 1.5; }
.no-letters { color: #9a8e78; font-style: italic; padding: 12px 0; }
.stats { font-size: 12px; color: #9a8e78; margin-bottom: 12px; }
.badge { display: inline-block; padding: 1px 7px; border-radius: 4px; font-size: 11px;
         margin-left: 6px; }
.badge-ok  { background: rgba(100,180,100,.15); color: #8bc88b; }
.badge-warn{ background: rgba(220,150,50,.15);  color: #e0a040; }
.badge-err { background: rgba(200,80,80,.15);   color: #e07070; }
"""

def score_class(s: float) -> str:
    if s >= 0.45: return "score-high"
    if s >= 0.35: return "score-medium"
    return "score-low"

def render_html(results: list[dict], do_classify: bool) -> str:
    ts    = datetime.now().strftime("%Y-%m-%d %H:%M")
    mode  = "Classification LLM activée" if do_classify else "Mode sémantique uniquement (sans LLM)"
    items = []

    for r in results:
        q    = r["question"]
        cat  = r.get("category", "—")
        meta = r["rag"]
        letters = meta["retrieved"]

        event_html = ""
        if meta["event"]:
            ev = meta["event"]
            event_html = f'<span class="event-tag">📍 {ev["event"]} ({ev["start"][:4]}–{ev["end"][:4]})</span>'
            if meta["sub_topic"]:
                event_html += f'<span class="sub-tag">🔍 {meta["sub_topic"]}</span>'
            win  = meta["window_size"] or "?"
            abv  = meta["above_threshold"] if meta["above_threshold"] is not None else "?"
            event_html += f'<span>fenêtre: {win} lettres, ≥0.35: {abv}</span>'
        else:
            event_html = '<span style="color:#9a8e78">⚡ Mode thématique (pas d\'événement unique)</span>'

        # Badge qualité
        n = len(letters)
        if n >= 10:
            badge = '<span class="badge badge-ok">✓ riche ({n})</span>'.format(n=n)
        elif n >= 5:
            badge = '<span class="badge badge-warn">~ moyen ({n})</span>'.format(n=n)
        elif n > 0:
            badge = '<span class="badge badge-warn">⚠ peu ({n})</span>'.format(n=n)
        else:
            badge = '<span class="badge badge-err">✗ aucune</span>'

        # Cards lettres
        if letters:
            cards = []
            for l in letters:
                s     = l.get("score", 0)
                sc    = score_class(s)
                fill  = int(s * 100)
                date  = l.get("date_iso") or "date inconnue"
                text  = (l.get("text") or "").strip()[:280].replace("<","&lt;")
                cards.append(f"""
<div class="letter-card">
  <div class="letter-header">
    <span class="letter-date">{date}</span>
    <span class="letter-id">id={l['id']}</span>
    <div class="score-bar-wrap">
      <span class="score-val">{s:.3f}</span>
      <div class="score-bar"><div class="score-fill {sc}" style="width:{fill}%"></div></div>
    </div>
  </div>
  <div class="letter-text">{text}…</div>
</div>""")
            letters_html = "<div class='letters-grid'>" + "".join(cards) + "</div>"
        else:
            letters_html = "<div class='no-letters'>Aucune lettre remontée.</div>"

        items.append(f"""
<div class="question-block">
  <div class="q-text">"{q}" {badge}</div>
  <div class="meta">
    <span>catégorie: <b>{cat}</b></span>
    {event_html}
  </div>
  {letters_html}
</div>""")

    body = "\n".join(items)
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"/>
  <title>RAG Inspect — {ts}</title>
  <style>{CSS}</style>
</head>
<body>
  <h1>RAG Inspect — {ts}</h1>
  <p style="color:#9a8e78;font-size:13px">{mode} · {len(results)} questions</p>
  {body}
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Diagnostic RAG — lettres remontées par question")
    parser.add_argument("questions", nargs="*", help="Questions à tester (optionnel)")
    parser.add_argument("--classify", action="store_true",
                        help="Activer la classification LLM (event + sub_topic) — coûte des tokens")
    parser.add_argument("--out", help="Chemin du fichier HTML de sortie")
    args = parser.parse_args()

    # Chargement des bases
    print("Chargement RAG…", end=" ", flush=True)
    conn, emb_matrix, chunk_ids = load_db(RAG_DB)
    print(f"{len(emb_matrix)} vecteurs")

    openai_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    client = OpenAI(api_key=openai_key)

    chat_client = client
    model       = os.getenv("LLM_MODEL", "gpt-4o-mini")
    events      = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))

    # Questions à tester
    questions: list[dict] = []
    if args.questions:
        questions = [{"question": q, "category": "cli"} for q in args.questions]
    else:
        questions = load_eval_questions() + EXTRA_QUESTIONS

    # Run
    results = []
    for i, q_obj in enumerate(questions):
        q = q_obj["question"]
        print(f"[{i+1}/{len(questions)}] {q[:70]}…")
        try:
            rag = run_rag(
                client, conn, emb_matrix, chunk_ids, q,
                do_classify=args.classify,
                chat_client=chat_client,
                events=events,
                model=model,
            )
            results.append({**q_obj, "rag": rag})
            ev  = rag["event"]["event"] if rag["event"] else "thématique"
            sub = f" / {rag['sub_topic']}" if rag["sub_topic"] else ""
            n   = len(rag["retrieved"])
            print(f"  → event={ev}{sub}  lettres={n}")
        except Exception as e:
            print(f"  ✗ ERREUR: {e}")
            results.append({**q_obj, "rag": {"event": None, "sub_topic": None,
                                              "window_size": None, "above_threshold": None,
                                              "retrieved": []}})

    # Rapport HTML
    html = render_html(results, args.classify)
    out_path = Path(args.out) if args.out else \
        OUT_DIR / f"rag_inspect_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"\n✓ Rapport : {out_path}")
    print(f"  open \"{out_path}\"")


if __name__ == "__main__":
    main()
