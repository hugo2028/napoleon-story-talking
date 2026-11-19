"""
Extraction spécialisée pour les fichiers Gallica de la Correspondance.

Produit des fichiers napoleon-corpus/processed/passages/correspondance_N.json compatibles avec
pipeline/generator.py.
"""

import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

from extractor import detect_theme


ROOT = Path(__file__).parent.parent
DEFAULT_INPUT_DIR = ROOT / "napoleon-corpus" / "sources" / "correspondances"
OUTPUT_DIR = ROOT / "napoleon-corpus" / "processed" / "passages"
MAX_WORDS = 220

ENTRY_INLINE_RE = re.compile(r"^(?P<num>\d{1,5})\.\s*(?:[-—–]\s*)?(?P<title>.+)$")
ENTRY_NUMBER_RE = re.compile(r"^\d{1,5}\.$")
DATE_HINT_RE = re.compile(
    r"\b("
    r"quartier|g[ée]n[ée]ral|paris|milan|cairo|caire|boulogne|tuileries|saint-cloud|"
    r"\d{1,2}(?:er|re|e|ème|è)?\s+(janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[ûu]t|septembre|octobre|novembre|d[ée]cembre)|"
    r"(vend[ée]miaire|brumaire|frimaire|niv[oô]se|pluvi[oô]se|vent[oô]se|germinal|flor[ée]al|prairial|messidor|thermidor|fructidor)"
    r")\b",
    re.IGNORECASE,
)
TITLE_HINT_RE = re.compile(
    r"^(A|À|AU|AUX|À LA|A L'|À L'|LE|LA|LES|ORDRE|PROCLAMATION|ALLOCUTION|ARR[ÊE]T[ÉE]|D[ÉE]CRET|NOTE|INSTRUCTIONS?)\b",
    re.IGNORECASE,
)
UNNUMBERED_TITLE_RE = re.compile(
    r"^(A|À|AU|AUX|À LA|A L'|À L'|ORDRE|PROCLAMATION|ALLOCUTION|ARR[ÊE]T[ÉE]|D[ÉE]CRET|NOTE|INSTRUCTIONS?)\b",
    re.IGNORECASE,
)
TABLE_MARKERS_RE = re.compile(r"(SOMMAIRE DES PI[ÈE]CES|FIN DE LA TABLE|Nos des DATES|N[°º] des DATES)", re.IGNORECASE)
SKIP_PARAGRAPH_RE = re.compile(
    r"^(Rappel de votre demande|Format de téléchargement|Vues |Nombre de pages|Notice complète|"
    r"Titre :|Auteur :|Éditeur :|Date d'édition|Contributeur :|Sujet :|Type :|Langue :|"
    r"Format :|Description :|Droits :|Identifiant :|Source :|Conservation numérique|"
    r"Date de mise en ligne|Le texte affiché peut comporter|CORRESPONDANCE|DE|NAPOL[ÉE]ON PREMIER\\.?|"
    r"TOME|PARIS|IMPRIMERIE|M DCCC|Dépôt de la guerre\\.?|Collection Napol[ée]on\\.?|FIN DE LA TABLE)",
    re.IGNORECASE,
)
NOTE_RE = re.compile(r"^(\*?\s*)?\d+\s+[A-ZÀ-Üa-zà-ü].{0,180}$")
EMBEDDED_ENTRY_RE = re.compile(
    r"\s+(?=(?:\d{2,5}\.\s*(?:[-—–]\s*)?"
    r"(?:A|À|AU|AUX|À LA|A L'|À L'|LE|LA|LES|ORDRE|PROCLAMATION|ALLOCUTION|ARR[ÊE]T[ÉE]|D[ÉE]CRET|NOTE|INSTRUCTIONS?)\b))",
    re.IGNORECASE,
)
EMBEDDED_MARKER_IN_BODY_RE = re.compile(
    r"\b\d{2,5}\.\s+(?:A|À|AU|AUX|LE|LA|LES|ORDRE|PROCLAMATION|ARR[ÊE]T[ÉE]|D[ÉE]CRET)\b",
    re.IGNORECASE,
)
TRAILING_RECIPIENT_PLACE_RE = re.compile(
    r",\s*(?:A|À|AU|AUX|A LA|À LA|A L'|À L')\s+(?P<place>[^,.]+)\.?\s*$",
    re.IGNORECASE,
)
LEADING_RECIPIENT_PREFIX_RE = re.compile(
    r"^(?:A|À|AU|AUX|A LA|À LA|A L'|À L')\s+",
    re.IGNORECASE,
)


