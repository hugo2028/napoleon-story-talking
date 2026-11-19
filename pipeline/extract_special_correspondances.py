"""
Extracteurs pour les petites correspondances qui ne suivent pas la structure
des 32 tomes.

Ces fichiers ont chacun une mise en page propre:
- marine_1: lettres et documents clos par signature, avec dates souvent
  républicaines ou en titre séparé.
- marine_2: une succession de lettres datées, sans numéro de pièce.
- inedites: LETTRE I, date, destinataire, corps.
- adieux_marie: deux lettres publiées dans un opuscule.
"""

import re
from pathlib import Path

from bs4 import BeautifulSoup

from extractor import detect_theme


MAX_WORDS = 220

MONTH_RE = (
    r"janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[ûu]t|septembre|"
    r"octobre|novembre|d[ée]cembre"
)
DATE_LINE_RE = re.compile(
    rf"^(?:(?P<place>[A-ZÀ-ÜA-Za-zà-ü' .-]+),\s*)?"
    rf"(?:le\s*)?(?P<date>\d{{1,2}}(?:er)?\s+(?:{MONTH_RE})(?:\s+\d{{3,4}})?|"
    rf"\d{{1,2}}\s*(?:id\.|octob\.|décem\.|fév\.|janv\.))\.?$",
    re.IGNORECASE,
)
DATE_HINT_RE = re.compile(
    rf"\b(?:{MONTH_RE}|id\.|janv\.|fév\.|octob\.|décem\.)\b",
    re.IGNORECASE,
)
MARINE_1_DATE_RE = re.compile(
    rf"^(?:[A-ZÀ-ÜA-Za-zà-ü' .-]+,\s*)?(?:A la |Au |Aux |St-|Saint-|le\s*)?"
    rf".*(?:\b\d{{1,2}}(?:er)?\s+(?:{MONTH_RE})\b|\b\d{{1,2}}\s+"
    rf"(?:vend[ée]miaire|brumaire|frimaire|niv[ôo]se|pluvi[ôo]se|vent[ôo]se|"
    rf"germinal|flor[ée]al|prairial|messidor|thermidor|fructidor)\b|"
    rf"\ban\s+[xivl0-9]+|\(\s*\d{{1,2}}(?:er)?\s+(?:{MONTH_RE})\s+\d{{3,4}}\s*\))",
    re.IGNORECASE,
)
DATE_PREFIX_RE = re.compile(
    rf"^(?P<date>(?:(?P<place>[A-ZÀ-ÜA-Za-zà-ü' .-]+),\s*)?"
    rf"(?:le\s*)?(?:\d{{1,2}}|[gqh])\s*(?:{MONTH_RE})(?:\s+\d{{3,4}})?|"
    rf"du\s+\d{{1,2}}[^.]*|"
    rf"\d{{1,2}}\s*(?:mai|juin|juillet|ao[ûu]t|septembre|octobre|novembre|d[ée]cembre)[,.]*)"
    rf"\.?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
INLINE_RECIPIENT_RE = re.compile(
    r"^(?P<recipient>(?:MONSIEUR|MADAME|SIRE|MONSEIGNEUR|CITOYEN|ALPHONSE|MA CH[ÈE]RE [^,]+)[^,]{0,80}),\s*(?P<body>.*)$",
    re.IGNORECASE,
)
LETTER_RE = re.compile(r"^LETTRE\s+(?P<num>[IVXLCDM]+)\.?\s*$", re.IGNORECASE)
PAGE_RE = re.compile(r"^\(?\s*[ivxlcdm\d]+\s*\)?\.?$", re.IGNORECASE)
SKIP_RE = re.compile(
    r"^(Rappel de votre demande|Format de téléchargement|Vues |Nombre de pages|Notice complète|"
    r"Titre\s*:|Auteur\s*:|Éditeur\s*:|Date d'édition\s*:|Contributeur\s*:|Sujet\s*:|"
    r"Type\s*:|Langue\s*:|Format\s*:|Description\s*:|Droits\s*:|Identifiant\s*:|"
    r"Source\s*:|Notice du catalogue|Conservation numérique|Date de mise en ligne|"
    r"Le texte affiché peut comporter|Le taux de reconnaissance estimé|TABLE|FIN DE LA TABLE|"
    r"DE L'IMPRIMERIE|PARIS IMPRIMERIE|DELLOYE|PONTHIEU|MONGIE|LES MARCHANDS)",
    re.IGNORECASE,
)
TITLE_PAGE_RE = re.compile(
    r"^(CORRESPONDANCE|DE|NAPOL[ÉE]ON|LE MINISTRE|TOME SECOND|QUARANTE|RECUEILLIES|"
    r"AVERTISSEMENT|L\. F\.|1825\.|1837\.|SUIVIS|DES CONSEILS|ET D'UNE LETTRE)$",
    re.IGNORECASE,
)
SIGNATURE_RE = re.compile(r"^NAPOL[ÉE]ON[,.]?$", re.IGNORECASE)
MARINE_1_GENERIC_TITLE_RE = re.compile(
    r"^(CORRESPONDANCE|DE NAPOL[ÉE]ON|AVEC|MINISTRE DE LA MARINE|Depuis |"
    r"EXTRAITE D'UN PORTEFEUILLE|TOME PREMIER|DES LETTRES|AVERTISSEMENT)",
    re.IGNORECASE,
)
MARINE_1_NOTE_RE = re.compile(r"^\(?\s*[\dijIlCcSs,'’]+\s*\)\s+")


def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text.strip()


def paragraph_texts(path: Path) -> list[str]:
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="ignore"), "lxml")
    for tag in soup.select("#pg-header, #pg-footer, .pgheader, .pgfooter"):
        tag.decompose()

    texts = []
    for tag in soup.find_all(["p", "h1", "h2", "h3", "h4", "blockquote"]):
        text = clean_text(tag.get_text(" ", strip=True))
        if not text:
            continue
        if PAGE_RE.fullmatch(text):
            continue
        if SKIP_RE.search(text) or TITLE_PAGE_RE.search(text):
            continue
        texts.append(text)
    return texts


