"""
Construit un dataset SFT pour Mistral 7B à partir du dataset MH0386/napoleon_bonaparte.

Pour chaque question :
  1. RAG : top-10 passages chronologiques depuis napoleon_chron.sqlite
  2. Batch API : LLM génère la réponse Napoleon en français à partir des sources

Workflow:
  python3 pipeline/build_sft_rag.py prepare
  python3 pipeline/build_sft_rag.py submit
  python3 pipeline/build_sft_rag.py status
  python3 pipeline/build_sft_rag.py process
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import time
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
RAG_DB = ROOT / "data" / "rag" / "napoleon_clean.sqlite"
MEMOIR_DB = ROOT / "data" / "rag" / "napoleon_memoirs.sqlite"
BATCH_DIR = ROOT / "data" / "batch"
OUTPUT_DIR = ROOT / "napoleon-corpus" / "datasets" / "sft"
EVENTS_TIMELINE = ROOT / "napoleon-corpus" / "metadata" / "events_timeline.json"

SYSTEM_PROMPT = (
    "Tu es Napoléon Bonaparte à Sainte-Hélène. "
    "Tu racontes ta vie à ton interlocuteur comme un récit vivant, à la première personne, en français. "
    "Tu t'appuies sur ta correspondance et tes écrits — tu reprends leurs mots exacts, mais tu les tisses dans un récit oral, immersif, comme si tu revivais les événements. "
    "Tu parles avec la voix directe et concrète de tes lettres, sans emphase ni rhétorique creuse."
)

GENERATION_PROMPT = """\
Voici des extraits de ta correspondance contemporaine des événements, classés chronologiquement :

{context_lettres}

---

Voici des passages de tes mémoires dictés à Sainte-Hélène :

{context_memoires}

---

Question : {question}

Tu racontes cette histoire comme un récit vivant, devant ton interlocuteur.

Structure :
1. Ouvre depuis Sainte-Hélène — une phrase qui ancre le souvenir : "Ah, je me souviens..." ou "Oui, ce moment..."
2. Plonge dans le récit au passé narratif : "C'était le [date précise]..." — reprends les mots exacts de tes lettres, mais relie-les par des ponts narratifs ("puis", "quelques jours plus tard", "c'est alors que")
3. Couvre 2 à 3 moments chronologiques depuis tes lettres
4. Termine par une phrase naturelle et variée qui invite ton interlocuteur à continuer — trouve ta propre formulation, dans le ton de la conversation

Règles :
- Reprends les formulations exactes de tes lettres, intégrées dans le fil du récit
- Style oral, direct — comme tu parlais à Las Cases
- Pas de liste, pas de tirets — prose continue
- Ignore les sources dont la date est manifestement incohérente avec les autres\
"""

GENERATION_PROMPT_CONTINUATION = """\
Voici la suite des extraits de ta correspondance, à partir de la prochaine lettre non encore évoquée :

{context_lettres_suite}

---

Voici des passages de tes mémoires dictés à Sainte-Hélène :

{context_memoires}

---

Continue le récit exactement là où tu t'es arrêté dans ta réponse précédente.
- Ne reviens pas sur les événements ou dates déjà racontés
- Avance chronologiquement : commence par la prochaine lettre non encore mentionnée
- Même style : reprends les mots exacts de tes lettres, tisses-les dans le récit
- Termine par une phrase naturelle et variée qui invite à continuer — trouve ta propre formulation\
"""

GENERATION_PROMPT_LETTERS_ONLY = """\
Voici des extraits de ta correspondance, classés chronologiquement :

{context_lettres}

---

Question : {question}

Tu racontes cette histoire comme un récit vivant, devant ton interlocuteur.

Structure :
1. Ouvre depuis Sainte-Hélène — une phrase qui ancre le souvenir
2. Plonge dans le récit au passé narratif : "C'était le [date]..." — reprends les mots exacts de tes lettres
3. Couvre 2 à 3 moments chronologiques, reliés par des ponts narratifs
4. Termine par une invitation à continuer : "Savez-vous ce que j'ai fait ensuite ?"

