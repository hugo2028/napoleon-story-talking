"""
Exporte les pools de données depuis napoleon-corpus selon une source policy.

Entrées :
  napoleon-corpus/metadata/manifest.jsonl
  napoleon-corpus/cleaned/*/*.jsonl
  napoleon-corpus/metadata/source_policy.json

Sorties :
  napoleon-corpus/datasets/cpt/corpus.jsonl
  napoleon-corpus/datasets/cpt/corpus.txt
  napoleon-corpus/datasets/cpt/corpus.raw.jsonl
  napoleon-corpus/datasets/cpt/corpus.raw.txt
  napoleon-corpus/datasets/sft/source_chunks.jsonl
  napoleon-corpus/datasets/rag/chunks.jsonl
"""

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).parent.parent
CORPUS_DIR = ROOT / "napoleon-corpus"
MANIFEST_PATH = CORPUS_DIR / "metadata" / "manifest.jsonl"
POLICY_PATH = CORPUS_DIR / "metadata" / "source_policy.json"

BOILERPLATE_RE = re.compile(
    r"(Rappel de votre demande|Format de t[ée]l[ée]chargement|"
    r"Notice du catalogue|Notice compl[èe]te|Conservation num[ée]rique|"
    r"Vues\s+\d+\s+[aà]\s+\d+|Project Gutenberg|START OF THE PROJECT|END OF THE PROJECT)",
    re.IGNORECASE,
)

EDITORIAL_RE = re.compile(
    r"^(Footnote|Note\s+\d+|Lecteur,|Voir r[ée]unies|Il a [ée]t[ée] tir[ée]|"
    r"Napol[ée]on Bonaparte n'existe plus|Nous publierons|On nous le peint|"
    r"Napol[ée]on Bonaparte est n[ée]|PARIS IMPRIMERIE|Chez [A-Z]|"
    r"Les Campagnes d'Italie.*peuvent entrer|Ses projets, ses victoires)",
    re.IGNORECASE,
)

FOOTNOTE_RE = re.compile(r"\b(Footnote|Note de l'[ée]diteur|note de bas de page)\b", re.IGNORECASE)

