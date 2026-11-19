"""
Construit une base Graph RAG SQLite à partir des livres.

Le graphe contient :
- des documents ;
- des passages chunkés ;
- des questions candidates pour chaque passage ;
- des entités/thèmes reliés aux passages ;
- des embeddings pour les passages et les questions.

Usage:
  python3 pipeline/rag_index.py
  python3 pipeline/rag_index.py --embedding-provider openai
  python3 pipeline/rag_index.py --embedding-provider hash  # secours local sans API
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import struct
import time
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup
from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_DIR = ROOT_DIR / "napoleon-corpus" / "sources"
DEFAULT_DB_PATH = ROOT_DIR / "data" / "rag" / "napoleon_rag.sqlite"

CHUNK_WORDS = 260
CHUNK_OVERLAP = 55
MIN_CHUNK_WORDS = 55
QUESTION_LIMIT_PER_CHUNK = 3
HASH_EMBEDDING_DIM = 384
OPENAI_BATCH_SIZE = 96

FRENCH_HINTS = {
    "le",
    "la",
    "les",
    "des",
    "une",
    "dans",
    "pour",
    "avec",
    "vous",
    "nous",
    "était",
    "être",
    "empereur",
    "armée",
    "france",
    "français",
    "monsieur",
    "citoyen",
}

ENGLISH_HINTS = {
    "the",
    "and",
    "with",
    "that",
    "this",
    "from",
    "were",
    "will",
    "shall",
    "emperor",
    "army",
    "french",
}

THEME_RULES = [
    (r"joséphine|josephine|marie-louise|famille|mariage|femme|fils", "famille"),
    (r"code civil|loi|constitution|sénat|conseil d'état|gouvernement|administration", "réformes"),
    (r"armée|bataille|campagne|victoire|défaite|guerre|soldats|maréchal", "guerre"),
    (r"traité|paix|alliance|ambassadeur|angleterre|autriche|russie|prusse", "diplomatie"),
    (r"sainte-hélène|exil|captivité|longwood|hudson lowe", "exil"),
    (r"égypte|pyramides|orient|nil|mameluk", "égypte"),
]

STOP_ENTITIES = {
    "ART",
    "CHAPITRE",
    "Citoyen",
    "Citoyens",
    "Correspondance",
    "Empire",
    "Empereur",
    "France",
    "Français",
    "Gouvernement",
    "Monsieur",
    "Napoléon",
    "Paris",
    "République",
    "Sire",
    "Tome",
}


@dataclass
class Document:
    title: str
    path: Path
    language: str
    text: str


@dataclass
class EmbeddingItem:
    kind: str
    row_id: int
    text: str


def clean_text(text: str) -> str:
    text = re.sub(r"\[[0-9]+\]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_vector(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def pack_vector(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


def hash_embedding(text: str, dim: int = HASH_EMBEDDING_DIM) -> list[float]:
    vector = [0.0] * dim
    tokens = re.findall(r"[a-zA-ZÀ-ÖØ-öø-ÿ0-9]{3,}", text.lower())
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "little") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[bucket] += sign
    return normalize_vector(vector)


def embed_texts(texts: list[str], provider: str, model: str) -> tuple[list[list[float]], str, int]:
    if provider == "hash":
        return [hash_embedding(text) for text in texts], "hash-local-v1", HASH_EMBEDDING_DIM

    load_dotenv(ROOT_DIR / ".env")
    api_key = os.getenv("EMBEDDING_API_KEY") or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("EMBEDDING_BASE_URL") or os.getenv("LLM_BASE_URL")
    if not api_key:
        raise RuntimeError(
            "Aucune clé d'embeddings trouvée. Définissez EMBEDDING_API_KEY ou LLM_API_KEY, "
            "ou lancez avec --embedding-provider hash pour un index local de secours."
        )

    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url)
    embeddings: list[list[float]] = []
    for start in range(0, len(texts), OPENAI_BATCH_SIZE):
        batch = texts[start : start + OPENAI_BATCH_SIZE]
        response = client.embeddings.create(model=model, input=batch)
        embeddings.extend([item.embedding for item in response.data])
        time.sleep(0.05)

    dim = len(embeddings[0]) if embeddings else 0
    return [normalize_vector(vector) for vector in embeddings], model, dim


def detect_language(text: str, path: Path) -> str:
    haystack = f"{path.as_posix()} {text[:6000]}".lower()
    french_score = sum(len(re.findall(rf"\b{re.escape(word)}\b", haystack)) for word in FRENCH_HINTS)
    english_score = sum(len(re.findall(rf"\b{re.escape(word)}\b", haystack)) for word in ENGLISH_HINTS)
    return "fr" if french_score >= english_score else "en"


def read_html(path: Path) -> tuple[str, str]:
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="ignore"), "lxml")
    for tag in soup.select("#pg-header, #pg-footer, .pgheader, .pgfooter, script, style, nav"):
        tag.decompose()

    title = ""
    if soup.title and soup.title.get_text(strip=True):
        title = soup.title.get_text(" ", strip=True)
    if not title:
        heading = soup.find(["h1", "h2"])
        title = heading.get_text(" ", strip=True) if heading else path.parent.name

    blocks: list[str] = []
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "p", "blockquote", "li"]):
        text = clean_text(tag.get_text(" ", strip=True))
        if len(text) >= 30 and not re.fullmatch(r"\d+", text):
            blocks.append(text)
    return clean_text(title), clean_text("\n".join(blocks))


def read_text(path: Path) -> tuple[str, str]:
    text = clean_text(path.read_text(encoding="utf-8", errors="ignore"))
    return path.stem, text


def iter_documents(source_dir: Path) -> list[Document]:
    docs: list[Document] = []
    for path in sorted(source_dir.rglob("*")):
        if path.suffix.lower() not in {".html", ".htm", ".txt"}:
            continue
        title, text = read_html(path) if path.suffix.lower() in {".html", ".htm"} else read_text(path)
        if len(text.split()) < MIN_CHUNK_WORDS:
            continue
        docs.append(Document(title=title, path=path, language=detect_language(text, path), text=text))
    return docs


def chunk_text(text: str) -> list[str]:
    words = text.split()
    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + CHUNK_WORDS, len(words))
        chunk = " ".join(words[start:end]).strip()
        if len(chunk.split()) >= MIN_CHUNK_WORDS:
            chunks.append(chunk)
        if end == len(words):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def detect_theme(text: str) -> str:
    lower = text.lower()
    for pattern, theme in THEME_RULES:
        if re.search(pattern, lower):
            return theme
    return "général"


def extract_entities(text: str, limit: int = 8) -> list[str]:
    candidates = re.findall(r"\b[A-ZÉÈÀÂÊÎÔÛÄËÏÖÜÇ][A-Za-zÀ-ÖØ-öø-ÿ'’-]{3,}(?:\s+[A-ZÉÈÀÂÊÎÔÛÄËÏÖÜÇ][A-Za-zÀ-ÖØ-öø-ÿ'’-]{2,})?", text)
    counts: dict[str, int] = {}
    for candidate in candidates:
        entity = clean_text(candidate).strip(" .,:;!?")
        if entity in STOP_ENTITIES or entity.isupper() or len(entity) < 4:
            continue
        counts[entity] = counts.get(entity, 0) + 1
    return [entity for entity, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def generate_questions(title: str, text: str) -> list[str]:
    theme = detect_theme(text)
    entities = extract_entities(text, limit=4)
    questions = [
        f"Que dit ce passage sur {theme} ?",
        f"Quels faits importants apparaissent dans {title} ?",
    ]
    for entity in entities:
        questions.append(f"Quel rôle joue {entity} dans ce passage ?")
    return list(dict.fromkeys(questions))[:QUESTION_LIMIT_PER_CHUNK]


def init_db(conn: sqlite3.Connection, embedding_model: str, embedding_dim: int, provider: str) -> None:
    conn.executescript(
        """
        drop table if exists graph_edges;
        drop table if exists embeddings;
        drop table if exists questions;
        drop table if exists entities;
        drop table if exists chunks;
        drop table if exists documents;
        drop table if exists rag_meta;

        create table rag_meta (
          key text primary key,
          value text not null
        );

        create table documents (
          id integer primary key,
          title text not null,
          path text not null unique,
          language text not null,
          content_hash text not null
        );

        create table chunks (
          id integer primary key,
          document_id integer not null references documents(id) on delete cascade,
          chunk_index integer not null,
          language text not null,
          title text not null,
          source_path text not null,
          theme text not null,
          text text not null
        );

        create table questions (
          id integer primary key,
          chunk_id integer not null references chunks(id) on delete cascade,
          question text not null
        );

        create table entities (
          id integer primary key,
          name text not null unique,
          kind text not null
        );

        create table embeddings (
          node_type text not null,
          node_id integer not null,
          model text not null,
          dim integer not null,
          vector blob not null,
          primary key (node_type, node_id)
        );

        create table graph_edges (
          source_type text not null,
          source_id integer not null,
          target_type text not null,
          target_id integer not null,
          relation text not null,
          weight real not null,
          primary key (source_type, source_id, target_type, target_id, relation)
        );

        create index idx_chunks_document on chunks(document_id);
        create index idx_chunks_language on chunks(language);
        create index idx_questions_chunk on questions(chunk_id);
        create index idx_edges_source on graph_edges(source_type, source_id);
        create index idx_edges_target on graph_edges(target_type, target_id);
        """
    )
    conn.executemany(
        "insert into rag_meta(key, value) values (?, ?)",
        [
            ("schema", "graph-rag-v1"),
            ("embedding_provider", provider),
            ("embedding_model", embedding_model),
            ("embedding_dim", str(embedding_dim)),
        ],
    )


def insert_edge(
    conn: sqlite3.Connection,
    source_type: str,
    source_id: int,
    target_type: str,
    target_id: int,
    relation: str,
    weight: float,
) -> None:
    conn.execute(
        """
        insert or replace into graph_edges(source_type, source_id, target_type, target_id, relation, weight)
        values (?, ?, ?, ?, ?, ?)
        """,
        (source_type, source_id, target_type, target_id, relation, weight),
    )


def add_entity(conn: sqlite3.Connection, name: str, kind: str = "entity") -> int:
    conn.execute("insert or ignore into entities(name, kind) values (?, ?)", (name, kind))
    row = conn.execute("select id from entities where name = ?", (name,)).fetchone()
    return int(row[0])


def build_index(source_dir: Path, db_path: Path, embedding_provider: str = "openai", embedding_model: str = "text-embedding-3-small") -> None:
    docs = iter_documents(source_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    items: list[EmbeddingItem] = []
    conn = sqlite3.connect(db_path)
    try:
        init_db(conn, embedding_model, 0, embedding_provider)
        chunk_count = 0
        question_count = 0
        entity_names: set[str] = set()

        for doc in docs:
            content_hash = hashlib.sha256(doc.text.encode("utf-8")).hexdigest()
            cursor = conn.execute(
                "insert into documents(title, path, language, content_hash) values (?, ?, ?, ?)",
                (doc.title, str(doc.path.relative_to(ROOT_DIR)), doc.language, content_hash),
            )
            document_id = int(cursor.lastrowid)
            previous_chunk_id: int | None = None

            for chunk_index, chunk in enumerate(chunk_text(doc.text)):
                theme = detect_theme(chunk)
                cursor = conn.execute(
                    """
                    insert into chunks(document_id, chunk_index, language, title, source_path, theme, text)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        chunk_index,
                        doc.language,
                        doc.title,
                        str(doc.path.relative_to(ROOT_DIR)),
                        theme,
                        chunk,
                    ),
                )
                chunk_id = int(cursor.lastrowid)
                items.append(EmbeddingItem("chunk", chunk_id, f"{doc.title}\n{theme}\n{chunk}"))
                chunk_count += 1

                if previous_chunk_id is not None:
                    insert_edge(conn, "chunk", previous_chunk_id, "chunk", chunk_id, "next", 0.55)
                    insert_edge(conn, "chunk", chunk_id, "chunk", previous_chunk_id, "previous", 0.55)
                previous_chunk_id = chunk_id

                theme_id = add_entity(conn, theme, "theme")
                entity_names.add(theme)
                insert_edge(conn, "chunk", chunk_id, "entity", theme_id, "has_theme", 0.75)
                insert_edge(conn, "entity", theme_id, "chunk", chunk_id, "theme_of", 0.75)

                for entity in extract_entities(chunk):
                    entity_id = add_entity(conn, entity, "person_or_place")
                    entity_names.add(entity)
                    insert_edge(conn, "chunk", chunk_id, "entity", entity_id, "mentions", 0.65)
                    insert_edge(conn, "entity", entity_id, "chunk", chunk_id, "mentioned_in", 0.65)

                for question in generate_questions(doc.title, chunk):
                    cursor = conn.execute("insert into questions(chunk_id, question) values (?, ?)", (chunk_id, question))
                    question_id = int(cursor.lastrowid)
                    items.append(EmbeddingItem("question", question_id, question))
                    insert_edge(conn, "question", question_id, "chunk", chunk_id, "answers_with", 0.9)
                    insert_edge(conn, "chunk", chunk_id, "question", question_id, "has_question", 0.9)
                    question_count += 1

        conn.commit()

        print(f"Calcul embeddings: {len(items)} noeuds ({embedding_provider})...")
        vectors, actual_model, dim = embed_texts([item.text for item in items], embedding_provider, embedding_model)
        conn.execute("update rag_meta set value = ? where key = 'embedding_model'", (actual_model,))
        conn.execute("update rag_meta set value = ? where key = 'embedding_dim'", (str(dim),))
        for item, vector in zip(items, vectors):
            conn.execute(
                "insert into embeddings(node_type, node_id, model, dim, vector) values (?, ?, ?, ?, ?)",
                (item.kind, item.row_id, actual_model, dim, pack_vector(vector)),
            )
        conn.commit()
    finally:
        conn.close()

    languages: dict[str, int] = {}
    for doc in docs:
        languages[doc.language] = languages.get(doc.language, 0) + 1

    print(f"Base Graph RAG créée: {db_path}")
    print(f"Documents indexés: {len(docs)}")
    print(f"Passages indexés: {chunk_count}")
    print(f"Questions indexées: {question_count}")
    print(f"Entités/thèmes indexés: {len(entity_names)}")
    print("Langues:", ", ".join(f"{lang}={count}" for lang, count in sorted(languages.items())))


def main() -> None:
    parser = argparse.ArgumentParser(description="Indexer les livres dans une base Graph RAG SQLite.")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE_DIR), help="Dossier contenant les livres")
    parser.add_argument("--output", default=str(DEFAULT_DB_PATH), help="Chemin de la base SQLite")
    parser.add_argument(
        "--embedding-provider",
        choices=["openai", "hash"],
        default=os.getenv("EMBEDDING_PROVIDER", "openai"),
        help="Provider d'embeddings. openai recommandé, hash utile pour tester sans API.",
    )
    parser.add_argument(
        "--embedding-model",
        default=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
        help="Modèle d'embedding utilisé avec --embedding-provider openai.",
    )
    args = parser.parse_args()
    build_index(Path(args.source), Path(args.output), args.embedding_provider, args.embedding_model)


if __name__ == "__main__":
    main()