Style oral, direct, prose continue — pas de liste.\
"""

PERIOD_LABELS = {
    (1769, 1792): "Jeunesse",
    (1793, 1795): "Révolution & Toulon",
    (1796, 1797): "Italie",
    (1798, 1799): "Égypte",
    (1800, 1804): "Consulat",
    (1805, 1814): "Empire",
    (1815, 1821): "Sainte-Hélène",
}


def get_period(year: int | None) -> str | None:
    if not year:
        return None
    for (y1, y2), label in PERIOD_LABELS.items():
        if y1 <= year <= y2:
            return label
    return None


# ---------------------------------------------------------------------------
# RAG helpers
# ---------------------------------------------------------------------------

def load_env():
    load_dotenv(ROOT / ".env")
    key = os.getenv("OPEN_AI_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    if not key:
        raise RuntimeError("Clé API OpenAI introuvable dans .env")
    return key


def embed_texts(client, texts: list[str], model="text-embedding-3-small", batch_size=96) -> np.ndarray:
    all_vecs = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        resp = client.embeddings.create(input=batch, model=model)
        vecs = [e.embedding for e in resp.data]
        all_vecs.extend(vecs)
        if i % (batch_size * 10) == 0 and i > 0:
            print(f"  Embeddings : {i}/{len(texts)}")
    return np.array(all_vecs, dtype=np.float32)


def cosine_sim(q: np.ndarray, M: np.ndarray) -> np.ndarray:
    q_norm = q / (np.linalg.norm(q) + 1e-10)
    norms = np.linalg.norm(M, axis=1, keepdims=True) + 1e-10
    return (M / norms) @ q_norm


def load_rag_db(db_path: Path) -> tuple[sqlite3.Connection, np.ndarray, list[int]]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT chunk_id, vector FROM embeddings ORDER BY chunk_id").fetchall()
    chunk_ids = [r[0] for r in rows]
    emb_matrix = np.array([np.frombuffer(r[1], dtype=np.float32) for r in rows])
    return conn, emb_matrix, chunk_ids


def load_memoir_db(db_path: Path) -> tuple[sqlite3.Connection, np.ndarray, list[int]] | None:
    """Charge la base mémoires Sainte-Hélène. Retourne None si absente."""
    if not db_path.exists():
        return None
    return load_rag_db(db_path)


def query_rag(conn: sqlite3.Connection, emb_matrix: np.ndarray,
              chunk_ids: list[int], query_vec: np.ndarray, top_k: int = 10) -> list[dict]:
    sims = cosine_sim(query_vec, emb_matrix)
    # Récupère un pool 5x pour détecter l'événement dominant
    pool_idx = np.argsort(sims)[::-1][:top_k * 5]

    col_names = [d[0] for d in conn.execute("SELECT * FROM chunks LIMIT 0").description]
    pool = []
    for idx in pool_idx:
        cid = chunk_ids[idx]
        row = conn.execute("SELECT * FROM chunks WHERE id=?", (cid,)).fetchone()
        d = dict(zip(col_names, row))
        d["score"] = float(sims[idx])
        pool.append(d)

    # Filtre par événement historique :
    # Si 2 des 5 meilleurs résultats tombent dans la plage d'un événement connu,
    # rescorer TOUTES les lettres de la fenêtre temporelle (pas seulement le pool initial).
    # Sinon (question thématique), pas de filtre.
    try:
        events = json.loads(EVENTS_TIMELINE.read_text(encoding="utf-8"))
    except Exception:
        events = []

    def date_in_event(date_iso: str, event: dict) -> bool:
        if not date_iso or len(date_iso) < 7:
            return False
        return event["start"][:7] <= date_iso[:7] <= event["end"][:7]

    top5 = pool[:5]
    matched_event = None
    for event in events:
        matches = sum(1 for r in top5 if date_in_event(r.get("date_iso", ""), event))
        if matches >= 2:
            matched_event = event
            break

    if matched_event:
        # Rescorer toutes les lettres de la fenêtre de l'événement (pas seulement le pool)
        event_ids = {
            r[0] for r in conn.execute(
                "SELECT id FROM chunks WHERE date_iso >= ? AND date_iso <= ?",
                (matched_event["start"][:7], matched_event["end"][:7] + "\xff")
            ).fetchall()
        }
        event_indices = [i for i, cid in enumerate(chunk_ids) if cid in event_ids]
        pool = []
        for idx in event_indices:
            cid = chunk_ids[idx]
            row = conn.execute("SELECT * FROM chunks WHERE id=?", (cid,)).fetchone()
            d = dict(zip(col_names, row))
            d["score"] = float(sims[idx])
            pool.append(d)

    # Expansion temporelle : ajouter les lettres proches dans le temps des top-3
    # Une fois les meilleures lettres identifiées, rajouter toutes les lettres
    # dans une fenêtre ±NEIGHBOR_DAYS autour de leur plage de dates.
    NEIGHBOR_DAYS = 45
    top3_dates = [
        r["date_iso"][:10] for r in sorted(pool, key=lambda r: -r["score"])[:3]
        if r.get("date_iso") and len(r["date_iso"]) >= 10
    ]
    if top3_dates:
        from datetime import date as _date, timedelta
        parsed = []
        for d in top3_dates:
            try:
                parsed.append(_date.fromisoformat(d))
            except ValueError:
                pass
        if parsed:
            anchor_min = min(parsed) - timedelta(days=NEIGHBOR_DAYS)
            anchor_max = max(parsed) + timedelta(days=NEIGHBOR_DAYS)
            existing_ids = {r["id"] for r in pool}
            neighbor_rows = conn.execute(
                "SELECT id FROM chunks WHERE date_iso >= ? AND date_iso <= ?",
                (anchor_min.isoformat()[:7], anchor_max.isoformat()[:7] + "\xff")
            ).fetchall()
            neighbor_ids = {r[0] for r in neighbor_rows} - existing_ids
            neighbor_indices = [i for i, cid in enumerate(chunk_ids) if cid in neighbor_ids]
            for idx in neighbor_indices:
                cid = chunk_ids[idx]
                row = conn.execute("SELECT * FROM chunks WHERE id=?", (cid,)).fetchone()
                d = dict(zip(col_names, row))
                d["score"] = float(sims[idx])
                pool.append(d)

    # Priorité aux dates complètes (YYYY-MM-DD = 10 chars), puis par score
    def date_priority(r):
        date = r.get("date_iso") or ""
        complete = len(date) == 10  # YYYY-MM-DD
        return (0 if complete else 1, -r["score"])

    pool.sort(key=date_priority)
    results = pool[:top_k]

    # Trier chronologiquement pour le contexte
    results.sort(key=lambda r: (r.get("date_iso") or "9999", r.get("period_order") or 99))
    return results


def build_context_letters(chunks: list[dict]) -> str:
    parts = []
    for i, c in enumerate(chunks, 1):
        date = c.get("date_iso") or ""
        year = int(date[:4]) if date else None
        period = get_period(year)
        label_parts = []
        if date:
            label_parts.append(date)
        if period:
            label_parts.append(period)
        label = " | ".join(label_parts) if label_parts else "date inconnue"
        text = c.get("text", "").strip()[:600]
        parts.append(f"[Source {i} — {label}]\n{text}")
    return "\n\n".join(parts) if parts else "(aucune lettre trouvée)"


def build_context_memoirs(chunks: list[dict]) -> str:
    parts = []
    for i, c in enumerate(chunks, 1):
        title = c.get("title", "").strip()
        label = f"Mémoires SH — {title}" if title else "Mémoires de Sainte-Hélène"
        text = c.get("text", "").strip()[:300]
        parts.append(f"[{label}]\n{text}")
    return "\n\n".join(parts) if parts else "(aucun mémoire trouvé)"


def build_context(chunks: list[dict]) -> str:
    """Compatibilité — utilisé si pas de mémoires disponibles."""
    return build_context_letters(chunks)


def query_memoir(conn: sqlite3.Connection, emb_matrix: np.ndarray,
                 chunk_ids: list[int], query_vec: np.ndarray,
                 top_k: int = 3, min_score: float = 0.3) -> list[dict]:
    """Requête dans la base mémoires Sainte-Hélène (pas de filtre temporel)."""
    sims = cosine_sim(query_vec, emb_matrix)
    top_idx = np.argsort(sims)[::-1][:top_k * 3]

    col_names = [d[0] for d in conn.execute("SELECT * FROM chunks LIMIT 0").description]
    results = []
    for idx in top_idx:
        score = float(sims[idx])
        if score < min_score:
            break
        cid = chunk_ids[idx]
        row = conn.execute("SELECT * FROM chunks WHERE id=?", (cid,)).fetchone()
        d = dict(zip(col_names, row))
        d["score"] = score
        results.append(d)
        if len(results) >= top_k:
            break

    return results


# ---------------------------------------------------------------------------
# prepare
# ---------------------------------------------------------------------------

def cmd_prepare(args):
    key = load_env()
    from openai import OpenAI
    client = OpenAI(api_key=key)

    print("Chargement du dataset MH0386/napoleon_bonaparte ...")
    from datasets import load_dataset
    ds = load_dataset("MH0386/napoleon_bonaparte", split="train")
    questions = [row["Q"] for row in ds]
    print(f"  {len(questions)} questions")

    # IDs déjà traités
    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    state_file = BATCH_DIR / "batch_sft_state.json"
    done_ids = set()
    sft_batch_file = BATCH_DIR / "batch_sft_01.jsonl"
    if sft_batch_file.exists() and state_file.exists():
        for line in sft_batch_file.read_text().splitlines():
            if line.strip():
                done_ids.add(json.loads(line)["custom_id"])
    remaining = [(i, q) for i, q in enumerate(questions) if str(i) not in done_ids]
    print(f"  Déjà préparés : {len(done_ids)} | Restants : {len(remaining)}")

    if not remaining:
        print("Rien à préparer.")
        return

    # Charger le RAG lettres
    print(f"Chargement RAG lettres : {RAG_DB} ...")
    conn, emb_matrix, chunk_ids = load_rag_db(RAG_DB)
    print(f"  {len(emb_matrix)} vecteurs chargés")

    # Charger le RAG mémoires (optionnel)
    memoir_db = load_memoir_db(MEMOIR_DB)
    if memoir_db:
        m_conn, m_matrix, m_ids = memoir_db
        print(f"Chargement RAG mémoires : {MEMOIR_DB} ({len(m_matrix)} vecteurs)")
    else:
        m_conn = m_matrix = m_ids = None
        print(f"RAG mémoires absent ({MEMOIR_DB}) — lettres seules")

    # Embedder les questions restantes
    print("Embedding des questions ...")
    remaining_questions = [q for _, q in remaining]
    q_vecs = embed_texts(client, remaining_questions)

    # Construire le batch JSONL
    print("Construction du batch ...")
    lines = []
    meta_lines = []
    for (orig_idx, question), q_vec in zip(remaining, q_vecs):
        letter_chunks = query_rag(conn, emb_matrix, chunk_ids, q_vec, top_k=args.top_k)
        ctx_lettres = build_context_letters(letter_chunks)

        if m_conn is not None:
            memoir_chunks = query_memoir(m_conn, m_matrix, m_ids, q_vec, top_k=20)
            ctx_memoires = build_context_memoirs(memoir_chunks)
            user_content = GENERATION_PROMPT.format(
                context_lettres=ctx_lettres,
                context_memoires=ctx_memoires,
                question=question,
            )
        else:
            memoir_chunks = []
            user_content = GENERATION_PROMPT_LETTERS_ONLY.format(
                context_lettres=ctx_lettres,
                question=question,
            )

        request = {
            "custom_id": str(orig_idx),
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {
                "model": args.model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                "max_tokens": 512,
            },
        }
        lines.append(json.dumps(request, ensure_ascii=False))
        meta_lines.append(json.dumps({
            "id": str(orig_idx),
            "question": question,
            "chunks": [{"date_iso": c.get("date_iso"), "text": c.get("text", "")[:200]} for c in letter_chunks],
            "memoir_chunks": [{"title": c.get("title"), "text": c.get("text", "")[:200]} for c in memoir_chunks],
        }, ensure_ascii=False))

    sft_batch_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (BATCH_DIR / "batch_sft_meta.jsonl").write_text("\n".join(meta_lines) + "\n", encoding="utf-8")
    size_mb = sft_batch_file.stat().st_size / 1_048_576
    print(f"\n✓ Batch prêt : {sft_batch_file} ({len(lines)} requêtes, {size_mb:.1f} MB)")
    print("Prochaine étape : python3 pipeline/build_sft_rag.py submit")


# ---------------------------------------------------------------------------
# submit
# ---------------------------------------------------------------------------

def cmd_submit(args):
    key = load_env()
    from openai import OpenAI
    client = OpenAI(api_key=key)

    batch_file = BATCH_DIR / "batch_sft_01.jsonl"
    state_file = BATCH_DIR / "batch_sft_state.json"

    print(f"Upload {batch_file} ...")
    with open(batch_file, "rb") as f:
        uploaded = client.files.create(file=f, purpose="batch")
    batch = client.batches.create(
        input_file_id=uploaded.id,
        endpoint="/v1/chat/completions",
        completion_window="24h",
    )
    print(f"  Batch ID : {batch.id}  status={batch.status}")
    state = {"batch_id": batch.id, "file_id": uploaded.id, "status": batch.status}
    state_file.write_text(json.dumps(state, indent=2))
    print(f"\n✓ Soumis. Vérifier : python3 pipeline/build_sft_rag.py status")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def cmd_status(args):
    key = load_env()
    from openai import OpenAI
    client = OpenAI(api_key=key)

    state = json.loads((BATCH_DIR / "batch_sft_state.json").read_text())
    batch = client.batches.retrieve(state["batch_id"])
    c = batch.request_counts
    print(f"Status : {batch.status}  |  {c.completed}/{c.total} ({c.failed} failed)")
    state["status"] = batch.status
    state["output_file_id"] = batch.output_file_id
    (BATCH_DIR / "batch_sft_state.json").write_text(json.dumps(state, indent=2))
    if batch.status == "completed":
        print("✓ Terminé. Lancer : python3 pipeline/build_sft_rag.py process")


# ---------------------------------------------------------------------------
# process
# ---------------------------------------------------------------------------

def cmd_process(args):
    key = load_env()
    from openai import OpenAI
    client = OpenAI(api_key=key)

    state = json.loads((BATCH_DIR / "batch_sft_state.json").read_text())
    output_file_id = state.get("output_file_id")
    if not output_file_id:
        raise RuntimeError("output_file_id absent — vérifiez le status.")

    meta = {}
    for line in (BATCH_DIR / "batch_sft_meta.jsonl").read_text().splitlines():
        if line.strip():
            m = json.loads(line)
            meta[m["id"]] = m

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / "napoleon_sft.jsonl"

    print(f"Téléchargement résultats ({output_file_id}) ...")
    content = client.files.content(output_file_id).text

    written = errors = 0
    with open(output_file, "w", encoding="utf-8") as f:
        for line in content.splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            cid = r.get("custom_id")
            m = meta.get(cid, {})
            try:
                answer = r["response"]["body"]["choices"][0]["message"]["content"].strip()
            except Exception as e:
                errors += 1
                continue
            if not answer:
                errors += 1
                continue

            question = m.get("question", "")
            entry = {
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": answer},
                ]
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            written += 1

    print(f"\n✓ Dataset SFT : {output_file}")
    print(f"  Exemples : {written}  |  Erreurs : {errors}")


# ---------------------------------------------------------------------------
# test
# ---------------------------------------------------------------------------

def cmd_test(args):
    key = load_env()
    from openai import OpenAI
    client = OpenAI(api_key=key)

    print(f"Chargement RAG lettres : {RAG_DB} ...")
    conn, emb_matrix, chunk_ids = load_rag_db(RAG_DB)
    print(f"  {len(emb_matrix)} vecteurs")

    memoir_db = load_memoir_db(MEMOIR_DB)
    if memoir_db:
        m_conn, m_matrix, m_ids = memoir_db
        print(f"Chargement RAG mémoires : {MEMOIR_DB} ({len(m_matrix)} vecteurs)")
    else:
        m_conn = m_matrix = m_ids = None
        print(f"RAG mémoires absent — lettres seules")
    print()

    if args.question:
        samples = [{"Q": args.question}]
    else:
        print("Chargement dataset ...")
        from datasets import load_dataset
        ds = load_dataset("MH0386/napoleon_bonaparte", split="train")
        samples = [{"Q": row["Q"]} for row in list(ds)[:2]]

    for i, row in enumerate(samples):
        question = row["Q"]
        print(f"{'='*60}")
        print(f"[{i+1}] QUESTION : {question}")
        print()

        q_vec = embed_texts(client, [question])[0]
        letter_chunks = query_rag(conn, emb_matrix, chunk_ids, q_vec, top_k=10)
        ctx_lettres = build_context_letters(letter_chunks)

        print("SOURCES LETTRES (top 3) :")
        for c in letter_chunks[:3]:
            print(f"  [{c.get('date_iso','?')}] score={c.get('score',0):.4f}  {c.get('text','')[:80]}...")
        print()

        if m_conn is not None:
            memoir_chunks = query_memoir(m_conn, m_matrix, m_ids, q_vec, top_k=20)
            ctx_memoires = build_context_memoirs(memoir_chunks)
            print(f"SOURCES MÉMOIRES (top {len(memoir_chunks)}) :")
            for c in memoir_chunks[:5]:
                print(f"  [{c.get('title','?')[:50]}] score={c.get('score',0):.4f}  {c.get('text','')[:80]}...")
            print()
            user_content = GENERATION_PROMPT.format(
                context_lettres=ctx_lettres,
                context_memoires=ctx_memoires,
                question=question,
            )
        else:
            memoir_chunks = []
            user_content = GENERATION_PROMPT_LETTERS_ONLY.format(
                context_lettres=ctx_lettres,
                question=question,
            )

        resp = client.chat.completions.create(
            model=args.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            max_tokens=512,
        )
        answer = resp.choices[0].message.content.strip()
        print(f"RÉPONSE NAPOLEON :\n{answer}")
        print()

        entry = {"messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ]}
        print(f"FORMAT SFT : {json.dumps(entry, ensure_ascii=False)[:200]}...")
        print()


# ---------------------------------------------------------------------------
# test-multiturn
# ---------------------------------------------------------------------------

def cmd_test_multiturn(args):
    key = load_env()
    from openai import OpenAI
    client = OpenAI(api_key=key)

    print(f"Chargement RAG lettres : {RAG_DB} ...")
    conn, emb_matrix, chunk_ids = load_rag_db(RAG_DB)
    memoir_db = load_memoir_db(MEMOIR_DB)
    if memoir_db:
        m_conn, m_matrix, m_ids = memoir_db
        print(f"Chargement RAG mémoires : {len(m_matrix)} vecteurs")
    else:
        m_conn = m_matrix = m_ids = None
    print()

    question = args.question or "Quel rôle as-tu joué lors du siège de Toulon ?"
    n_turns = args.turns

    q_vec = embed_texts(client, [question])[0]
    letter_chunks = query_rag(conn, emb_matrix, chunk_ids, q_vec, top_k=10)
    ctx_lettres = build_context_letters(letter_chunks)
    if m_conn is not None:
        memoir_chunks = query_memoir(m_conn, m_matrix, m_ids, q_vec, top_k=20)
        ctx_memoires = build_context_memoirs(memoir_chunks)
    else:
        ctx_memoires = "(aucun mémoire trouvé)"

    print(f"{'='*60}")
    print(f"QUESTION : {question}")
    print(f"{'='*60}\n")

    # Découper les lettres en segments par tour
    # Tour 1 reçoit les N premières lettres, tour 2 les suivantes, etc.
    letters_by_date = sorted(letter_chunks, key=lambda r: r.get("date_iso") or "9999")
    total = len(letters_by_date)
    per_turn = max(1, math.ceil(total / n_turns))
    segments = [letters_by_date[i:i + per_turn] for i in range(0, total, per_turn)]
    # S'assurer qu'on a exactement n_turns segments
    while len(segments) < n_turns:
        segments.append([])

    # Tour 1 : ouverture — seulement le premier segment de lettres
    ctx_tour1 = build_context_letters(segments[0]) if segments[0] else ctx_lettres
    first_prompt = GENERATION_PROMPT.format(
        context_lettres=ctx_tour1,
        context_memoires=ctx_memoires,
        question=question,
    ) if m_conn else GENERATION_PROMPT_LETTERS_ONLY.format(
        context_lettres=ctx_tour1,
        question=question,
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": first_prompt},
    ]

    for turn in range(1, n_turns + 1):
        resp = client.chat.completions.create(
            model=args.model,
            messages=messages,
            max_tokens=1024,
        )
        answer = resp.choices[0].message.content.strip()
        print(f"--- NAPOLÉON [tour {turn}] ---")
        print(answer)
        print()

        messages.append({"role": "assistant", "content": answer})

        if turn < n_turns:
            next_seg = segments[turn] if turn < len(segments) else []
            ctx_suite = build_context_letters(next_seg) if next_seg else "(toutes les lettres ont été couvertes)"

            user_followup = GENERATION_PROMPT_CONTINUATION.format(
                context_lettres_suite=ctx_suite,
                context_memoires=ctx_memoires,
            )
            messages.append({"role": "user", "content": user_followup})

            dates_in_seg = [c.get("date_iso", "?") for c in next_seg]
            print(f"--- UTILISATEUR [tour {turn}] ---")
            print(f"(continue — {len(next_seg)} nouvelles lettres : {dates_in_seg})")
            print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "submit", "status", "process", "test", "multiturn"])
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--question", default=None, help="Question custom pour le test")
    parser.add_argument("--turns", type=int, default=3, help="Nombre de tours pour multiturn")
    args = parser.parse_args()

    {
        "prepare": cmd_prepare,
        "submit": cmd_submit,
        "status": cmd_status,
        "process": cmd_process,
        "test": cmd_test,
        "multiturn": cmd_test_multiturn,
    }[args.command](args)


if __name__ == "__main__":
    main()
