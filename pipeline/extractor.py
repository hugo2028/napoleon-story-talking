"""
Étape 1 : Extraction des passages clés depuis le HTML de Gutenberg.
Produit napoleon-corpus/processed/passages/passages.json
"""

import json
import re
from pathlib import Path
from bs4 import BeautifulSoup

# Mapping titre de section → thème
THEME_RULES = [
    (r"sainte-hélène|exil|captivité|hudson\slowe|île|après ma chute|longwood", "exil"),
    (r"famille|joséphine|marie.louise|enfant|frère|sœur|mère|père|mariage|mon fils", "famille"),
    (r"diplomatie|traité|paix|ambassadeur|puissance|alliance|négociation", "diplomatie"),
    (r"consul|gouvernement|loi|sénat|décret|empire|constitution|administration|code", "politique"),
    (r"stratégie|manœuvre|ordre de bataille|corps d.armée|division|artillerie|cavalerie|tactique", "stratégie"),
    (r"proclam", "proclamation"),
    (r"lettre|correspondent", "correspondance"),
    (r"campagne|armée|bataille|victoire|ennemi|soldat|officier|régiment|guerre|combat|attaque|siège", "guerre"),
    (r"égypte|orient|mameluk|syrie|pyramide|nil", "guerre"),
]

SYSTEM_PROMPT = (
    "Tu es Napoléon Bonaparte, Empereur des Français. "
    "Tu réponds toujours à la première personne."
)

DEFAULT_HTML_PATH = (
    Path(__file__).parent.parent
    / "napoleon-corpus"
    / "sources"
    / "mémoires"
    / "mémoires tome 1"
    / "memoires_1.html"
)
DATA_DIR = Path(__file__).parent.parent / "napoleon-corpus" / "processed" / "passages"

# Longueur cible d'un passage en mots (pour segmentation)
MAX_WORDS = 180
MIN_WORDS = 40
TERMINAL_RE = re.compile(r'[.!?]["»”)]*$')
VALID_START_RE = re.compile(r'^[A-ZÀÂÄÇÉÈÊËÎÏÔÖÙÛÜŸ0-9«"(]')
ABBREVIATIONS = {
    "M.": "M§",
    "MM.": "MM§",
    "Mme.": "Mme§",
    "Mlle.": "Mlle§",
    "S. M.": "S§ M§",
    "S. A.": "S§ A§",
    "etc.": "etc§",
}
SKIP_RE = re.compile(
    r"^(Rappel de votre demande|Format de téléchargement|Vues |Nombre de pages|Notice complète|Notice du catalogue|Notice d'ensemble|"
    r"Titre\s*:|Auteur\s*:|Éditeur\s*:|Date d'édition\s*:|Contributeur\s*:|Sujet\s*:|Type\s*:|Langue\s*:|"
    r"Format\s*:|Description\s*:|Droits\s*:|Identifiant\s*:|Source\s*:|Conservation numérique|"
    r"Date de mise en ligne|Le texte affiché peut comporter|Le taux de reconnaissance estimé|"
    r"The Project Gutenberg|Project Gutenberg|BIBLIOTH[ÈE]QUE DE L'ARM[ÉE]E|LIBRAIRIE HACHETTE|"
    r"DE L'IMPRIMERIE|IMPRIMERIE|TYPOGRAPHIE|PONTHIEU|MONGIE|LES MARCHANDS DE NOUVEAUT[ÉE]S)",
    re.IGNORECASE,
)
BOILERPLATE_PASSAGE_RE = re.compile(
    r"(Notice d'ensemble|Project Gutenberg|BIBLIOTH[ÈE]QUE DE L'ARM[ÉE]E|"
    r"LIBRAIRIE|HACHETTE|TYPOGRAPHIE|IMPRIMERIE|BOULEVARD SAINT-GERMAIN|"
    r"QUAI DES GRANDS|LECTEUR, VEUILLEZ|REVUE DES DEUX MONDES)",
    re.IGNORECASE,
)
TRAILING_TABLE_RE = re.compile(
    r"(TABLE DES MATI[ÈE]RES|TABLE ALPHAB[ÉE]TIQUE|FIN DE LA TABLE|"
    r"CINQUI[ÈE]ME LIVRAISON|pages?\s+\d+|"
    r"(?:\b[IVXLCDM]{1,6}\.\s+[^.]{5,80}){4,})",
    re.IGNORECASE,
)


