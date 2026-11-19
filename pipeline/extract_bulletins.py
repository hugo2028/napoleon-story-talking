"""
Extraction spécialisée pour les bulletins/proclamations Gallica.

Les bulletins ont souvent une structure en paragraphes:
  ARMÉE D'ITALIE.
  PROCLAMATION AU PEUPLE GÉNOIS.
  27 germinal (,16 avril 1794).
  Corps du texte...

L'extracteur générique traite cela comme du texte continu et perd la date au
niveau des métadonnées. Celui-ci conserve titre + date + corps.
"""

import re
from pathlib import Path

from bs4 import BeautifulSoup

from extractor import detect_theme


MAX_WORDS = 220

DATE_HINT_RE = re.compile(
    r"\b("
    r"\d{1,2}\s+(janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[ûu]t|septembre|octobre|novembre|d[ée]cembre)\s+\d{4}|"
    r"\d{1,2}\s+(vend[ée]miaire|brumaire|frimaire|niv[oô]se|pluvi[oô]se|vent[oô]se|germinal|flor[ée]al|prairial|messidor|thermidor|fructidor)"
    r")\b",
    re.IGNORECASE,
)

TITLE_START_RE = re.compile(
    r"^(PROCLAMATION|RAPPORT|LETTRE|ORDRE|ALLOCUTION|ARR[ÊE]T[ÉE]|D[ÉE]CRET|INSTRUCTIONS?|ADRESSE|MESSAGE|NOTE)\b",
    re.IGNORECASE,
)

SKIP_RE = re.compile(
    r"^(Rappel de votre demande|Format de téléchargement|Vues |Nombre de pages|Notice complète|"
    r"Titre\s*:|Auteur\s*:|Éditeur\s*:|Date d'édition\s*:|Notice d'ensemble\s*:|Type\s*:|Langue\s*:|"
    r"Format\s*:|Description\s*:|Droits\s*:|Identifiant\s*:|Source\s*:|"
    r"Conservation numérique|Date de mise en ligne|Le texte affiché peut comporter|"
    r"Le taux de reconnaissance estimé|BULLETIN|TABLE DES MATI[ÈE]RES|FIN DE LA TABLE)",
    re.IGNORECASE,
)
TITLE_PAGE_RE = re.compile(
    r"(LES\s+BULLETINS|GRANDE\s+ARM[ÉE]E|PR[ÉE]C[ÉE]D[ÉE]S\s+DES\s+RAPPORTS|"
    r"EXTRAITS\s+TEXTUELLEMENT|MONITEUR|ANNALES|ADRIEN\s+PASCAL|"
    r"CHEZ\s+.*LIBRAI|IMPRIMERIE|TOME\s+(PREMIER|DEUXI[ÈE]ME|TROISI[ÈE]ME|QUATRI[ÈE]ME|CINQUI[ÈE]ME|SIXI[ÈE]ME))",
    re.IGNORECASE,
)


def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text.strip()


def place_from_date(date_text: str | None) -> str | None:
    if not date_text:
        return None
    text = clean_text(date_text).strip(" .")
    if "," not in text:
        return None
    head = clean_text(text.split(",", 1)[0]).strip(" .")
    if not head or is_date(head):
        return None
    return head


def paragraph_texts(path: Path) -> list[str]:
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="ignore"), "lxml")
    for tag in soup.select("#pg-header, #pg-footer, .pgheader, .pgfooter"):
        tag.decompose()

    texts = []
    for tag in soup.find_all(["p", "h1", "h2", "h3", "h4", "blockquote"]):
        text = clean_text(tag.get_text(" ", strip=True))
        if not text or len(text) < 3:
            continue
        if re.fullmatch(r"\d+", text):
            continue
        if SKIP_RE.search(text):
            continue
        if TITLE_PAGE_RE.search(text):
            continue
        texts.append(text)
    return texts


def is_date(text: str) -> bool:
    return bool(DATE_HINT_RE.search(text))


def is_probable_title(text: str) -> bool:
    if TITLE_START_RE.search(text):
        return True
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 8:
        return False
    upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
    return upper_ratio > 0.75 and text.endswith((".", ":"))


def parse_document_start(paragraphs: list[str], index: int):
    if index + 1 >= len(paragraphs):
        return None

    title = paragraphs[index]
    if is_probable_title(title) and is_date(paragraphs[index + 1]):
        return title, paragraphs[index + 1], index + 2

    # Cas fréquent: surtitre militaire, puis titre, puis date.
    if (
        index + 2 < len(paragraphs)
        and is_probable_title(paragraphs[index])
        and is_probable_title(paragraphs[index + 1])
        and is_date(paragraphs[index + 2])
    ):
        title = f"{paragraphs[index]} {paragraphs[index + 1]}"
        return title, paragraphs[index + 2], index + 3

    return None


def is_document_start(paragraphs: list[str], index: int) -> bool:
    return parse_document_start(paragraphs, index) is not None


def chunk_paragraphs(paragraphs: list[str], max_words: int = MAX_WORDS) -> list[str]:
    chunks = []
    current = []
    current_words = 0
    for paragraph in paragraphs:
        words = paragraph.split()
        if current and current_words + len(words) > max_words:
            chunks.append(" ".join(current))
            current = []
            current_words = 0
        current.append(paragraph)
        current_words += len(words)
    if current:
        chunks.append(" ".join(current))
    return chunks


def add_chunks(
    passages: list[dict],
    title: str,
    date: str | None,
    body: list[str],
    source_file: Path,
    document_id: int | None,
) -> None:
    chunks = chunk_paragraphs(body)
    place = place_from_date(date)
    for part_index, chunk in enumerate(chunks, 1):
        if not chunk.strip():
            continue
        prefix = ""
        if part_index == 1 and date:
            prefix = f"{title} {date} "
        elif part_index == 1 and title != "Introduction":
            prefix = f"{title} "

        text = clean_text(prefix + chunk)
        part_suffix = f" — partie {part_index}" if len(chunks) > 1 else ""
        section = f"{title}{f' ({date})' if date else ''}{part_suffix}"
        passages.append({
            "id": len(passages),
            "document_id": document_id,
            "letter_id": document_id,
            "part_index": part_index,
            "part_count": len(chunks),
            "section": section[:220],
            "theme": detect_theme(title + " " + text),
            "text": text,
            "word_count": len(text.split()),
            "date": date,
            "date_text": date,
            "place": place,
            "document_title": title,
            "source_file": str(source_file),
        })


def extract_bulletin_file(path: Path) -> list[dict]:
    paragraphs = paragraph_texts(path)
    passages: list[dict] = []
    document_id = 0
    i = 0

    while i < len(paragraphs):
        start = parse_document_start(paragraphs, i)
        if not start:
            i += 1
            continue

        title, date_text, body_start = start
        document_id += 1
        j = body_start
        body = []
        while j < len(paragraphs) and not is_document_start(paragraphs, j):
            body.append(paragraphs[j])
            j += 1

        add_chunks(passages, title, date_text, body, path, document_id)
        i = max(j, i + 1)

    return passages