def normalize_place(place: str | None) -> str | None:
    if not place:
        return None
    place = clean_text(place).strip(" .,")
    return place or None


def is_date_line(text: str) -> bool:
    return bool(DATE_LINE_RE.match(clean_text(text).strip(" .")))


def is_dateish_line(text: str) -> bool:
    text = clean_text(text)
    return is_date_line(text) or bool(DATE_HINT_RE.search(text) and len(text.split()) <= 8)


def is_marine_1_date_line(text: str) -> bool:
    text = clean_text(text).strip(" .")
    if MARINE_1_NOTE_RE.match(text) or text.startswith("("):
        return False
    if len(text.split()) > 16:
        return False
    if not MARINE_1_DATE_RE.search(text):
        return False
    return bool(
        re.search(r"\b\d{3,4}\b", text)
        or re.search(r"\ban\s+[xivl0-9]+\b", text, re.IGNORECASE)
        or re.search(rf"\b\d{{1,2}}\s+(?:{MONTH_RE})\b", text, re.IGNORECASE)
    )


def is_marine_1_title_line(text: str) -> bool:
    text = clean_text(text).strip(" .")
    if not text or MARINE_1_GENERIC_TITLE_RE.search(text):
        return False
    if len(text.split()) > 18:
        return False
    has_letters = re.search(r"[A-Za-zÀ-Üà-ü]", text)
    mostly_upper = text.upper() == text
    return bool(has_letters and mostly_upper)


def is_standalone_note(text: str) -> bool:
    text = clean_text(text)
    return bool(MARINE_1_NOTE_RE.match(text) and len(text.split()) <= 28)


def is_recipient_line(text: str) -> bool:
    text = clean_text(text).strip(" ,.")
    if len(text.split()) > 8:
        return False
    return bool(re.match(r"^(MONSIEUR|MADAME|SIRE|MONSEIGNEUR|CITOYEN|ALPHONSE)\b", text, re.IGNORECASE))


def date_parts(text: str) -> tuple[str, str | None]:
    cleaned = clean_text(text).strip()
    match = DATE_LINE_RE.match(cleaned.strip(" ."))
    if match:
        return cleaned, normalize_place(match.group("place"))
    if "," in cleaned:
        head = cleaned.split(",", 1)[0]
        if not DATE_HINT_RE.search(head):
            return cleaned, normalize_place(head)
    return cleaned, None


def split_date_prefix(text: str) -> tuple[str | None, str | None, str]:
    cleaned = clean_text(text).strip()
    match = DATE_PREFIX_RE.match(cleaned)
    if not match:
        return None, None, cleaned
    date_text = clean_text(match.group("date")).strip(" .") + "."
    place = normalize_place(match.group("place"))
    rest = clean_text(match.group("rest"))
    return date_text, place, rest


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


