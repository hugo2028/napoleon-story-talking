"""
Recherche Graph RAG par embeddings.

Usage:
  python3 pipeline/rag_query.py "Que pense Napoléon de Joséphine ?"
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import struct
import unicodedata
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT_DIR / "data" / "rag" / "napoleon_rag.sqlite"

DEFAULT_CHUNK_THRESHOLD = float(os.getenv("RAG_MIN_CHUNK_SCORE", "0.34"))
DEFAULT_QUESTION_THRESHOLD = float(os.getenv("RAG_MIN_QUESTION_SCORE", "0.42"))
INITIAL_CHUNK_CANDIDATES = 40
INITIAL_QUESTION_CANDIDATES = 30
GRAPH_EXPANSION_LIMIT = 80

QUERY_STOP_WORDS = {
    "a",
    "au",
    "aux",
    "avec",
    "ce",
    "ces",
    "comment",
    "dans",
    "de",
    "des",
    "dit",
    "du",
    "elle",
    "en",
    "est",
    "et",
    "il",
    "je",
    "la",
    "le",
    "les",
    "leur",
    "lui",
    "me",
    "mes",
    "mon",
    "napoleon",
    "ne",
    "nous",
    "ou",
    "par",
    "pas",
    "pense",
    "plus",
    "pour",
    "qu",
    "que",
    "quel",
    "quelle",
    "qui",
    "quoi",
    "ressent",
    "sont",
    "sur",
    "te",
    "ton",
    "tu",
    "un",
    "une",
    "vous",
    "votre",
}


def normalize_vector(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def unpack_vector(blob: bytes, dim: int) -> tuple[float, ...]:
    return struct.unpack(f"{dim}f", blob)


def cosine(left: list[float] | tuple[float, ...], right: list[float] | tuple[float, ...]) -> float:
    return sum(a * b for a, b in zip(left, right))


def normalize_text(text: str) -> str:
    without_accents = unicodedata.normalize("NFKD", text)
    return "".join(char for char in without_accents if not unicodedata.combining(char)).lower()


def tokenize_query(question: str) -> list[str]:
    normalized = normalize_text(question)
    tokens = re.findall(r"[a-z0-9]{2,}", normalized)
    terms = [token for token in tokens if token not in QUERY_STOP_WORDS]
    return list(dict.fromkeys(terms))


def numeric_terms(terms: list[str]) -> set[str]:
    return {term for term in terms if term.isdigit()}


def text_contains_terms(text: str, terms: set[str]) -> bool:
    if not terms:
        return True
    haystack = set(re.findall(r"[a-z0-9]{2,}", normalize_text(text)))
    return terms.issubset(haystack)


def hash_embedding(text: str, dim: int) -> list[float]:
    import hashlib

    vector = [0.0] * dim
    tokens = re.findall(r"[a-zA-ZÀ-ÖØ-öø-ÿ0-9]{3,}", text.lower())
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "little") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[bucket] += sign
    return normalize_vector(vector)


def read_meta(conn: sqlite3.Connection) -> dict[str, str]:
    try:
        rows = conn.execute("select key, value from rag_meta").fetchall()
    except sqlite3.OperationalError:
        return {}
    return {str(row[0]): str(row[1]) for row in rows}


def embed_query(question: str, provider: str, model: str, dim: int) -> list[float]:
    if provider == "hash":
        return hash_embedding(question, dim)

    load_dotenv(ROOT_DIR / ".env")
    api_key = os.getenv("EMBEDDING_API_KEY") or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("EMBEDDING_BASE_URL") or os.getenv("LLM_BASE_URL")
    if not api_key:
        raise RuntimeError("Aucune clé d'embeddings disponible pour interroger l'index Graph RAG.")

    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.embeddings.create(model=model, input=question)
    return normalize_vector(response.data[0].embedding)


def load_embeddings(conn: sqlite3.Connection, node_type: str) -> list[tuple[int, tuple[float, ...]]]:
    rows = conn.execute(
        "select node_id, dim, vector from embeddings where node_type = ?",
        (node_type,),
    ).fetchall()
    return [(int(row["node_id"]), unpack_vector(row["vector"], int(row["dim"]))) for row in rows]


def top_similar(
    query_vector: list[float],
    embeddings: list[tuple[int, tuple[float, ...]]],
    candidate_limit: int,
) -> list[tuple[int, float]]:
    scored = [(node_id, cosine(query_vector, vector)) for node_id, vector in embeddings]
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:candidate_limit]


def question_chunk_scores(conn: sqlite3.Connection, question_scores: list[tuple[int, float]]) -> dict[int, float]:
    if not question_scores:
        return {}
    question_ids = [qid for qid, _ in question_scores]
    placeholders = ",".join("?" for _ in question_ids)
    rows = conn.execute(
        f"select id, chunk_id from questions where id in ({placeholders})",
        question_ids,
    ).fetchall()
    score_by_question = dict(question_scores)
    scores: dict[int, float] = {}
    for row in rows:
        chunk_id = int(row["chunk_id"])
        score = score_by_question[int(row["id"])]
        scores[chunk_id] = max(scores.get(chunk_id, -1.0), score)
    return scores


def lexical_chunk_scores(conn: sqlite3.Connection, question: str) -> dict[int, float]:
    terms = tokenize_query(question)
    if not terms:
        return {}

    required_numbers = numeric_terms(terms)
    rows = conn.execute("select id, title, theme, text from chunks").fetchall()
    scores: dict[int, float] = {}
    for row in rows:
        searchable = normalize_text(" ".join([row["title"], row["theme"], row["text"]]))
        searchable_terms = set(re.findall(r"[a-z0-9]{2,}", searchable))
        if required_numbers and not required_numbers.issubset(searchable_terms):
            continue

        matched = [term for term in terms if term in searchable_terms]
        if not matched:
            continue

        match_ratio = len(matched) / len(terms)
        if len(terms) >= 3 and len(matched) < 2:
            continue

        phrase_bonus = 0.0
        for left, right in zip(terms, terms[1:]):
            phrase_bonus += min(searchable.count(f"{left} {right}") * 0.045, 0.12)

        frequency_bonus = 0.0
        for term in matched:
            frequency_bonus += min(searchable.count(term) * 0.012, 0.06)

        scores[int(row["id"])] = 0.28 + (match_ratio * 0.25) + min(phrase_bonus, 0.14) + min(frequency_bonus, 0.12)
    return scores


def filter_numeric_mismatch(conn: sqlite3.Connection, scores: dict[int, float], question: str) -> dict[int, float]:
    required_numbers = numeric_terms(tokenize_query(question))
    if not required_numbers or not scores:
        return scores

    chunk_ids = list(scores)
    placeholders = ",".join("?" for _ in chunk_ids)
    rows = conn.execute(
        f"select id, title, theme, text from chunks where id in ({placeholders})",
        chunk_ids,
    ).fetchall()
    allowed_ids = {
        int(row["id"])
        for row in rows
        if text_contains_terms(" ".join([row["title"], row["theme"], row["text"]]), required_numbers)
    }
    return {chunk_id: score for chunk_id, score in scores.items() if chunk_id in allowed_ids}


def expand_graph(conn: sqlite3.Connection, seed_scores: dict[int, float]) -> dict[int, float]:
    expanded = dict(seed_scores)
    frontier = sorted(seed_scores.items(), key=lambda item: item[1], reverse=True)[:GRAPH_EXPANSION_LIMIT]
    for chunk_id, seed_score in frontier:
        rows = conn.execute(
            """
            select target_type, target_id, relation, weight
            from graph_edges
            where source_type = 'chunk' and source_id = ?
            """,
            (chunk_id,),
        ).fetchall()
        for edge in rows:
            target_type = edge["target_type"]
            target_id = int(edge["target_id"])
            relation = edge["relation"]
            weight = float(edge["weight"])

            if target_type == "chunk":
                expanded[target_id] = max(expanded.get(target_id, -1.0), seed_score * weight * 0.82)
                continue

            if target_type != "entity":
                continue

            neighbor_rows = conn.execute(
                """
                select target_id, weight
                from graph_edges
                where source_type = 'entity'
                  and source_id = ?
                  and target_type = 'chunk'
                limit 24
                """,
                (target_id,),
            ).fetchall()
            entity_factor = 0.68 if relation == "has_theme" else 0.52
            for neighbor in neighbor_rows:
                neighbor_id = int(neighbor["target_id"])
                neighbor_score = seed_score * weight * float(neighbor["weight"]) * entity_factor
                expanded[neighbor_id] = max(expanded.get(neighbor_id, -1.0), neighbor_score)
    return expanded


def fetch_chunks(conn: sqlite3.Connection, scores: dict[int, float], limit: int) -> list[dict]:
    if not scores:
        return []
    chunk_ids = list(scores)
    placeholders = ",".join("?" for _ in chunk_ids)
    rows = conn.execute(
        f"""
        select id, title, source_path, language, chunk_index, theme, text
        from chunks
        where id in ({placeholders})
        """,
        chunk_ids,
    ).fetchall()

    results = []
    for row in rows:
        score = scores[int(row["id"])]
        language_bonus = 0.035 if row["language"] == "fr" else 0.0
        results.append(
            {
                "id": int(row["id"]),
                "title": row["title"],
                "source_path": row["source_path"],
                "language": row["language"],
                "chunk_index": int(row["chunk_index"]),
                "theme": row["theme"],
                "score": score + language_bonus,
                "text": row["text"],
            }
        )

    results.sort(key=lambda item: item["score"], reverse=True)
    return results[:limit]


def search(question: str, db_path: Path = DEFAULT_DB_PATH, limit: int = 6) -> list[dict]:
    if not db_path.exists() or not question.strip():
        return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        meta = read_meta(conn)
        if meta.get("schema") != "graph-rag-v1":
            return []

        provider = meta.get("embedding_provider", "openai")
        model = meta.get("embedding_model", "text-embedding-3-small")
        dim = int(meta.get("embedding_dim", "0"))
        if dim <= 0:
            return []

        query_vector = embed_query(question, provider, model, dim)
        chunk_scores = top_similar(query_vector, load_embeddings(conn, "chunk"), INITIAL_CHUNK_CANDIDATES)
        question_scores = top_similar(query_vector, load_embeddings(conn, "question"), INITIAL_QUESTION_CANDIDATES)
        lexical_scores = lexical_chunk_scores(conn, question)

        strong_chunks = {
            chunk_id: score
            for chunk_id, score in chunk_scores
            if score >= DEFAULT_CHUNK_THRESHOLD
        }
        strong_question_chunks = {
            chunk_id: score
            for chunk_id, score in question_chunk_scores(conn, question_scores).items()
            if score >= DEFAULT_QUESTION_THRESHOLD
        }
        strong_lexical_chunks = {
            chunk_id: score
            for chunk_id, score in lexical_scores.items()
            if score >= DEFAULT_CHUNK_THRESHOLD
        }

        if not strong_chunks and not strong_question_chunks and not strong_lexical_chunks:
            return []

        seed_scores = dict(strong_chunks)
        for chunk_id, score in strong_question_chunks.items():
            seed_scores[chunk_id] = max(seed_scores.get(chunk_id, -1.0), score)
        for chunk_id, score in strong_lexical_chunks.items():
            seed_scores[chunk_id] = max(seed_scores.get(chunk_id, -1.0), score)
        seed_scores = filter_numeric_mismatch(conn, seed_scores, question)
        if not seed_scores:
            return []

        expanded_scores = expand_graph(conn, seed_scores)
        expanded_scores = filter_numeric_mismatch(conn, expanded_scores, question)
        floor = min(DEFAULT_CHUNK_THRESHOLD, DEFAULT_QUESTION_THRESHOLD) * 0.72
        filtered_scores = {
            chunk_id: score
            for chunk_id, score in expanded_scores.items()
            if score >= floor
        }
        return fetch_chunks(conn, filtered_scores, limit)
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Chercher dans la base Graph RAG.")
    parser.add_argument("question")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Chemin de la base SQLite")
    parser.add_argument("--limit", type=int, default=6)
    args = parser.parse_args()
    print(json.dumps(search(args.question, Path(args.db), args.limit), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