def detect_theme(text: str) -> str:
    """Détecte le thème depuis le texte du passage (plus fiable que le titre de section)."""
    text_lower = text.lower()
    # Compter les hits pour chaque thème
    scores: dict[str, int] = {}
    for pattern, theme in THEME_RULES:
        hits = len(re.findall(pattern, text_lower))
        if hits:
            scores[theme] = scores.get(theme, 0) + hits
    if scores:
        return max(scores, key=lambda t: scores[t])
    return "général"



def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text.strip()


def should_skip_text(text: str) -> bool:
    if SKIP_RE.search(text):
        return True
    if re.fullmatch(r"[-—–_•*@ ]+", text):
        return True
    return False


def protect_abbreviations(text: str) -> str:
    for source, target in ABBREVIATIONS.items():
        text = text.replace(source, target)
    return text


def restore_abbreviations(text: str) -> str:
    return text.replace("§", ".")


def split_sentences(text: str) -> tuple[list[str], str]:
    """Retourne les phrases complètes et le fragment final non terminé."""
    protected = protect_abbreviations(text)
    sentences: list[str] = []
    start = 0
    pattern = re.compile(r'[.!?]["»”)]?(?=\s+[A-ZÀÂÄÇÉÈÊËÎÏÔÖÙÛÜŸ«"(]|\s*$)')
    for match in pattern.finditer(protected):
        sentence = restore_abbreviations(protected[start:match.end()]).strip()
        if sentence:
            sentences.append(sentence)
        start = match.end()
    remainder = restore_abbreviations(protected[start:]).strip()
    return sentences, remainder


def complete_passage(text: str) -> bool:
    text = text.strip()
    return bool(text and VALID_START_RE.match(text) and TERMINAL_RE.search(text))


def chunk_complete_sentences(text: str, max_words: int = MAX_WORDS) -> tuple[list[str], str | None]:
    """Construit des chunks de phrases complètes et signale le reste tronqué."""
    sentences, remainder = split_sentences(text)
    chunks: list[str] = []
    current: list[str] = []
    words = 0

    def flush() -> None:
        nonlocal current, words
        if not current:
            return
        chunk = clean_text(" ".join(current))
        if len(chunk.split()) >= MIN_WORDS and complete_passage(chunk):
            chunks.append(chunk)
        current = []
        words = 0

    for sentence in sentences:
        sentence_words = len(sentence.split())
        if current and words + sentence_words > max_words:
            flush()
        current.append(sentence)
        words += sentence_words
        if words >= max_words:
            flush()

    flush()
    return chunks, (remainder or None)


def is_front_boilerplate_passage(text: str) -> bool:
    return bool(BOILERPLATE_PASSAGE_RE.search(text[:700]))


def is_back_matter_passage(text: str) -> bool:
    return bool(BOILERPLATE_PASSAGE_RE.search(text[:700]) or TRAILING_TABLE_RE.search(text[:1200]))


def trim_book_matter(passages: list[dict]) -> list[dict]:
    while passages and is_front_boilerplate_passage(passages[0].get("text", "")):
        passages.pop(0)
    while passages and is_back_matter_passage(passages[-1].get("text", "")):
        passages.pop()
    for index, passage in enumerate(passages):
        passage["id"] = index
    return passages