def add_document(
    passages: list[dict],
    *,
    source_file: Path,
    letter_id: str | int,
    title: str,
    recipient: str | None,
    date_text: str | None,
    place: str | None,
    body: list[str],
) -> None:
    body = [clean_text(text) for text in body if clean_text(text)]
    if not body:
        return

    chunks = chunk_paragraphs(body)
    for part_index, text in enumerate(chunks, 1):
        section = title
        if date_text:
            section = f"{section} ({date_text})"
        if len(chunks) > 1:
            section = f"{section} — partie {part_index}"
        passages.append({
            "id": len(passages),
            "letter_id": letter_id,
            "source_id": letter_id,
            "part_index": part_index,
            "part_count": len(chunks),
            "section": section[:220],
            "theme": detect_theme(f"{title} {text}"),
            "text": text,
            "word_count": len(text.split()),
            "recipient": recipient,
            "recipient_raw": recipient,
            "recipient_place": None,
            "place": place,
            "date": date_text,
            "date_text": date_text,
            "source_file": str(source_file),
        })


def extract_marine_1_file(path: Path) -> list[dict]:
    paragraphs = paragraph_texts(path)
    passages: list[dict] = []
    current_date: str | None = None
    current_place: str | None = None
    current_title: str | None = None
    current_recipient: str | None = None
    pending_title: str | None = None
    body: list[str] = []
    letter_no = 0
    in_documents = False
    corpus_marker_count = 0

    def flush() -> None:
        nonlocal body, current_date, current_place, current_title, current_recipient
        if current_date and body:
            add_document(
                passages,
                source_file=path,
                letter_id=letter_no,
                title=current_title or "Lettre au ministre de la Marine",
                recipient=current_recipient,
                date_text=current_date,
                place=current_place,
                body=body,
            )
        body = []
        current_date = None
        current_place = None
        current_title = None
        current_recipient = None

    for text in paragraphs:
        if "EXTRAITE D'UN PORTEFEUILLE DE SAINTE" in text.upper():
            corpus_marker_count += 1
            in_documents = corpus_marker_count >= 2
            continue
        if not in_documents:
            continue

        if SIGNATURE_RE.match(text):
            flush()
            pending_title = None
            continue

        if is_marine_1_title_line(text):
            if current_date and body:
                flush()
            pending_title = text.strip(" .")
            continue

        if is_marine_1_date_line(text):
            if current_date and not body and text.startswith("("):
                current_date = clean_text(f"{current_date} {text}")
                continue
            flush()
            letter_no += 1
            current_date, current_place = date_parts(text)
            current_title = pending_title or "Lettre au ministre de la Marine"
            pending_title = None
            continue

        if not current_date:
            continue

        if is_standalone_note(text):
            continue

        if current_recipient is None:
            inline_recipient = INLINE_RECIPIENT_RE.match(text)
            if inline_recipient:
                current_recipient = inline_recipient.group("recipient").strip(" ,.")
            elif is_recipient_line(text):
                current_recipient = text.strip(" ,.")

        body.append(text)

    flush()
    return passages


def extract_marine_2_file(path: Path) -> list[dict]:
    paragraphs = paragraph_texts(path)
    passages: list[dict] = []
    current_date: str | None = None
    current_place: str | None = None
    current_recipient: str | None = None
    body: list[str] = []
    letter_no = 0
    in_letters = False

    def flush() -> None:
        nonlocal body
        if current_date and body:
            add_document(
                passages,
                source_file=path,
                letter_id=letter_no,
                title=f"Lettre au ministre de la Marine",
                recipient=current_recipient,
                date_text=current_date,
                place=current_place,
                body=body,
            )
        body = []

    for text in paragraphs:
        upper = text.upper()
        if in_letters and (
            "FIN DU SECOND" in upper
            or "TABLE ALPHAB" in upper
            or "DES NOMS CIT" in upper
        ):
            flush()
            break
        if "Depuis" in text and "avril 1815" in text:
            in_letters = True
            continue
        if not in_letters:
            continue
        if is_date_line(text):
            flush()
            letter_no += 1
            current_date, current_place = date_parts(text)
            current_recipient = None
            continue
        if not current_date:
            continue
        if current_recipient is None:
            inline_recipient = INLINE_RECIPIENT_RE.match(text)
            if inline_recipient:
                current_recipient = inline_recipient.group("recipient").strip(" ,.")
            elif is_recipient_line(text):
                current_recipient = text.strip(" ,.")
                body.append(text)
                continue
        body.append(text)

    flush()
    return passages