NON_NAPOLEON_SOURCE_TYPES = {"source", "jeunesse"}
SAFE_CPT_SOURCE_TYPES = {"correspondance", "lettres-amour-imperiales", "proclamations"}
BOOK_CPT_SOURCE_TYPES = {"memoires-proches", "campagnes", "bulletins"}
TERMINAL_PUNCTUATION = {".", "!", "?", "»"}
BOOK_TERMINAL_PUNCTUATION = {".", "!", "?", "»", ";"}
VALID_START_RE = re.compile(r"^[A-ZÀÂÄÇÉÈÊËÎÏÔÖÙÛÜŸ0-9«\"(]")
LOWER = "a-zàâäçéèêëîïôöùûüÿæœ"
UPPER = "A-ZÀÂÄÇÉÈÊËÎÏÔÖÙÛÜŸÆŒ"
INTERNAL_CAPS_RE = re.compile(rf"\b[{LOWER}]+[{UPPER}][{LOWER}{UPPER}]*\b")
ALNUM_TOKEN_RE = re.compile(rf"\b[{LOWER}{UPPER}]*\d+[{LOWER}{UPPER}]+\b|\b[{LOWER}{UPPER}]+\d+[{LOWER}{UPPER}]*\b")
VALID_ORDINAL_RE = re.compile(r"^\d+(?:er|e|es)$", re.IGNORECASE)
WEIRD_SYMBOL_IN_WORD_RE = re.compile(rf"\b[{LOWER}{UPPER}]+[\\^~&\][\"*/][{LOWER}{UPPER}]+\b")
SINGLE_LETTER_RUN_RE = re.compile(r"(?:\b[A-Za-zÀ-ÿ]\b[\s,;:.!?-]+){4,}")
SPACED_APOSTROPHE_RE = re.compile(r"\b[ldjmstcnLDJMSTCN] ['’]")
BAD_DOUBLE_PUNCT_RE = re.compile(r"(\.\.|,,|,,|,\.|\.,|;;|::|!!|\?\?|\?\.|!\.)")
LINK_RE = re.compile(r"(https?://|www\.|gallica\.bnf\.fr|gutenberg\.org|ark:/)", re.IGNORECASE)
BULLETIN_START_RE = re.compile(r"^[A-ZÀÂÄÇÉÈÊËÎÏÔÖÙÛÜŸ]")
BULLETIN_DOCUMENT_START_RE = re.compile(
    r"^(AU|AUX|À|LE|LA|LES|ORDRE|PROCLAMATION|RAPPORT|BULLETIN|"
    r"ARM[ÉE]E|QUARTIER|SOLDATS|CITOYENS|MONITEUR|«)",
    re.IGNORECASE,
)
OCR_SYMBOL_RE = re.compile(r"[\^~&\\\[\]*]")
OCR_GARBAGE_RE = re.compile(r"^[A-ZÀ-Ü0-9\s®©™)(';:!\".,\-/]+$")
OCR_DENSE_SYMBOL_RE = re.compile(r"[®©™]|(?:[)\(';:!\".,\-/]\s*){5,}")
THIRD_PERSON_BIO_RE = re.compile(
    r"\b(napol[ée]on|bonaparte)\s+(est|était|fut|devint|avait|naquit|mourut|"
    r"arriva|servit|embrassa|conserva|donna|passa|écrivit)\b",
    re.IGNORECASE,
)
BOOK_EDITORIAL_VOICE_RE = re.compile(
    r"\b(l'auteur|le lecteur|cet ouvrage|ce volume|nous publierons|on nous le peint|"
    r"nous donnons|cette notice|notice biographique)\b",
    re.IGNORECASE,
)
LOWER_SENTENCE_AFTER_DOT_RE = re.compile(
    rf"(?<!\bM)(?<!\bMM)(?<!\bMme)(?<!\bMlle)(?<!\bS)(?<!\betc)"
    rf"(?<=[.!?])\s+[\"'’«(]*[{LOWER}]"
)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_cleaned_by_id(manifest: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_id = {}
    paths = sorted({CORPUS_DIR / row["text_path"] for row in manifest})
    for path in paths:
        if not path.exists():
            continue
        for row in load_jsonl(path):
            by_id[row["id"]] = row
    return by_id


def selected(row: dict[str, Any], policy: dict[str, Any]) -> bool:
    include = set(policy.get("include_source_types") or [])
    exclude = set(policy.get("exclude_source_types") or [])
    source_type = row.get("source_type")

    if include and source_type not in include:
        return False
    if source_type in exclude:
        return False
    if policy.get("require_date") and not row.get("date"):
        return False
    if int(row.get("word_count") or 0) < int(policy.get("min_words") or 0):
        return False
    return True


def build_pool(
    manifest: list[dict[str, Any]],
    cleaned_by_id: dict[str, dict[str, Any]],
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = []
    for meta in manifest:
        if not selected(meta, policy):
            continue
        cleaned = cleaned_by_id.get(meta["id"])
        if not cleaned:
            continue
        rows.append({
            "id": meta["id"],
            "title": meta.get("title"),
            "author": meta.get("author"),
            "date": meta.get("date"),
            "period": meta.get("period"),
            "theme": meta.get("theme"),
            "source_type": meta.get("source_type"),
            "reliability": meta.get("reliability"),
            "language": meta.get("language"),
            "rights": meta.get("rights"),
            "source_file": meta.get("source_file"),
            "word_count": meta.get("word_count"),
            "text": cleaned.get("text", ""),
        })
    return rows


def cpt_keep(row: dict[str, Any]) -> tuple[bool, str | None]:
    text = (row.get("text") or "").strip()
    if row.get("source_type") not in SAFE_CPT_SOURCE_TYPES:
        return False, "not_strict_primary_source"
    if row.get("source_type") in NON_NAPOLEON_SOURCE_TYPES:
        return False, "non_napoleon_source_type"
    return cpt_text_quality_keep(row, text)


def cpt_books_keep(row: dict[str, Any]) -> tuple[bool, str | None]:
    if row.get("source_type") not in BOOK_CPT_SOURCE_TYPES:
        return False, "not_book_source"

    text = (row.get("text") or "").strip()
    if row.get("source_type") == "bulletins":
        keep, reason = cpt_text_quality_keep(row, text, min_words=100, terminal_punctuation={"."})
        if not keep:
            return False, reason
        if not BULLETIN_START_RE.match(text):
            return False, "bulletin_bad_start"
        if row.get("title") == "Introduction" and not BULLETIN_DOCUMENT_START_RE.match(text):
            return False, "book_introduction"
        if LINK_RE.search(text):
            return False, "link"
        if OCR_SYMBOL_RE.search(text):
            return False, "ocr_symbol"
        if THIRD_PERSON_BIO_RE.search(text):
            return False, "third_person_biography"
        if BOOK_EDITORIAL_VOICE_RE.search(text):
            return False, "book_editorial_voice"
        return True, None

    keep, reason = cpt_text_quality_keep(row, text)
    if not keep:
        return False, reason

    lower_text = text.lower()
    if row.get("title") == "Introduction":
        return False, "book_introduction"
    if THIRD_PERSON_BIO_RE.search(lower_text):
        return False, "third_person_biography"
    if BOOK_EDITORIAL_VOICE_RE.search(lower_text):
        return False, "book_editorial_voice"
    return True, None


def merge_book_rows(rows: list[dict[str, Any]], max_words: int = 260) -> list[dict[str, Any]]:
    book_rows = [row for row in rows if row.get("source_type") in BOOK_CPT_SOURCE_TYPES]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in book_rows:
        grouped.setdefault(str(row.get("source_file")), []).append(row)

    merged_rows: list[dict[str, Any]] = []
    for _, source_rows in sorted(grouped.items()):
        source_rows = sorted(source_rows, key=lambda row: row.get("id", ""))
        buffer: list[dict[str, Any]] = []
        words = 0

        def flush() -> None:
            nonlocal buffer, words
            if not buffer:
                return
            text = " ".join((row.get("text") or "").strip() for row in buffer if (row.get("text") or "").strip())
            text = re.sub(r"\s+", " ", text).strip()
            first = buffer[0]
            last = buffer[-1]
            merged = dict(first)
            merged["id"] = first["id"] if first["id"] == last["id"] else f"{first['id']}__{last['id']}"
            merged["text"] = text
            merged["word_count"] = len(text.split())
            merged["merged_ids"] = [row["id"] for row in buffer]
            merged_rows.append(merged)
            buffer = []
            words = 0

        for row in source_rows:
            text = (row.get("text") or "").strip()
            if not text:
                continue
            if not buffer and not VALID_START_RE.match(text):
                continue
            buffer.append(row)
            words += len(text.split())
            if text[-1] in BOOK_TERMINAL_PUNCTUATION and words >= 100:
                flush()
            elif words >= max_words:
                flush()
        flush()

    return merged_rows


def cpt_text_quality_keep(
    row: dict[str, Any],
    text: str,
    min_words: int = 40,
    terminal_punctuation: set[str] | None = None,
) -> tuple[bool, str | None]:
    if not text:
        return False, "empty"
    if int(row.get("word_count") or 0) < min_words:
        return False, "too_short"
    if text.endswith(("...", "…")) or "..." in text or "…" in text:
        return False, "ellipsis"
    if not VALID_START_RE.match(text):
        return False, "fragment_start"
    terminals = terminal_punctuation or TERMINAL_PUNCTUATION
    if text[-1] not in terminals:
        return False, "truncated_sentence"
    if LOWER_SENTENCE_AFTER_DOT_RE.search(text):
        return False, "sentence_not_capitalized"
    if WEIRD_SYMBOL_IN_WORD_RE.search(text):
        return False, "ocr_symbol_in_word"
    if OCR_GARBAGE_RE.match(text[:120]) or OCR_DENSE_SYMBOL_RE.search(text[:160]):
        return False, "ocr_garbage"
    if INTERNAL_CAPS_RE.search(text):
        return False, "ocr_internal_caps"
    if SINGLE_LETTER_RUN_RE.search(text):
        return False, "ocr_spaced_letters"
    if SPACED_APOSTROPHE_RE.search(text):
        return False, "ocr_spaced_apostrophe"
    if BAD_DOUBLE_PUNCT_RE.search(text):
        return False, "ocr_bad_punctuation"
    for match in ALNUM_TOKEN_RE.finditer(text):
        token = match.group(0)
        if not VALID_ORDINAL_RE.match(token):
            return False, "ocr_digit_in_word"
    if BOILERPLATE_RE.search(text):
        return False, "boilerplate_metadata"
    if FOOTNOTE_RE.search(text):
        return False, "footnote"
    if EDITORIAL_RE.search(text):
        return False, "editorial_or_preface"
    if text.lower().startswith(("préface", "preface", "introduction")):
        return False, "preface"
    return True, None


def write_cpt(rows: list[dict[str, Any]]) -> None:
    output_jsonl = CORPUS_DIR / "datasets" / "cpt" / "corpus.jsonl"
    output_txt = CORPUS_DIR / "datasets" / "cpt" / "corpus.txt"
    output_raw_jsonl = CORPUS_DIR / "datasets" / "cpt" / "corpus.raw.jsonl"
    output_raw_txt = CORPUS_DIR / "datasets" / "cpt" / "corpus.raw.txt"
    output_books_jsonl = CORPUS_DIR / "datasets" / "cpt" / "books_safe.jsonl"
    output_books_txt = CORPUS_DIR / "datasets" / "cpt" / "books_safe.raw.txt"
    output_books_raw_jsonl = CORPUS_DIR / "datasets" / "cpt" / "books_safe.raw.jsonl"
    output_combined_txt = CORPUS_DIR / "datasets" / "cpt" / "combined_safe.raw.txt"
    output_combined_jsonl = CORPUS_DIR / "datasets" / "cpt" / "combined_safe.raw.jsonl"
    output_excluded = CORPUS_DIR / "datasets" / "cpt" / "excluded.jsonl"
    output_books_excluded = CORPUS_DIR / "datasets" / "cpt" / "books_excluded.jsonl"

    kept_rows = []
    excluded_rows = []
    for row in rows:
        keep, reason = cpt_keep(row)
        if keep:
            kept_rows.append(row)
        else:
            excluded = dict(row)
            excluded["exclude_reason"] = reason
            excluded_rows.append(excluded)

    books_rows = []
    books_excluded_rows = []
    for row in merge_book_rows(rows):
        books_keep, books_reason = cpt_books_keep(row)
        if books_keep:
            books_rows.append(row)
        else:
            excluded = dict(row)
            excluded["exclude_reason"] = books_reason
            books_excluded_rows.append(excluded)

    write_jsonl(output_jsonl, kept_rows)
    write_jsonl(output_excluded, excluded_rows)
    write_jsonl(output_raw_jsonl, [{"text": row["text"].strip()} for row in kept_rows if row["text"].strip()])
    write_jsonl(output_books_jsonl, books_rows)
    write_jsonl(output_books_excluded, books_excluded_rows)
    write_jsonl(output_books_raw_jsonl, [{"text": row["text"].strip()} for row in books_rows if row["text"].strip()])
    write_jsonl(output_combined_jsonl, [{"text": row["text"].strip()} for row in (kept_rows + books_rows) if row["text"].strip()])

    output_txt.parent.mkdir(parents=True, exist_ok=True)
    with open(output_txt, "w", encoding="utf-8") as f:
        for row in kept_rows:
            header = f"### {row['title']}"
            if row.get("date"):
                header += f" ({row['date']})"
            f.write(header + "\n")
            f.write(row["text"].strip() + "\n\n")

    with open(output_raw_txt, "w", encoding="utf-8") as f:
        current_source = None
        for row in kept_rows:
            text = row["text"].strip()
            if not text:
                continue
            if row.get("source_file") != current_source:
                current_source = row.get("source_file")
                f.write("\n\n")
            f.write(text + "\n\n")

    with open(output_books_txt, "w", encoding="utf-8") as f:
        current_source = None
        for row in books_rows:
            text = row["text"].strip()
            if not text:
                continue
            if row.get("source_file") != current_source:
                current_source = row.get("source_file")
                f.write("\n\n")
            f.write(text + "\n\n")

    with open(output_combined_txt, "w", encoding="utf-8") as f:
        current_source = None
        for row in kept_rows + books_rows:
            text = row["text"].strip()
            if not text:
                continue
            if row.get("source_file") != current_source:
                current_source = row.get("source_file")
                f.write("\n\n")
            f.write(text + "\n\n")

    print(f"CPT exclusions: {len(excluded_rows)} chunks -> {output_excluded}")
    print(f"CPT books safe: {len(books_rows)} chunks -> {output_books_txt}")
    print(f"CPT combined safe: {len(kept_rows) + len(books_rows)} chunks -> {output_combined_txt}")
    return len(kept_rows), len(excluded_rows)


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(MANIFEST_PATH))
    parser.add_argument("--policy", default=str(POLICY_PATH))
    args = parser.parse_args()

    manifest = load_jsonl(Path(args.manifest))
    policy = json.loads(Path(args.policy).read_text(encoding="utf-8"))
    cleaned_by_id = load_cleaned_by_id(manifest)

    cpt_rows = build_pool(manifest, cleaned_by_id, policy["cpt"])
    sft_rows = build_pool(manifest, cleaned_by_id, policy["sft_generation"])
    rag_rows = build_pool(manifest, cleaned_by_id, policy["rag"])

    cpt_kept, _ = write_cpt(cpt_rows)
    write_jsonl(CORPUS_DIR / "datasets" / "sft" / "source_chunks.jsonl", sft_rows)
    write_jsonl(CORPUS_DIR / "datasets" / "rag" / "chunks.jsonl", rag_rows)

    print(f"CPT: {cpt_kept} chunks")
    print(f"SFT source chunks: {len(sft_rows)} chunks")
    print(f"RAG dated chunks: {len(rag_rows)} chunks")


if __name__ == "__main__":
    main()