def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text.strip()


def split_recipient(title: str) -> tuple[str, str | None]:
    """Retourne le destinataire nominal et l'éventuel lieu de destination."""
    title = clean_text(title).rstrip()
    recipient_place = None
    match = TRAILING_RECIPIENT_PLACE_RE.search(title)
    if match:
        recipient_place = clean_text(match.group("place").strip(" ."))
        title = clean_text(title[:match.start()].rstrip(" .,"))
    recipient = LEADING_RECIPIENT_PREFIX_RE.sub("", title).strip(" .")
    return recipient or title, recipient_place


def place_from_date(date_text: str) -> str | None:
    """Extrait le lieu d'écriture depuis une ligne du type 'Ollioules, 13 brumaire...'."""
    text = clean_text(date_text).strip(" .")
    if "," not in text:
        return None
    head = clean_text(text.split(",", 1)[0]).strip(" .")
    if not head:
        return None
    if re.search(r"\d|janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre|vendémiaire|brumaire|frimaire|nivôse|pluviôse|ventôse|germinal|floréal|prairial|messidor|thermidor|fructidor", head, re.IGNORECASE):
        return None
    return head


def split_inline_start(text: str) -> list[str]:
    """Découpe '123. AU X. Paris, 1 janvier. Corps...' en paragraphes logiques."""
    match = ENTRY_INLINE_RE.match(text)
    if not match:
        return [text]

    number = match.group("num")
    rest = clean_text(match.group("title"))
    date_match = DATE_HINT_RE.search(rest)
    if not date_match or date_match.start() < 8:
        return [text]

    title = clean_text(rest[:date_match.start()])
    dated_body = clean_text(rest[date_match.start():])
    sentence_end = -1
    for match_end in re.finditer(r"\.(?:\s+|$)", dated_body):
        candidate = match_end.end()
        head = dated_body[:candidate]
        if DATE_HINT_RE.search(head):
            sentence_end = candidate
            break

    if sentence_end == -1:
        return [f"{number}. {title}", dated_body]

    date = clean_text(dated_body[:sentence_end])
    body = clean_text(dated_body[sentence_end:])
    parts = [f"{number}. {title}", date]
    if body:
        parts.append(body)
    return parts


def plausible_title(text: str) -> bool:
    words = text.split()
    return 1 <= len(words) <= 35 and len(text) <= 260


def plausible_date(text: str) -> bool:
    words = text.split()
    return 1 <= len(words) <= 30 and len(text) <= 220 and bool(DATE_HINT_RE.search(text))


def paragraph_texts(html_path: Path) -> list[str]:
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8", errors="ignore"), "lxml")
    texts = []
    for tag in soup.find_all("p"):
        text = clean_text(tag.get_text(" ", strip=True))
        if text:
            for part in EMBEDDED_ENTRY_RE.split(text):
                part = part.strip()
                if part:
                    texts.extend(split_inline_start(part))
    return texts