def extract_inedites_file(path: Path) -> list[dict]:
    paragraphs = paragraph_texts(path)
    passages: list[dict] = []
    current_letter: str | None = None
    current_date: str | None = None
    current_place: str | None = None
    current_recipient: str | None = None
    body: list[str] = []
    index = 0

    def flush() -> None:
        nonlocal body
        if current_letter and body:
            add_document(
                passages,
                source_file=path,
                letter_id=current_letter,
                title=current_letter,
                recipient=current_recipient,
                date_text=current_date,
                place=current_place,
                body=body,
            )
        body = []

    while index < len(paragraphs):
        text = paragraphs[index]
        match = LETTER_RE.match(text)
        if match:
            flush()
            current_letter = f"LETTRE {match.group('num').upper()}"
            current_date = None
            current_place = None
            current_recipient = None
            index += 1
            continue

        if current_letter and current_date is None:
            date_prefix, place_prefix, rest = split_date_prefix(text)
            if date_prefix:
                current_date = date_prefix
                current_place = place_prefix
                if rest:
                    text = rest
                else:
                    index += 1
                    continue
            elif is_dateish_line(text):
                current_date, current_place = date_parts(text)
                index += 1
                continue
            else:
                pass

        if current_letter and current_recipient is None:
            inline_recipient = INLINE_RECIPIENT_RE.match(text)
            if inline_recipient:
                current_recipient = inline_recipient.group("recipient").strip(" ,.")
                rest = inline_recipient.group("body")
                if rest:
                    body.append(rest)
                index += 1
                continue

        if current_letter and current_date is None and is_dateish_line(text):
            current_date, current_place = date_parts(text)
            index += 1
            continue

        if current_letter and current_recipient is None and is_recipient_line(text):
            current_recipient = text.strip(" ,.")
            body.append(text)
            index += 1
            continue

        if current_letter:
            body.append(text)
        index += 1

    flush()
    return passages


def extract_adieux_marie_file(path: Path) -> list[dict]:
    paragraphs = paragraph_texts(path)
    passages: list[dict] = []

    marie_body: list[str] = []
    josephine_body: list[str] = []
    mode: str | None = None
    pending_josephine_header = False
    josephine_date: str | None = None
    josephine_place: str | None = None

    for text in paragraphs:
        lower = text.lower()
        if "ma chère épouse" in lower:
            mode = "marie"
            continue
        if "lettre de" in lower:
            if mode == "marie":
                before, _, _ = text.partition("Lettre")
                if before.strip():
                    marie_body.append(before.strip())
                if marie_body:
                    add_document(
                        passages,
                        source_file=path,
                        letter_id="adieux_marie_louise",
                        title="Adieux à Marie-Louise",
                        recipient="Marie-Louise",
                        date_text=None,
                        place=None,
                        body=marie_body,
                    )
                    marie_body = []
            pending_josephine_header = True
            mode = "josephine_header"
            continue

        if pending_josephine_header and "joséphine" in lower:
            continue

        if "joséphine" in lower and "lettre" in lower:
            before, _, after = text.partition("Lettre")
            if mode == "marie" and before.strip():
                marie_body.append(before.strip())
            if marie_body:
                add_document(
                    passages,
                    source_file=path,
                    letter_id="adieux_marie_louise",
                    title="Adieux à Marie-Louise",
                    recipient="Marie-Louise",
                    date_text=None,
                    place=None,
                    body=marie_body,
                )
                marie_body = []
            mode = "josephine_header"
            if "fontainebleau" in after.lower():
                _, _, dated = after.partition("Au château")
                dated = "Au château" + dated if dated else after
                salutation_match = re.search(r"\bCh[èe]re\b", dated, re.IGNORECASE)
                if salutation_match:
                    josephine_date = clean_text(dated[:salutation_match.start()]).strip(" .") + "."
                    josephine_body.append(clean_text(dated[salutation_match.start():]))
                else:
                    josephine_date = clean_text(dated)
                josephine_place = "Fontainebleau"
                mode = "josephine"
            continue
        if mode == "josephine_header" and ("fontainebleau" in lower or is_date_line(text)):
            josephine_date = text
            josephine_place = "Fontainebleau" if "fontainebleau" in lower else date_parts(text)[1]
            mode = "josephine"
            pending_josephine_header = False
            continue
        if "de l'imprim" in lower:
            break
        if mode == "marie":
            marie_body.append(text)
        elif mode == "josephine":
            josephine_body.append(text)

    if marie_body:
        add_document(
            passages,
            source_file=path,
            letter_id="adieux_marie_louise",
            title="Adieux à Marie-Louise",
            recipient="Marie-Louise",
            date_text=None,
            place=None,
            body=marie_body,
        )
    if josephine_body:
        add_document(
            passages,
            source_file=path,
            letter_id="lettre_josephine_1814_04_06",
            title="Lettre à Joséphine",
            recipient="Joséphine",
            date_text=josephine_date,
            place=josephine_place,
            body=josephine_body,
        )
    return passages
