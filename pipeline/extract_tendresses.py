"""
Extraction spécialisée pour Tendresses impériales.

Le HTML est structuré par lettres:
  h2 LETTRE I
  h4 À Joséphine, à Milan.
  p  Marmirolo, le 29 messidor... (17 Juillet 1796).
  p  Corps...

On conserve la lettre comme unité logique et on propage la même date à toutes
les parties si la lettre doit être découpée.
"""

import re
from pathlib import Path

from bs4 import BeautifulSoup

from extractor import detect_theme


MAX_WORDS = 220
DATE_HINT_RE = re.compile(
    r"\b("
    r"\d{4}|"
    r"\d{1,2}\s+(janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[ûu]t|septembre|octobre|novembre|d[ée]cembre)|"
    r"(vend[ée]miaire|brumaire|frimaire|niv[oô]se|pluvi[oô]se|vent[oô]se|germinal|flor[ée]al|prairial|messidor|thermidor|fructidor)"
    r")\b",
    re.IGNORECASE,
)
TRAILING_RECIPIENT_PLACE_RE = re.compile(
    r",\s*(?:a|à|au|aux|a la|à la|a l'|à l')\s+(?P<place>[^,.]+)\.?\s*$",
    re.IGNORECASE,
)
LEADING_RECIPIENT_PREFIX_RE = re.compile(
    r"^(?:a|à|au|aux|a la|à la|a l'|à l')\s+",
    re.IGNORECASE,
)


def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text.strip()


def split_recipient(title: str | None) -> tuple[str | None, str | None]:
    if not title:
        return None, None
    text = clean_text(title)
    recipient_place = None
    match = TRAILING_RECIPIENT_PLACE_RE.search(text)
    if match:
        recipient_place = clean_text(match.group("place").strip(" ."))
        text = clean_text(text[:match.start()].rstrip(" .,"))
    recipient = LEADING_RECIPIENT_PREFIX_RE.sub("", text).strip(" .")
    return recipient or text, recipient_place


def place_from_date(date_text: str | None) -> str | None:
    if not date_text:
        return None
    text = clean_text(date_text).strip(" .")
    if "," not in text:
        return None
    head = clean_text(text.split(",", 1)[0]).strip(" .")
    if not head or DATE_HINT_RE.search(head):
        return None
    return head


def iter_blocks(path: Path) -> list[tuple[str, str]]:
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="ignore"), "lxml")
    for tag in soup.select("#pg-header, #pg-footer, .pgheader, .pgfooter"):
        tag.decompose()

    blocks = []
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "p", "blockquote"]):
        text = clean_text(tag.get_text(" ", strip=True))
        if text:
            blocks.append((tag.name, text))
    return blocks


def chunk_paragraphs(paragraphs: list[str], max_words: int = MAX_WORDS) -> list[str]:
    chunks = []
    current = []
    words = 0
    for paragraph in paragraphs:
        count = len(paragraph.split())
        if current and words + count > max_words:
            chunks.append(" ".join(current))
            current = []
            words = 0
        current.append(paragraph)
        words += count
    if current:
        chunks.append(" ".join(current))
    return chunks


def is_date_line(text: str) -> bool:
    return bool(DATE_HINT_RE.search(text))


def extract_tendresses_file(path: Path) -> list[dict]:
    blocks = iter_blocks(path)
    passages = []
    current_letter: str | None = None
    current_title: str | None = None
    current_date: str | None = None
    body: list[str] = []

    def flush_letter() -> None:
        nonlocal body
        if not current_letter or not body:
            body = []
            return

        chunks = chunk_paragraphs(body)
        title = current_title or current_letter
        recipient, recipient_place = split_recipient(current_title)
        place = place_from_date(current_date)
        for part_index, text in enumerate(chunks, 1):
            text = clean_text(text)
            if not text:
                continue
            part_suffix = f" — partie {part_index}" if len(chunks) > 1 else ""
            section = f"{current_letter}. {title}{f' ({current_date})' if current_date else ''}{part_suffix}"
            passages.append({
                "id": len(passages),
                "letter_id": current_letter,
                "part_index": part_index,
                "part_count": len(chunks),
                "section": section[:220],
                "theme": detect_theme(title + " " + text),
                "text": text,
                "word_count": len(text.split()),
                "recipient": recipient or title,
                "recipient_raw": current_title,
                "recipient_place": recipient_place,
                "place": place,
                "date": current_date,
                "date_text": current_date,
                "source_file": str(path),
            })
        body = []

    i = 0
    while i < len(blocks):
        tag, text = blocks[i]
        if tag == "h2" and re.match(r"^LETTRE\s+[IVXLCDM]+\b", text, re.IGNORECASE):
            flush_letter()
            current_letter = text
            current_title = None
            current_date = None
            body = []
            i += 1
            continue

        if current_letter and tag == "h2":
            flush_letter()
            current_letter = None
            current_title = None
            current_date = None
            body = []
            i += 1
            continue

        if current_letter and tag in {"h3", "h4"} and current_title is None:
            current_title = text
            i += 1
            continue

        if current_letter and tag in {"p", "blockquote"}:
            if current_date is None and not body and is_date_line(text):
                current_date = text
                body.append(text)
            else:
                body.append(text)
            i += 1
            continue

        i += 1

    flush_letter()
    return passages