def parse_entry_start(paragraphs: list[str], index: int):
    text = paragraphs[index]
    inline = ENTRY_INLINE_RE.match(text)
    if inline:
        number = int(inline.group("num"))
        title = clean_text(inline.group("title"))
        if number > 0 and len(title) >= 4 and plausible_title(title) and TITLE_HINT_RE.search(title):
            date_index = index + 1
            if date_index < len(paragraphs) and plausible_date(paragraphs[date_index]):
                return number, title, paragraphs[date_index], index + 2

    if ENTRY_NUMBER_RE.match(text):
        if index + 2 >= len(paragraphs):
            return None
        title = paragraphs[index + 1]
        date = paragraphs[index + 2]
        number = int(text[:-1])
        if number > 0 and plausible_title(title) and plausible_date(date) and TITLE_HINT_RE.search(title):
            return int(text[:-1]), title, date, index + 3

    if UNNUMBERED_TITLE_RE.search(text):
        date_index = index + 1
        if plausible_title(text) and date_index < len(paragraphs) and plausible_date(paragraphs[date_index]):
            return None, text, paragraphs[date_index], index + 2

    return None


def is_entry_start(paragraphs: list[str], index: int) -> bool:
    return parse_entry_start(paragraphs, index) is not None


def is_noise(text: str) -> bool:
    if SKIP_PARAGRAPH_RE.search(text):
        return True
    if TABLE_MARKERS_RE.search(text):
        return True
    if re.fullmatch(r"[-—–_•* ]+", text):
        return True
    if len(text) <= 2:
        return True
    return False


def trim_body(paragraphs: list[str]) -> list[str]:
    body = []
    for text in paragraphs:
        if is_noise(text):
            continue
        body.append(text)
    return body


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


FIRST_PERSON_IN_TEXT = re.compile(r"\b(je|j'|nous|mon|ma|mes|notre|nos)\b", re.IGNORECASE)


def extract_correspondance_file(html_path: Path) -> list[dict]:
    paragraphs = paragraph_texts(html_path)
    passages = []
    i = 0
    last_number = 0
    while i < len(paragraphs):
        start = parse_entry_start(paragraphs, i)
        if not start:
            i += 1
            continue

        number, title, date, body_start = start
        if number is None:
            number = last_number + 1
        last_number = max(last_number, number)
        recipient, recipient_place = split_recipient(title)
        place = place_from_date(date)
        j = body_start
        body_paragraphs = []
        while j < len(paragraphs) and not is_entry_start(paragraphs, j):
            if TABLE_MARKERS_RE.search(paragraphs[j]):
                break
            body_paragraphs.append(paragraphs[j])
            j += 1

        body = trim_body(body_paragraphs)
        chunks = chunk_paragraphs(body)
        for part_index, text in enumerate(chunks, 1):
            word_count = len(text.split())
            if not text.strip():
                continue

            part_suffix = f" — partie {part_index}" if len(chunks) > 1 else ""
            section = f"{number}. {title} ({date}){part_suffix}"
            passages.append({
                "id": len(passages),
                "letter_id": number,
                "source_id": number,
                "part_index": part_index,
                "part_count": len(chunks),
                "section": section[:180],
                "theme": detect_theme(title + " " + text),
                "text": text,
                "word_count": word_count,
                "recipient": recipient,
                "recipient_raw": title,
                "recipient_place": recipient_place,
                "place": place,
                "date": date,
                "date_text": date,
                "source_file": str(html_path),
            })

        i = max(j, i + 1)

    return passages


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(DEFAULT_INPUT_DIR), help="Fichier HTML ou dossier de correspondances")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    if input_path.is_dir():
        html_files = sorted(input_path.glob("*.html"))
    else:
        html_files = [input_path]

    total = 0
    for html_path in html_files:
        passages = extract_correspondance_file(html_path)
        output_path = output_dir / f"{html_path.stem}.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(passages, ensure_ascii=False, indent=2), encoding="utf-8")
        total += len(passages)
        print(f"{html_path.name}: {len(passages)} passages -> {output_path}")

    print(f"\nTotal: {total} passages")


if __name__ == "__main__":
    main()