def extract_passages(html_path: Path = None) -> list[dict]:
    html_path = html_path or DEFAULT_HTML_PATH
    print(f"Lecture de {html_path}...")
    with open(html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "lxml")

    # Supprimer header/footer Gutenberg
    for tag in soup.select("#pg-header, #pg-footer, .pgheader, .pgfooter"):
        tag.decompose()

    passages = []
    current_section = "Introduction"
    current_theme = "général"
    buffer_paragraphs: list[str] = []

    def add_passage(text: str, flags: list[str] | None = None):
        """Ajoute un passage après détection de thème."""
        if not text.strip():
            return
        text = clean_text(text)
        if not complete_passage(text):
            return
        words = text.split()
        theme = detect_theme(text)
        passages.append({
            "id": len(passages),
            "section": current_section,
            "theme": theme,
            "text": text,
            "word_count": len(words),
            "extraction_flags": flags or ["sentence_complete"],
        })

    def flush_buffer():
        nonlocal buffer_paragraphs
        if not buffer_paragraphs:
            return
        text = " ".join(buffer_paragraphs)
        split_and_flush(text)
        buffer_paragraphs = []

    def split_and_flush(text: str):
        """Découpe en passages de phrases complètes, sans apprendre les fins coupées."""
        chunks, remainder = chunk_complete_sentences(text)
        for chunk in chunks:
            add_passage(chunk)
        if remainder and passages:
            passages[-1].setdefault("dropped_remainder", True)

    body = soup.find("body")
    if not body:
        raise RuntimeError("Body non trouvé dans le HTML")

    for tag in body.children:
        if not hasattr(tag, "name") or tag.name is None:
            continue

        if tag.name in ("h1", "h2", "h3", "h4"):
            flush_buffer()
            heading_text = clean_text(tag.get_text())
            if len(heading_text) > 5:
                current_section = heading_text[:100]
                current_theme = detect_theme(current_section)

        elif tag.name in ("p", "blockquote"):
            text = clean_text(tag.get_text())
            # Ignorer les notes de bas de page et numéros de page
            if len(text) < 20:
                continue
            if re.match(r"^\d+$", text):
                continue
            if should_skip_text(text):
                continue

            buffer_paragraphs.append(text)
            combined = " ".join(buffer_paragraphs)
            if len(combined.split()) >= MAX_WORDS:
                split_and_flush(combined)
                buffer_paragraphs = []

        elif tag.name in ("div", "section"):
            # Traiter récursivement les divs
            for child in tag.find_all(["h1", "h2", "h3", "h4", "p", "blockquote"]):
                if child.name in ("h1", "h2", "h3", "h4"):
                    flush_buffer()
                    heading_text = clean_text(child.get_text())
                    if len(heading_text) > 5:
                        current_section = heading_text[:100]
                        current_theme = detect_theme(current_section)
                else:
                    text = clean_text(child.get_text())
                    if len(text) < 20 or re.match(r"^\d+$", text):
                        continue
                    if should_skip_text(text):
                        continue
                    buffer_paragraphs.append(text)
                    combined = " ".join(buffer_paragraphs)
                    if len(combined.split()) >= MAX_WORDS:
                        split_and_flush(combined)
                        buffer_paragraphs = []

    flush_buffer()
    passages = trim_book_matter(passages)

    # Statistiques par thème
    theme_counts: dict[str, int] = {}
    for p in passages:
        theme_counts[p["theme"]] = theme_counts.get(p["theme"], 0) + 1

    print(f"\n✓ {len(passages)} passages extraits")
    print("\nRépartition par thème:")
    for theme, count in sorted(theme_counts.items(), key=lambda x: -x[1]):
        print(f"  {theme:<20} {count:>4} passages")

    return passages


def main(html_path: Path = None) -> Path:
    html_path = Path(html_path) if html_path else DEFAULT_HTML_PATH
    # Nom du fichier de sortie basé sur le fichier d'entrée
    output_path = DATA_DIR / f"{html_path.stem}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    passages = extract_passages(html_path)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(passages, f, ensure_ascii=False, indent=2)
    print(f"\n→ Sauvegardé dans {output_path}")
    return output_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", "-i", default=None,
                        help="Chemin vers le fichier HTML ou TXT source")
    args = parser.parse_args()
    main(args.input)
