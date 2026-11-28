"""
Archiviste autonome — agent à outils qui enquête dans la correspondance et pilote le récit.

Au lieu d'un pipeline figé (classifieur → seuil fixe → échantillonnage → découpage automatique),
un LLM « archiviste » dispose d'outils pour :
  - consulter la chronologie et la répartition des lettres d'une période,
  - chercher (sémantique avec seuil et limite choisis par lui, ou mots exacts),
  - lire les lettres et les Œuvres de Napoléon Bonaparte (éd. Panckoucke),
  - fixer / réviser un plan de récit en chapitres,
  - servir un tour (lettres à raconter + pistes proposées au visiteur).

La narration reste confiée au prompt de Napoléon (SYSTEM_PROMPT de napoleon_agent).
Activé par AGENT_MODE=autonome (défaut). Modèle de l'archiviste : AGENT_MODEL (défaut gpt-4.1).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
from pathlib import Path
from collections import Counter
from difflib import SequenceMatcher

import numpy as np

import unicodedata

from napoleon_agent import NAPOLEON_FICHE, cosine_sim, embed_question, fetch_chunks

# Sections des Œuvres : titre lisible et période, pour situer chaque passage dans le temps
_SECTIONS_FILE = Path(__file__).resolve().parent.parent / "napoleon-corpus" / "metadata" / "oeuvres_sections.json"
OEUVRES_SECTIONS = {k: v for k, v in json.loads(_SECTIONS_FILE.read_text(encoding="utf-8")).items()
                    if not k.startswith("_")} if _SECTIONS_FILE.exists() else {}


# Passages des Œuvres gardés pour la recherche, datés un par un (scripts/build_oeuvres_passages.py) : seuls ceux
# dont la date est sûre y figurent ; les autres ne sont plus proposés.
_PASSAGES_FILE = _SECTIONS_FILE.parent / "oeuvres_passages.json"
PASSAGES_OEUVRES = (json.loads(_PASSAGES_FILE.read_text(encoding="utf-8"))["passages"]
                    if _PASSAGES_FILE.exists() else None)
_EPISODES_FILE = _SECTIONS_FILE.parent / "episodes.json"
EPISODES = ({e["id"]: e for e in json.loads(_EPISODES_FILE.read_text(encoding="utf-8"))["episodes"]}
            if _EPISODES_FILE.exists() else {})


def passage_oeuvres(cid: int, title: str) -> dict | None:
    """{ouvrage, periode, episode, importance, ecrit_apres_coup?} d'un passage des Œuvres, ou None s'il est écarté
    (date incertaine, texte de l'éditeur ou d'un tiers)."""
    sec = section_oeuvres(title)
    if PASSAGES_OEUVRES is None:            # pas encore de datation par passage : la section seule
        return None if sec.get("editeur") else sec
    p = PASSAGES_OEUVRES.get(str(cid))
    if not p:
        return None
    ep = EPISODES.get(p["episode"], {})
    return {"ouvrage": sec["ouvrage"], "periode": p["date"] or sec.get("periode", ""),
            "episode": ep.get("titre", p["episode"]), "importance": p.get("importance", 2),
            **({"ecrit_apres_coup": True} if p.get("nature") == "retrospectif" else {})}


def section_oeuvres(title: str) -> dict:
    """{ouvrage, periode, editeur} d'une section des Œuvres (titre brut de la base)."""
    sec = OEUVRES_SECTIONS.get((title or "").strip(), {})
    deb, fin = sec.get("debut") or "", sec.get("fin") or ""
    periode = deb if deb == fin else " → ".join(x for x in (deb, fin) if x)
    return {"ouvrage": sec.get("titre") or (title or "Œuvres").strip().rstrip("."),
            **({"periode": periode} if periode else {}), **({"editeur": True} if sec.get("editeur") else {})}


def _sans_accents(texte: str) -> str:
    texte = unicodedata.normalize("NFKD", (texte or "").lower())
    return "".join(c for c in texte if not unicodedata.combining(c))
from llm_connector import parse_json_object

AGENT_MODEL = os.getenv("AGENT_MODEL", "gpt-4.1-mini")
MAX_AGENT_STEPS = int(os.getenv("AGENT_MAX_STEPS", "14"))

_MOT_RE = re.compile(r"\w+", re.UNICODE)

# Une lettre longue est découpée en plusieurs passages dans la base : l'archiviste, le narrateur, les
# notes et les sources travaillent sur la LETTRE entière (passages d'un même tome, même en-tête
# numéroté, même date), identifiée par son premier passage.
_TITRE_NUMEROTE = re.compile(r"^\s*\d{1,5}\.\s")
# Écrits de Napoléon pris en compte pour repérer une lacune des archives entre deux lettres racontées
_ECRITS_NAPOLEON = ("napoleon_letter", "napoleon_order", "napoleon_proclamation", "bulletin")
LACUNE_MIN_JOURS = int(os.getenv("LACUNE_MIN_JOURS", "14"))
# Deux variantes racontent le même passage : leurs lettres sont du même jour ou de jours voisins.
VARIANTE_MAX_JOURS = 3
# En dessous de ce nombre de lettres, l'épisode est trop pauvre pour réclamer des variantes.
VARIANTES_MIN_LETTRES = 8
# Au-delà, un plan mélange probablement plusieurs épisodes (avertissement renvoyé à l'archiviste).
EPISODE_MAX_MOIS = 24


PLAN_MAX_JOURS = 3 * 366   # un épisode : trois ans au plus


def _ecart_jours(a: str, b: str) -> int | None:
    try:
        return abs((dt.date.fromisoformat(a[:10]) - dt.date.fromisoformat(b[:10])).days)
    except ValueError:
        return None


def build_letter_index(conn) -> tuple[dict[int, int], dict[int, list[int]]]:
    """(passage → lettre, lettre → passages dans l'ordre du volume)."""
    groupes: dict[tuple, list[tuple[str, int]]] = {}
    for cid, key, source_type, kind, title, date in conn.execute(
            "SELECT id, chunk_key, source_type, source_kind, title, date_iso FROM chunks"):
        titre = (title or "").strip()
        if kind != "memoir" and date and titre and (_TITRE_NUMEROTE.match(titre)
                                                    or source_type == "lettres-amour-imperiales"):
            groupes.setdefault(((key or "").rsplit("_", 1)[0], titre, date), []).append((key or "", cid))
        else:
            groupes[("seul", cid)] = [(key or "", cid)]
    lettre_de, passages = {}, {}
    for membres in groupes.values():
        ids = [cid for _, cid in sorted(membres)]
        passages[ids[0]] = ids
        for cid in ids:
            lettre_de[cid] = ids[0]
    return lettre_de, passages


def _retrouver_citation(citation: str, lettre: str, seuil: float = 0.85) -> str | None:
    """Retrouve la citation dans la lettre et renvoie le texte EXACT de la lettre.

    Tolère les écarts de ponctuation, d'espaces, d'apostrophes et un mot ou deux recopiés de travers ;
    une paraphrase (ratio < seuil) est rejetée.
    """
    q = [m.group().lower() for m in _MOT_RE.finditer(citation)]
    mots = list(_MOT_RE.finditer(lettre))
    if len(q) < 4 or not mots:
        return None
    low = [m.group().lower() for m in mots]
    meilleur, pos = 0.0, None
    for taille in {len(q) - 2, len(q) - 1, len(q), len(q) + 1, len(q) + 2}:
        if taille < 1:
            continue
        for i in range(0, max(1, len(low) - taille + 1)):
            if low[i] != q[0] and low[min(i + taille, len(low)) - 1] != q[-1]:
                continue   # ni le premier ni le dernier mot ne collent : inutile de comparer
            r = SequenceMatcher(None, q, low[i:i + taille], autojunk=False).ratio()
            if r > meilleur:
                meilleur, pos = r, (i, min(i + taille, len(low)) - 1)
    if meilleur < seuil or pos is None:
        return None
    debut, fin = mots[pos[0]].start(), mots[pos[1]].end()
    extrait = lettre[debut:fin]
    # garder la ponctuation finale de la phrase si elle suit immédiatement
    if fin < len(lettre) and lettre[fin] in ".!?…":
        extrait += lettre[fin]
    return " ".join(extrait.split())


CITATION_PROMPT = """\
Tu choisis, dans des lettres de Napoléon, les phrases que le visiteur l'entendra prononcer de vive voix \
pendant qu'il raconte. Le visiteur n'a pas la lettre sous les yeux : la phrase doit avoir du sens seule.

C'est à toi de juger. Mets-toi à la place du visiteur qui écoute, sans la lettre sous les yeux : \
cette phrase, dite à voix haute, le touchera-t-elle, l'éclairera-t-elle, lui fera-t-elle entendre Napoléon \
lui-même ? Ce qui porte en général : une pensée, un sentiment, un jugement, une décision, une image forte, \
une formule qui dit l'homme ou le moment (« Soldats, je suis content de vous. », « À quoi tient la destinée \
des hommes et des empires ! »). Ce qui sonne creux à l'oreille : une liste, des effectifs, un itinéraire, \
un ordre administratif, une formule de politesse, une phrase qui n'a de sens qu'avec ce qui l'entoure — \
même si elle « montre la rigueur » de Napoléon.

Tu peux retenir une phrase, deux, ou aucune : si rien ne mérite d'être entendu, n'en retiens aucune, \
le récit s'en passera très bien. Évite de reprendre ce qui a déjà été cité.

Pour chaque phrase retenue, dis d'abord pourquoi elle portera auprès du visiteur, puis recopie-la \
MOT POUR MOT (une ou deux phrases complètes, courtes à dire). \
Réponds uniquement en JSON : {"citations": [{"lettre": <id>, "pourquoi": "...", "texte": "..."}]}"""


# ---------------------------------------------------------------------------
# Prompt de l'archiviste
# ---------------------------------------------------------------------------

ARCHIVIST_PROMPT = """\
Tu es l'archiviste de la correspondance de Napoléon Bonaparte. Tu prépares, tour après tour, \
le récit que Napoléon fait de sa vie à un visiteur, depuis Sainte-Hélène. Tu ne parles jamais \
au visiteur : tu enquêtes avec tes outils puis tu transmets au narrateur ce qu'il doit raconter.

Le visiteur peut t'écrire dans une autre langue que le français (anglais, espagnol…). Le corpus est en français : comprends sa demande, mais fais toujours tes recherches, tes titres et tes résumés en français (la traduction est faite au moment de la narration).

Deux façons de converser :
- le RÉCIT GUIDÉ (plan, moments, variantes, pistes proposées) : quand le visiteur veut qu'on lui \
raconte un épisode et se laisse conduire ;
- la CONVERSATION LIBRE : le visiteur veut parler avec Napoléon à sa façon. Il lui pose des questions directes \
(sur un homme, une décision, un sentiment, une opinion), rebondit sur ce qu'il vient d'entendre, \
le contredit ou bavarde.
C'est à toi de juger, d'après ses messages, laquelle il souhaite, et de suivre son élan. En conversation \
libre, ne le ramène pas de force dans le récit et ne lui impose pas de choix qu'il n'a pas demandés : \
Napoléon répond à ce qu'on lui demande. Termine alors par repondre_librement, avec dans « lettres » \
les 1 à 3 lettres qui fondent la réponse (trouvées par tes recherches, comme pour le récit), et dans \
« consigne » la question à laquelle répondre, ce que les lettres disent réellement (à qui elles sont \
adressées, de qui elles parlent, et si elles n'y répondent qu'en partie), et s'il convient ou non de relancer. \
N'y ajoute aucun jugement que les lettres ne portent pas. Le récit \
en cours et ses pistes restent en attente : le visiteur pourra y revenir quand il voudra.

Tes responsabilités :
1. Comprendre ce que veut le visiteur (nouveau sujet, choix d'une piste proposée, suite du récit, \
détail précis, conversation libre, simple échange).
   Une question sur une longue période (« la Révolution », « l'Empire ») ne se raconte pas d'un bloc : un plan \
couvre UN épisode (quelques mois, trois ans au plus). Prends le premier épisode de la période qui a des sources \
(lettres ou Œuvres) ; si ce qui le précède n'en a pas, le narrateur le dit en une phrase. Les épisodes suivants \
se proposent ensuite, en transition.
2. Enquêter quand c'est nécessaire : situer la période (chronologie), mesurer la matière \
disponible (explorer_periode), chercher (rechercher / rechercher_mots), lire les lettres prometteuses.
   - Formule ta première requête avec les mots du visiteur, sans y ajouter ce que tu crois savoir du sujet : c'est la recherche qui doit te dire où sont les sources, pas ta mémoire.
   - C'est TOI qui choisis le seuil et le nombre de résultats : regarde la distribution des scores \
et le contenu, n'applique pas de seuil aveuglément. Une requête courte donne des scores bas : \
complète par une recherche par période, par mots exacts (lieux, personnes) ou par une requête plus riche.
   - Vérifie la cohérence date / contenu avant de retenir une lettre : écarte les lettres hors sujet, \
mal datées (ex. une bataille de 1815 datée de 1814) ou les rapports de tiers sans valeur pour le récit.
3. Construire un plan avec fixer_plan : une suite de MOMENTS (numérotés dans l'ordre du récit), \
et pour chaque moment 1 à 2 chapitres VARIANTES (titre court, résumé factuel tiré des lettres, 1 à 4 lettres). \
Deux variantes d'un même moment racontent le même passage par des lettres ou des angles différents \
(ex. le débarquement en Égypte : l'ordre d'assaut sur Alexandrie, ou la lettre écrite le soir même \
au Directoire ; Austerlitz : le champ de bataille dans les ordres aux maréchaux, ou la proclamation \
aux soldats et la lettre à Joséphine). Le visiteur choisira l'une des deux ; l'autre sera abandonnée : \
ainsi chaque conversation sur un même sujet suit un chemin unique. \
Si le sujet est pauvre en lettres, fais un plan court (un moment peut n'avoir qu'une variante) \
plutôt que d'inventer.
   - UN plan = UN épisode cohérent (une campagne, une période, un thème bien borné dans le temps). \
Tous les chapitres et toutes les lettres du plan appartiennent à cet épisode : ne mélange JAMAIS \
plusieurs campagnes (ex. 1805 et 1809) dans un même plan.
   - Être de la bonne période ne suffit pas : chaque lettre retenue doit parler DU SUJET de l'épisode. \
Napoléon écrit chaque jour sur mille affaires ; une lettre du même mois sur une autre affaire \
(ex. pendant la campagne de Marengo, la pacification de l'Ouest ou une expédition outre-mer) \
n'a pas sa place dans le plan. explorer_periode sert à mesurer la matière ; pour choisir les lettres, \
cherche par le sujet (rechercher, rechercher_mots sur les lieux et les personnes de l'épisode).
   - Si la demande est vague (« une victoire », « une bataille », « votre jeunesse »), choisis toi-même \
UN épisode précis, riche en lettres, et donne-lui un intitulé explicite qui le situe : \
« La campagne de 1805 contre l'Autriche : d'Ulm à Austerlitz », et des dates periode_debut / periode_fin.
   - Les pistes proposées restent dans l'épisode en cours. Un autre épisode ne se propose qu'en \
transition, quand l'épisode est épuisé.
   - Proportionne le plan à la matière : si explorer_periode montre des dizaines de lettres, \
lis 6 à 12 candidates choisies d'après leurs extraits (rechercher puis lire_lettres) et bâtis 3 à 6 moments qui \
couvrent l'épisode dans l'ordre chronologique (préparatifs, tournants, apogée, conséquences), \
avec deux variantes pour les moments où deux lettres racontent le même passage (même jour ou jours voisins : \
des lettres éloignées de plus de 3 jours forment des moments successifs, jamais des variantes). \
Un plan d'un seul moment n'est acceptable que si les lettres manquent vraiment.
   - Commence le récit au début de l'épisode, sauf si le visiteur demande un moment précis. Un moment sans
lettre a sa place dans le plan s'il a des passages des Œuvres (memoires) : donne-lui ces passages et une date, et
sers-le à son tour (servir_tour avec lettres vides). Un moment sans lettre ni passage des Œuvres n'a pas de source :
il n'entre pas dans le plan.
   - Une demande de récit (« parle-moi de… », « raconte… », « et le sacre ? ») appelle l'enquête, le plan et servir_tour DÈS CE TOUR. Ne réponds jamais par repondre_librement en annonçant un épisode que tu n'as pas préparé, et ne fais pas choisir au visiteur entre des moments sans lettres pour les raconter.
   - Contrôle la cohérence de chaque lettre avant de la retenir : une lettre qui évoque \
« l'anniversaire » d'une bataille ne peut pas dater du jour de cette bataille ; une lettre qui \
mentionne des faits postérieurs à sa date est mal datée → écarte-la.
4. Servir le tour avec servir_tour : le chapitre à raconter maintenant, 1 à 3 lettres (de préférence \
1 ou 2), éventuellement 1 à 2 passages des Œuvres de Napoléon (écrits des campagnes et du règne \
réunis après coup, pas des souvenirs de l'exil) quand ils éclairent le moment raconté (pas à chaque tour), \
et les pistes à proposer pour la suite :
   - les pistes portent sur LE MÊME passage : les 2 variantes du moment suivant (jamais deux moments \
éloignés, jamais un saut de plusieurs mois) — c'est la règle dès que ce moment a 2 variantes ;
   - 1 piste si le moment suivant n'a qu'une variante ;
   - aucune piste si tout est raconté : indique alors une transition vers un autre moment de la vie \
de Napoléon pour lequel tu as vérifié qu'il existe des lettres.
5. Aux tours suivants : si le visiteur choisit une piste (même implicitement : un lieu, une personne, \
« la seconde »…), sers ce chapitre ; l'autre variante est abandonnée automatiquement. S'il demande un détail ou un moment qui relève du sujet en cours \
(une personne, une date, un épisode de la même période), fais une recherche ciblée et RÉVISE le plan : \
fixer_plan avec EXACTEMENT le même intitulé de sujet, en gardant les chapitres encore pertinents et en \
ajoutant/réordonnant ce qu'il faut (les chapitres déjà racontés sont conservés automatiquement). \
Ne change d'intitulé de sujet que si le visiteur passe vraiment à une autre période ou un autre thème : \
nouvelle enquête et nouveau plan.
6. Pour une salutation, un échange sans rapport avec la correspondance ou une conversation libre, \
utilise repondre_librement (tu peux d'abord chercher une lettre marquante pour proposer un sujet concret, \
ou les lettres qui répondent à la question du visiteur).
7. Lettre tirée au hasard (premier tour) : quand le contexte fournit des « lettres tirées au hasard » \
et que le visiteur salue ou ne précise pas de sujet, laisse le hasard orienter la conversation : \
garde celle dont la « phrase citable » est la plus forte (à défaut, la plus évocatrice), situe son épisode (chronologie, au besoin lire_lettres), \
puis repondre_librement avec lettre_amorce = son id et une consigne : saluer le visiteur, dire que \
Napoléon était justement en train de relire cette lettre, en faire entendre une phrase, puis \
proposer d'évoquer l'épisode qu'elle ouvre (nommé clairement, avec l'année) — ou autre chose s'il préfère. \
Le hasard ne sert qu'à ouvrir la conversation quand le visiteur n'apporte rien. Une question, même large \
ou vague (« pourquoi as-tu perdu la guerre ? », « qu'as-tu fait de bien ? »), est déjà un sujet : ignore ces \
lettres, enquête sur la question et réponds-y (récit guidé ou conversation libre, selon ce qu'il semble attendre). \
Les lettres d'une réponse viennent toujours de tes recherches sur la question, jamais du tirage.
   Plus tard dans la conversation, quand le visiteur veut autre chose sans dire quoi, le hasard peut \
de nouveau ouvrir la voie : tirer_au_hasard te donne d'autres lettres, et tu procèdes de la même façon \
(sans saluer à nouveau : la conversation continue). C'est à toi de juger quand c'est le meilleur choix. \
Ne propose pas un épisode de mémoire, sans lettre pour l'appuyer.
   Au tour suivant, si le visiteur accepte l'épisode proposé, construis le plan de CET épisode \
en y intégrant la lettre amorce.

8. Napoléon parle depuis Sainte-Hélène, au printemps 1821 : il ne sait rien de ce qui vient après \
(sa mort, la suite de l'histoire, les inventions, les pays et les personnes d'après). \
   - Pour toute question sur sa vie, cherche dans cet ordre et dis au narrateur, dans la consigne, d'où vient \
ce qu'il raconte :
     1. les lettres (rechercher, rechercher_mots) : le récit ou la réponse s'appuie sur elles ;
     2. ses Œuvres (memoires) : cherche-y aussi, en UNE ou DEUX recherches au plus, et joins 1 à 2 passages qui
éclairent le sujet (servir_tour.memoires ou repondre_librement.memoires). Sans lettre, Napoléon dit qu'il n'a pas
de lettre sur ce sujet, et nomme l'écrit dont vient le passage ;
     3. sinon, PAS DE SOURCE : repondre_librement, sans lettre ni passage, avec pour consigne de dire simplement
que Napoléon n'a aucune source écrite sur ce sujet, sans le raconter, et de proposer un autre sujet dont tu as
vérifié les lettres. La fiche personnelle n'est pas une source : elle t'oriente (dates, épisodes, quel sujet
proposer), mais rien de ce qu'elle dit n'est transmis au narrateur.
   - La consigne ne contient aucun fait que tes sources ne donnent pas : ni nom, ni date, ni lieu tirés de ta \
propre connaissance. Ce que tu sais par toi-même mais n'as trouvé nulle part n'existe pas pour Napoléon.
   - Une question sur ce qui est postérieur à 1821 ou étranger à son temps : repondre_librement, sans lettre \
ni passage, avec pour consigne que Napoléon ne sait pas de quoi parle le visiteur et le dit en homme de son temps, \
sans faire semblant de savoir, puis ramène la conversation vers sa vie.
   - Une question à laquelle ni les lettres ni les Œuvres ne répondent : repondre_librement, sans lettre ni passage, \
avec pour consigne de ne pas la traiter sur le fond et de proposer un sujet dont tu as vérifié les lettres. \
Ne demande jamais au narrateur de répondre de mémoire.

9. Mise en scène : avec servir_tour ou repondre_librement, tu peux régler le décor de Longwood pour ce tour.
   - meteo : le temps derrière la fenêtre, accordé au ton (brume pour l'exil et les regrets, orage pour une bataille
ou un désastre, pluie pour un deuil, clair pour un récit serein). Change-le quand le ton change, pas à chaque tour.
   - carte : la région de l'épisode raconté, qui s'éclaire sur la carte murale ; à renseigner dès qu'un récit
se situe quelque part (italie, egypte, autriche, russie, espagne, belgique…).
   - lumiere : l'éclairage de la pièce. normale pour la conversation et les récits ; penombre (la pièce baisse, la
lueur du feu sur lui) pour une confidence, un regret, un deuil, la captivité ; projecteur (pièce dans le noir, une
seule lumière sur lui) très rarement, pour un moment solennel : une proclamation, un testament, un adieu. Reviens
à normale quand le ton redevient ordinaire.
   - musique : un fond musical accordé au récit (solennelle, melancolique, tendre, triomphale, marseillaise), ou
aucune pour une simple conversation. Choisis-la au début d'un épisode et change-la quand le ton change vraiment, pas
à chaque tour ; aucune musique vaut mieux qu'une musique à contresens. La musique est un accent, pas un fond
permanent : elle ne se fait entendre que pendant les citations (ses propres mots entre « »), et la plupart des tours
n'en ont pas. « marseillaise » est un chant précis, pas une musique de bataille :
réserve-la, très rarement, à un moment où ce chant a sa place (les armées de la République, une proclamation
républicaine, le départ pour l'Italie en 1796) ; jamais pour une campagne de l'Empire. Pas de musique pour un salut, l'accueil du
visiteur ou une lettre tirée au hasard pour ouvrir la conversation : elle ne commence qu'avec un récit.
   - tableau : une œuvre de ton catalogue (cherche-la avec l'outil tableaux) épinglée au tableau mural, seulement quand elle montre vraiment le
moment raconté (le sacre, Arcole, Jaffa, Austerlitz…) ; « aucun » pour l'enlever quand le récit passe à autre chose.
Choisis l'œuvre d'après le SUJET du récit (la personne, l'événement, le moment), jamais d'après le lieu d'où la
lettre est écrite : une lettre d'amour à Joséphine envoyée de Milan appelle un portrait de Joséphine, pas un
tableau de la campagne d'Italie. Lis la description de l'œuvre (outil tableaux) : elle dit ce qu'elle montre,
quand l'épingler et quand s'en abstenir. Si aucune ne montre le sujet, mets « aucun ».
Le tableau sert au visiteur, pas à Napoléon : beaucoup d'œuvres ont été peintes après 1821 et il ne peut pas les
connaître. Ne demande jamais au narrateur d'en parler ; son cartel donne sa date.
Dès que le sujet change (nouvel épisode, ou réponse libre sur autre chose), renseigne-le toujours, avec
servir_tour comme avec repondre_librement : l'œuvre du nouveau sujet, ou « aucun » — jamais l'œuvre d'un autre
sujet laissée en place.

Les lettres :
- Chaque identifiant désigne une LETTRE entière, même si elle est longue (« passages » : nombre de morceaux \
dans la base ; lire_lettres en donne le début, « suite_non_lue » signale qu'elle continue). Une lettre ne \
figure que dans un seul chapitre : deux variantes ne sont jamais deux morceaux d'une même lettre.
- « date_incertaine » : la date de ce texte est douteuse ; ne le retiens pas dans un plan chronologique.
- Le type « memoir » désigne un récit écrit après coup (Œuvres de Sainte-Hélène…), pas une lettre du moment.
- Sujet pauvre en lettres : un moment par lettre, une seule variante si besoin. Ne fabrique pas de choix \
en coupant la matière : mieux vaut un récit court et complet qu'un choix qui fait perdre la moitié des lettres.

Règles :
- Tout ce que Napoléon racontera doit venir des lettres et des passages des Œuvres servis : choisis-les avec soin.
- Ne sers jamais une lettre déjà racontée, sauf si le visiteur le demande expressément.
- Sois efficace : une enquête complète tient en 3 à 8 appels d'outils ; un tour de suite en 0 à 2.
- Termine TOUJOURS par servir_tour ou repondre_librement.
"""

# ---------------------------------------------------------------------------
# Schémas d'outils (OpenAI function calling)
# ---------------------------------------------------------------------------

# Mise en scène choisie par l'archiviste à chaque tour (affichée par l'interface, jamais racontée)
METEOS = ["clair", "brume", "pluie", "orage"]
LUMIERES = ["normale", "penombre", "projecteur"]
MUSIQUES = ["aucune", "solennelle", "melancolique", "tendre", "triomphale", "marseillaise"]
# Œuvres que l'archiviste peut épingler au tableau mural (napoleon-corpus/metadata/tableaux.json,
# images dans web/decor/tableaux/) : toutes peintes de son vivant.
_TABLEAUX_FILE = Path(__file__).resolve().parent.parent / "napoleon-corpus" / "metadata" / "tableaux.json"
try:
    TABLEAUX = {t["id"]: t for t in json.loads(_TABLEAUX_FILE.read_text(encoding="utf-8"))}
except (OSError, json.JSONDecodeError):
    TABLEAUX = {}
CARTES = ["corse", "france", "italie", "egypte", "espagne", "autriche", "prusse", "pologne", "allemagne", "russie", "belgique", "angleterre", "elbe", "sainte_helene"]
_SCENE = {
    "meteo": {"type": "string", "enum": METEOS,
               "description": "Le temps derrière la fenêtre de Longwood, accordé au ton du tour : clair (récit serein), "
                              "brume (exil, mélancolie, souvenirs flous), pluie (tristesse, deuil, attente), "
                              "orage (bataille, colère, désastre). Facultatif : sans valeur, le temps ne change pas."},
    "carte": {"type": "string", "enum": CARTES,
               "description": "Région à éclairer sur la carte murale : le lieu de l'épisode raconté (ex. italie pour "
                              "1796, autriche pour Austerlitz, russie pour 1812, belgique pour Waterloo). "
                              "Facultatif : sans valeur, la carte reste comme elle est."},
    "lumiere": {"type": "string", "enum": LUMIERES,
                "description": "Éclairage de la pièce, accordé au ton : normale (conversation, récit), penombre "
                               "(confidence, regret, deuil, captivité), projecteur (rare : moment solennel, "
                               "proclamation, adieu). Facultatif : sans valeur, l'éclairage ne change pas."},
    "musique": {"type": "string", "enum": MUSIQUES,
                "description": "Musique de fond, jouée doucement sous la voix : aucune (conversation, simple échange), "
                               "solennelle (sacre, proclamation, grand moment d'État), melancolique (exil, défaite, "
                               "deuil, regrets), tendre (Joséphine, son fils, la famille), triomphale (victoire, entrée "
                               "dans une capitale), marseillaise (La Marseillaise elle-même : très rare, seulement quand "
                               "ce chant a sa place, sous la République). "
                               "Facultatif : sans valeur, la musique ne change pas."},
    "tableau": {"type": "string", "enum": ["aucun"] + list(TABLEAUX),
                "description": "Œuvre à épingler au tableau mural, quand elle montre le moment raconté : un "
                               "identifiant trouvé avec l'outil tableaux. aucun : l'enlever. Facultatif : sans "
                               "valeur, l'œuvre affichée ne change pas."},
}


def _fn(name, description, properties=None, required=None):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties or {}, "required": required or []},
    }}

_PERIODE = {
    "date_debut": {"type": "string", "description": "Début de période YYYY-MM ou YYYY-MM-DD (optionnel)."},
    "date_fin":   {"type": "string", "description": "Fin de période YYYY-MM ou YYYY-MM-DD (optionnel)."},
}

TOOLS = [
    _fn("chronologie", "Liste des grands événements de la vie de Napoléon avec leurs dates."),
    _fn("explorer_periode",
        "Vue d'ensemble d'une période : nombre de lettres, répartition par mois et par type de source, "
        "destinataires/titres les plus fréquents, échantillon de lettres (id, date, titre).",
        {"date_debut": _PERIODE["date_debut"], "date_fin": _PERIODE["date_fin"]},
        ["date_debut", "date_fin"]),
    _fn("rechercher",
        "Recherche sémantique dans tout ce que Napoléon a écrit ou sait : ses lettres (resultats, triés par score "
        "cosinus, avec un extrait et la distribution des scores), les passages de ses Œuvres (oeuvres : ids à "
        "donner dans « memoires ») et les faits de sa fiche (fiche : pour t'orienter seulement, jamais transmis au narrateur). Compare les "
        "listes : la meilleure réponse peut venir de ses Œuvres ou de sa fiche quand les lettres ne parlent pas du sujet.",
        {"requete": {"type": "string", "description": "Requête riche en contenu (lieux, personnes, faits)."},
         **_PERIODE,
         "seuil_min": {"type": "number", "description": "Score minimal (0 à 1). Défaut 0."},
         "limite": {"type": "integer", "description": "Nombre de résultats (1-50). Défaut 20."}},
        ["requete"]),
    _fn("rechercher_mots",
        "Recherche exacte (insensible à la casse) de mots ou expressions dans le texte des lettres.",
        {"mots": {"type": "array", "items": {"type": "string"}, "description": "Mots/expressions (OU logique)."},
         **_PERIODE,
         "limite": {"type": "integer", "description": "Nombre de résultats (1-50). Défaut 25."}},
        ["mots"]),
    _fn("lire_lettres", "Texte des lettres (6 maximum par appel, 1000 caractères chacune). "
        "Ne lis que les candidates les plus prometteuses d'après les extraits.",
        {"ids": {"type": "array", "items": {"type": "integer"}}}, ["ids"]),
    _fn("tirer_au_hasard",
        "Tire 5 lettres au hasard dans toute la correspondance (jamais déjà racontées), chacune avec un extrait "
        "et sa « phrase citable ». Utile quand le visiteur veut autre chose sans dire quoi : le hasard d'une "
        "lettre ouvre un sujet concret, tiré des archives plutôt que de la mémoire générale."),
    _fn("memoires", "Recherche dans les Œuvres de Napoléon Bonaparte (éd. Panckoucke) : écrits des campagnes "
        "et du règne réunis après coup. Ce ne sont pas des souvenirs de Sainte-Hélène.",
        {"requete": {"type": "string"},
         "limite": {"type": "integer", "description": "1-8, défaut 4."},
         "date_debut": {"type": "string", "description": "Facultatif : YYYY, YYYY-MM ou YYYY-MM-DD."},
         "date_fin": {"type": "string", "description": "Facultatif : YYYY, YYYY-MM ou YYYY-MM-DD."}},
        ["requete"]),
    _fn("tableaux",
        "Cherche dans le catalogue des œuvres (tableaux, gravures, portraits) que tu peux épingler au tableau mural "
        "(champ « tableau »). Chaque œuvre : identifiant, titre, peintre, date de l'œuvre, sujet. Beaucoup ont été "
        "faites après 1821 : elles servent au visiteur, Napoléon ne les connaît pas.",
        {"mots": {"type": "string", "description": "Mots du sujet : lieu, bataille, personne, événement (ex. « Wagram », "
                                                   "« Joséphine », « retraite de Russie »)."}},
        ["mots"]),
    _fn("fiche_personnelle",
        "Le savoir de Napoléon sur sa propre vie, sans ses lettres, tel qu'il le connaît au printemps 1821 : "
        "famille, jeunesse, chaque campagne et chaque période, ses proches et ses maréchaux, l'exil, et ce qu'il "
        "ne sait pas. Elle t'oriente (dates, épisodes, sujets à proposer) ; ses faits ne sont jamais transmis au narrateur. "
        "Sans argument : la liste des rubriques. Avec « rubrique » : les faits d'une rubrique. Avec « mots » : "
        "les faits qui contiennent ces mots (noms, lieux, années).",
        {"rubrique": {"type": "string", "description": "Optionnel : une rubrique (ex. « Jeunesse », « Empire », « exil »)."},
         "mots": {"type": "string", "description": "Optionnel : mots à chercher (ex. « sacre Notre-Dame Pie VII »)."}}),
    _fn("fixer_plan",
        "Fixe ou révise le plan du récit. Remplace tous les chapitres NON racontés par ceux fournis "
        "(les chapitres déjà racontés sont conservés).",
        {"sujet": {"type": "string", "description": "Titre du sujet (ex. « L'exil à l'île d'Elbe »)."},
         "periode_debut": {"type": "string", "description": "YYYY-MM-DD"},
         "periode_fin": {"type": "string", "description": "YYYY-MM-DD"},
         "chapitres": {"type": "array", "items": {"type": "object", "properties": {
             "moment": {"type": "integer", "description": "Numéro du moment dans l'ordre du récit (1, 2, 3…). "
                        "Deux chapitres du même moment sont deux variantes du même passage."},
             "titre": {"type": "string"},
             "resume": {"type": "string", "description": "1-2 phrases factuelles tirées des sources du chapitre."},
             "lettres": {"type": "array", "items": {"type": "integer"},
                         "description": "Lettres du chapitre ; vide si le moment n'a pas de lettre."},
             "memoires": {"type": "array", "items": {"type": "integer"},
                          "description": "Passages des Œuvres (ids de l'outil memoires ou de rechercher) sur ce moment."},
             "date": {"type": "string", "description": "YYYY-MM : date du moment, obligatoire s'il n'a pas de lettre."},
         }, "required": ["titre", "resume", "lettres"]}}},
        ["sujet", "chapitres"]),
    _fn("servir_tour",
        "Termine le tour : transmet au narrateur le chapitre à raconter, les lettres, les passages des "
        "Œuvres éventuels et les pistes à proposer au visiteur.",
        {"chapitre": {"type": "string", "description": "Identifiant du chapitre (ex. c2)."},
         "lettres": {"type": "array", "items": {"type": "integer"}, "description": "1 à 3 lettres à raconter ; vide pour un chapitre sans lettre."},
         "memoires": {"type": "array", "items": {"type": "integer"}, "description": "0 à 2 passages des Œuvres de Napoléon (outil memoires)."},
         "pistes": {"type": "array", "items": {"type": "string"}, "description": "0 à 2 identifiants de chapitres non racontés : les variantes du moment suivant."},
         "transition": {"type": "string", "description": "Si aucune piste : moment de la vie vers lequel proposer d'enchaîner."},
         "note": {"type": "string", "description": "Consigne courte au narrateur (angle, émotion, lien avec la demande)."},
         **_SCENE},
        ["chapitre", "lettres", "pistes"]),
    _fn("repondre_librement",
        "Termine le tour hors du récit guidé : salutation, échange, question hors correspondance, "
        "ou conversation libre où Napoléon répond directement au visiteur, sans plan ni choix à proposer.",
        {"consigne": {"type": "string", "description": "Ce que Napoléon doit dire ou à quoi il répond, sous quel angle, "
                      "et s'il relance ou non, en une ou deux phrases."},
         "lettres": {"type": "array", "items": {"type": "integer"},
                     "description": "Optionnel : 1 à 3 lettres sur lesquelles Napoléon fonde sa réponse (conversation libre)."},
         "memoires": {"type": "array", "items": {"type": "integer"},
                      "description": "Optionnel : 1 à 2 passages de ses Œuvres (outil memoires) quand aucune lettre ne répond."},
         "lettre_amorce": {"type": "integer", "description": "Optionnel : une lettre dont citer un détail pour proposer un sujet."},
         **_SCENE},
        ["consigne"]),
]

TERMINAL_TOOLS = {"servir_tour", "repondre_librement"}


# ---------------------------------------------------------------------------
# Archiviste
# ---------------------------------------------------------------------------

def _norm_start(d: str | None) -> str | None:
    return d.strip() if d else None

def _norm_end(d: str | None) -> str | None:
    return (d.strip() + "\xff") if d else None


class Archivist:
    def __init__(self, client, conn, emb_matrix, chunk_ids, m_conn, m_matrix, m_ids, events,
                 model: str = AGENT_MODEL, embed_client=None):
        self.client = client              # modèle de l'agent (connecteur universel, compatible OpenAI)
        self.embed_client = embed_client  # embeddings OpenAI, optionnels (recherche sémantique)
        self._fiche_emb = None            # vecteurs des faits de la fiche, calculés à la première recherche
        # Textes écartés des recherches (recueil jugé apocryphe : docs/LETTRES_INEDITES.md)
        self.ecartes = {r[0] for r in conn.execute("SELECT id FROM chunks WHERE source_kind LIKE 'apocryphe%'")}
        self.conn = conn
        self.emb = emb_matrix
        self.ids = np.array(chunk_ids)
        self.m_conn, self.m_emb, self.m_ids = m_conn, m_matrix, (np.array(m_ids) if m_ids else None)
        self.events = events
        self.model = model
        self.lettre_de, self.passages = build_letter_index(conn)

    # ── Lettres entières ────────────────────────────────────────────────────
    def lettre(self, cid) -> int:
        """Identifiant de la lettre (son premier passage) à laquelle appartient un passage."""
        return self.lettre_de.get(int(cid), int(cid))

    def lettres(self, ids) -> list[int]:
        """Identifiants de lettres, sans doublon, dans l'ordre donné."""
        out = []
        for i in ids or []:
            try:
                lid = self.lettre(i)
            except (TypeError, ValueError):
                continue
            if lid not in out:
                out.append(lid)
        return out

    def textes(self, ids, limite: int | None = None) -> list[dict]:
        """Lettres entières : métadonnées du premier passage, texte de tous les passages réunis."""
        out = []
        for lid in self.lettres(ids):
            parts = fetch_chunks(self.conn, self.passages.get(lid, [lid]))
            if not parts:
                continue
            texte = "\n".join((c.get("text") or "").strip() for c in parts)
            lettre = dict(parts[0])
            lettre["id"], lettre["nb_passages"] = lid, len(parts)
            lettre["tronquee"] = bool(limite and len(texte) > limite)
            lettre["text"] = texte[:limite] if limite else texte
            out.append(lettre)
        return out

    # ── Session ─────────────────────────────────────────────────────────────
    @staticmethod
    def new_state() -> dict:
        return {"plan": None, "chapitres": [], "racontees": [], "pistes": [], "tour": 0,
                "derniere_reponse": "", "amorce": None, "citations_dites": []}

    def _random_letters(self, n: int = 5, exclure=()) -> list[dict]:
        """Lettres tirées au hasard pour amorcer un sujet (lettres/proclamations de Napoléon, datées)."""
        exclure = set(self.lettres(exclure))
        rows = self.conn.execute(
            "SELECT id FROM chunks WHERE length(date_iso) = 10 AND date_reliable != 0 "
            "AND source_kind IN ('napoleon_letter','napoleon_proclamation') AND length(text) > 400 "
            "ORDER BY RANDOM() LIMIT ?", (n * 4,)).fetchall()
        tirees = [l for l in self.lettres(r[0] for r in rows) if l not in exclure][:n]
        letters = [{"id": l["id"], "date": l.get("date_iso"), "titre": (l.get("title") or "")[:80],
                    "extrait": (l.get("text") or "").replace("\n", " ")}
                   for l in self.textes(tirees, limite=700)]
        choix = {c["lettre"]: c for c in self._choisir_citations(
            None, [l["id"] for l in letters],
            "Premier tour : pour CHAQUE lettre, retiens la phrase que tu ferais entendre pour donner envie "
            "d'en savoir plus, ou aucune si elle n'en contient pas.", par_lettre=True)}
        for l in letters:
            c = choix.get(l["id"])
            l["phrase_citable"] = f"« {c['texte']} »" if c else "(aucune)"
        return letters

    # ── Choix des citations (appel dédié : l'agent juge seul) ───────────────
    def _choisir_citations(self, state, lettres: list[int], contexte: str, par_lettre: bool = False) -> list[dict]:
        """L'agent choisit 0 à 2 citations (ou une par lettre) ; le code vérifie seulement qu'elles sont exactes."""
        chunks = self.textes(lettres, limite=4000)
        if not chunks:
            return []
        dites = (state or {}).get("citations_dites") or []
        corps = "\n\n".join(f"[lettre {c['id']} — {c.get('date_iso') or '?'}]\n{c.get('text') or ''}"
                             for c in chunks)
        demande = (f"{contexte}\n\n"
                   + ("Déjà cité dans la conversation :\n" + "\n".join(f"- « {d} »" for d in dites) + "\n\n" if dites else "")
                   + corps)
        try:
            resp = self.client.chat.completions.create(
                model=self.model, temperature=0.3, response_format={"type": "json_object"},
                messages=[{"role": "system", "content": CITATION_PROMPT}, {"role": "user", "content": demande}])
            cands = parse_json_object(resp.choices[0].message.content).get("citations") or []
        except Exception as exc:
            print(f"[CITATIONS] échec : {exc}")
            return []
        textes = {c["id"]: c.get("text") or "" for c in chunks}
        out = []
        for c in cands:
            try:
                lid = self.lettre(c.get("lettre"))
            except (TypeError, ValueError):
                continue
            if not str(c.get("texte") or "").strip():
                continue   # « aucune » pour cette lettre : choix de l'agent
            exact = _retrouver_citation(str(c.get("texte") or ""), textes.get(lid, ""))
            if exact and exact not in dites:
                out.append({"lettre": lid, "texte": exact})
                print(f"[CITATIONS] {exact[:70]} — {str(c.get('pourquoi') or '')[:80]}")
            else:
                print(f"[CITATIONS] écartée (pas mot pour mot dans la lettre {lid}) : {str(c.get('texte'))[:80]}")
        return out if par_lettre else out[:2]

    # ── Outils ──────────────────────────────────────────────────────────────
    def _ids_in_period(self, start, end) -> set[int] | None:
        if not start and not end:
            return None
        rows = self.conn.execute(
            "SELECT id FROM chunks WHERE date_iso >= ? AND date_iso <= ? AND date_reliable != 0",
            (_norm_start(start) or "0000", _norm_end(end) or "9999\xff")).fetchall()
        return {r[0] for r in rows}

    def _meta(self, ids: list[int]) -> dict[int, tuple]:
        if not ids:
            return {}
        q = ",".join("?" * len(ids))
        rows = self.conn.execute(
            f"SELECT id, date_iso, title, source_kind, substr(text,1,220), date_reliable FROM chunks WHERE id IN ({q})", ids
        ).fetchall()
        return {r[0]: r for r in rows}

    def t_chronologie(self, state):
        return [{"evenement": e["event"], "debut": e["start"], "fin": e["end"]} for e in self.events]

    def t_explorer_periode(self, state, date_debut, date_fin):
        passages = self.conn.execute(
            "SELECT id, date_iso, title, source_kind FROM chunks WHERE date_iso >= ? AND date_iso <= ? "
            "AND date_reliable != 0 ORDER BY date_iso", (_norm_start(date_debut), _norm_end(date_fin))).fetchall()
        rows, vues = [], set()
        for r in passages:            # une ligne par lettre (son premier passage dans la période)
            lid = self.lettre(r[0])
            if lid not in vues:
                vues.add(lid)
                rows.append((lid, *r[1:]))
        par_mois = Counter((r[1] or "?")[:7] for r in rows)
        par_type = Counter(r[3] or "?" for r in rows)
        titres = Counter(" ".join((r[2] or "").split(".")[-1].split()[:6]) for r in rows)
        step = max(1, len(rows) // 40)
        return {
            "total_lettres": len(rows),
            "par_mois": dict(sorted(par_mois.items())),
            "par_type_source": dict(par_type.most_common()),
            "destinataires_frequents": titres.most_common(12),
            "echantillon": [{"id": r[0], "date": r[1], "titre": (r[2] or "")[:90]} for r in rows[::step][:40]],
        }

    def t_rechercher(self, state, requete, date_debut=None, date_fin=None, seuil_min=0.0, limite=20):
        limite = max(1, min(50, int(limite or 20)))
        if self.embed_client is None:
            return {"erreur": "recherche sémantique indisponible (aucune clé d'embeddings OpenAI configurée) : "
                              "cherche avec rechercher_mots (lieux, personnes, mots exacts) et explorer_periode."}
        q = embed_question(self.embed_client, requete)
        sims = cosine_sim(q, self.emb)
        allowed = self._ids_in_period(date_debut, date_fin)
        if allowed is not None:
            mask = np.isin(self.ids, list(allowed))
            idx = np.where(mask)[0]
        else:
            idx = np.arange(len(self.ids))
        if self.ecartes:
            idx = idx[~np.isin(self.ids[idx], list(self.ecartes))]
        scores = sims[idx]
        dist = {}
        if len(scores):
            dist = {"lettres_dans_perimetre": int(len(scores)),
                    "max": round(float(scores.max()), 3),
                    "p90": round(float(np.percentile(scores, 90)), 3),
                    "mediane": round(float(np.median(scores)), 3),
                    **{f"nb>={s}": int((scores >= s).sum()) for s in (0.30, 0.35, 0.40, 0.45, 0.50)}}
        order = idx[np.argsort(-scores)]
        top = [(int(self.ids[i]), float(sims[i])) for i in order if sims[i] >= float(seuil_min or 0)][:limite * 3]
        meta = self._meta([t[0] for t in top])
        racontees = set(self.lettres(state["racontees"]))
        res, vues = [], set()
        for cid, sc in top:           # le meilleur passage de chaque lettre la représente
            m = meta.get(cid)
            lid = self.lettre(cid)
            if not m or lid in vues or len(res) >= limite:
                continue
            vues.add(lid)
            n = len(self.passages.get(lid, [lid]))
            res.append({"id": lid, "date": m[1], "score": round(sc, 3), "type": m[3],
                        "titre": (m[2] or "")[:80], "extrait": (m[4] or "").replace("\n", " ")[:200],
                        **({"passages": n} if n > 1 else {}),
                        **({"date_incertaine": True} if m[5] == 0 else {}),
                        **({"deja_racontee": True} if lid in racontees else {})})
        return {"distribution_scores": dist, "resultats": res, **self._autres_sources(q)}

    def _autres_sources(self, q) -> dict:
        """Avec les lettres, les meilleurs passages des Œuvres et les faits de la fiche les plus proches de la
        requête : la même recherche montre tout ce que Napoléon a écrit ou sait sur le sujet."""
        out = {}
        if self.m_emb is not None:
            sims = cosine_sim(q, self.m_emb)
            oeuvres = []
            for i in np.argsort(-sims)[:40]:
                if len(oeuvres) >= 4:
                    break
                row = self.m_conn.execute("SELECT title, text FROM chunks WHERE id=?", (int(self.m_ids[i]),)).fetchone()
                sec = passage_oeuvres(int(self.m_ids[i]), row[0]) if row else None
                if sec:
                    oeuvres.append({"id": int(self.m_ids[i]), "score": round(float(sims[i]), 3), **sec,
                                    "extrait": (row[1] or "").replace("\n", " ")[:200]})
            out["oeuvres"] = oeuvres
        if NAPOLEON_FICHE:
            if self._fiche_emb is None:
                resp = self.embed_client.embeddings.create(input=[f["texte"] for f in NAPOLEON_FICHE],
                                                           model="text-embedding-3-small")
                self._fiche_emb = np.array([d.embedding for d in resp.data], dtype=np.float32)
            sims = cosine_sim(q, self._fiche_emb)
            out["fiche"] = [{"id": NAPOLEON_FICHE[i]["id"], "score": round(float(sims[i]), 3),
                             "texte": NAPOLEON_FICHE[i]["texte"]} for i in np.argsort(-sims)[:5]]
        return out

    def t_rechercher_mots(self, state, mots, date_debut=None, date_fin=None, limite=25):
        limite = max(1, min(50, int(limite or 25)))
        conds = " OR ".join("lower(text) LIKE ?" for _ in mots)
        params = [f"%{m.lower()}%" for m in mots]
        sql = (f"SELECT id, date_iso, title, source_kind, text, date_reliable FROM chunks WHERE ({conds}) "
               "AND source_kind NOT LIKE 'apocryphe%'")
        if date_debut or date_fin:
            sql += " AND date_iso >= ? AND date_iso <= ? AND date_reliable != 0"
            params += [_norm_start(date_debut) or "0000", _norm_end(date_fin) or "9999\xff"]
        rows = self.conn.execute(sql + " ORDER BY date_iso", params).fetchall()
        racontees = set(self.lettres(state["racontees"]))
        res, vues = [], set()
        for r in rows:
            lid = self.lettre(r[0])
            if lid in vues:
                continue
            vues.add(lid)
            if len(res) >= limite:
                continue
            low = (r[4] or "").lower()
            pos = min((low.find(m.lower()) for m in mots if low.find(m.lower()) >= 0), default=0)
            res.append({"id": lid, "date": r[1], "type": r[3], "titre": (r[2] or "")[:80],
                        "extrait": (r[4] or "")[max(0, pos - 80): pos + 140].replace("\n", " "),
                        **({"date_incertaine": True} if r[5] == 0 else {}),
                        **({"deja_racontee": True} if lid in racontees else {})})
        return {"total_trouve": len(vues), "resultats": res}

    def t_lire_lettres(self, state, ids):
        # Plafonné (6 lettres × 1600 caractères) : lire beaucoup coûte cher en temps de réponse
        demandees = self.lettres(ids)
        out = []
        for c in self.textes(demandees[:6], limite=1600):
            out.append({"id": c["id"], "date": c.get("date_iso"), "type": c.get("source_kind"),
                        "titre": (c.get("title") or "")[:120], "texte": c.get("text") or "",
                        **({"passages": c["nb_passages"]} if c["nb_passages"] > 1 else {}),
                        **({"suite_non_lue": True} if c["tronquee"] else {}),
                        **({"date_incertaine": True} if c.get("date_reliable") == 0 else {})})
        if len(demandees) > 6:
            out.append({"note": f"{len(demandees) - 6} lettres non lues : 6 au maximum par appel, choisis les plus prometteuses."})
        return out

    def t_tirer_au_hasard(self, state):
        letters = self._random_letters(exclure=state["racontees"])
        return [{"id": l["id"], "date": l["date"], "titre": l["titre"], "extrait": l["extrait"],
                 "phrase_citable": l["phrase_citable"]} for l in letters]

    def t_tableaux(self, state, mots):
        cles = [m for m in re.findall(r"\w+", _sans_accents(mots)) if len(m) > 2]
        scores = []
        for t in TABLEAUX.values():
            texte = _sans_accents(f"{t['titre']} {t['sujet']} {t['peintre']}")
            n = sum(c in texte for c in cles)
            if n:
                scores.append((n, t))
        return [{k: t[k] for k in ("id", "titre", "peintre", "date", "sujet")}
                for _, t in sorted(scores, key=lambda x: -x[0])[:8]]

    def t_fiche_personnelle(self, state, rubrique=None, mots=None):
        rubriques = {}
        for f in NAPOLEON_FICHE:
            rubriques[f["rubrique"]] = rubriques.get(f["rubrique"], 0) + 1
        faits = []
        if rubrique:
            r = _sans_accents(rubrique)
            faits = [f for f in NAPOLEON_FICHE if r in _sans_accents(f["rubrique"])]
        if mots:
            # Faits contenant le plus de mots de la recherche (accents et majuscules ignorés)
            cles = [m for m in re.findall(r"\w+", _sans_accents(mots)) if len(m) > 2]
            scores = [(sum(c in _sans_accents(f["texte"]) for c in cles), f) for f in NAPOLEON_FICHE]
            trouves = [f for s, f in sorted(scores, key=lambda x: -x[0]) if s > 0][:12]
            faits = faits + [f for f in trouves if f not in faits]
        return {"rubriques": rubriques,
                "faits": [{"id": f["id"], "rubrique": f["rubrique"], "texte": f["texte"]} for f in faits]}

    def t_memoires(self, state, requete, limite=4, date_debut=None, date_fin=None):
        if self.m_emb is None:
            return {"erreur": "mémoires indisponibles"}
        limite = max(1, min(8, int(limite or 4)))
        if self.embed_client is None:
            return self._memoires_par_mots(requete, limite)
        lo = (date_debut or "")[:10]
        hi = (date_fin or "")[:10]
        sims = cosine_sim(embed_question(self.embed_client, requete), self.m_emb)
        out = []
        for i in np.argsort(-sims)[:300]:
            if len(out) >= limite:
                break
            cid = int(self.m_ids[i])
            row = self.m_conn.execute("SELECT title, text FROM chunks WHERE id=?", (cid,)).fetchone()
            sec = passage_oeuvres(cid, row[0]) if row else None
            if not sec:
                continue          # date incertaine, ou texte d'un éditeur : écarté de la recherche
            per = sec.get("periode") or ""
            if (lo or hi) and (not per[:4].isdigit() or (lo and per[:len(lo)] < lo[:len(per)])
                               or (hi and per[:len(hi)] > hi[:len(per)])):
                continue
            out.append({"id": cid, "score": round(float(sims[i]), 3), **sec, "texte": (row[1] or "")[:400]})
        return out

    def _periodes_oeuvres(self, ids: list[int]) -> dict:
        """Date (des faits racontés) de chaque passage des Œuvres."""
        out = {}
        for i in ids:
            row = self.m_conn.execute("SELECT title FROM chunks WHERE id=?", (i,)).fetchone() if self.m_conn else None
            sec = passage_oeuvres(i, row[0]) if row else None
            if sec:
                out[i] = sec.get("periode") or ""
        return out

    def _oeuvres_ecartees(self, ids: list[int]) -> list[int]:
        """Passages des Œuvres inconnus ou écartés de la recherche (date incertaine, texte d'un éditeur)."""
        if not ids or self.m_conn is None:
            return list(ids)
        rows = dict(self.m_conn.execute(
            f"SELECT id, title FROM chunks WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall())
        return [i for i in ids if i not in rows or passage_oeuvres(i, rows[i]) is None]

    def _memoires_par_mots(self, requete: str, limite: int) -> list[dict]:
        """Repli sans embeddings : passages des mémoires contenant le plus de mots de la requête."""
        mots = [m for m in re.findall(r"\w+", requete.lower()) if len(m) > 3][:6]
        if not mots:
            return []
        score = " + ".join("(instr(lower(text), ?) > 0)" for _ in mots)
        rows = self.m_conn.execute(
            f"SELECT id, title, text, {score} AS s FROM chunks WHERE s > 0 ORDER BY s DESC LIMIT ?",
            (*mots, limite)).fetchall()
        return [{"id": r[0], "score": r[3], "titre": (r[1] or "")[:80], "texte": (r[2] or "")[:400]} for r in rows]

    def t_fixer_plan(self, state, sujet, chapitres, periode_debut=None, periode_fin=None):
        for ch in chapitres:
            ch["lettres"] = self.lettres(ch.get("lettres", []))
        meta = self._meta([i for ch in chapitres for i in ch["lettres"]])
        # Garde-fou « un plan = un épisode » : une période de plus de trois ans n'est pas un épisode
        if periode_debut and periode_fin:
            ecart = _ecart_jours((periode_debut + "-01-01")[:10] if len(periode_debut) == 4 else (periode_debut + "-01")[:10],
                                 (periode_fin + "-01-01")[:10] if len(periode_fin) == 4 else (periode_fin + "-01")[:10])
            if ecart is not None and ecart > PLAN_MAX_JOURS:
                return {"_erreur": (f"période de {ecart // 365} ans : un plan couvre UN épisode (trois ans au plus). "
                                    "Choisis le premier épisode de cette période qui a des sources et fais-en le plan ; "
                                    "les épisodes suivants se proposeront en transition.")}
        # Refuser les lettres datées hors de la période annoncée
        hors_periode = []
        if periode_debut and periode_fin:
            lo, hi = periode_debut[:7], periode_fin[:7] + "\xff"
            for lid, m in meta.items():
                d = (m[1] or "")[:7]
                if d and not (lo <= d <= hi):
                    hors_periode.append({"id": lid, "date": m[1]})
        incertaines = [lid for lid, m in meta.items() if m[5] == 0]
        valid = set(meta.keys()) - {h["id"] for h in hors_periode} - set(incertaines)
        new_topic = not state["plan"] or state["plan"].get("sujet") != sujet
        gardes = [] if new_topic else [c for c in state["chapitres"] if c["statut"] in ("raconte", "ecarte")]
        racontees = set(self.lettres(state["racontees"]))
        prises = {l for c in gardes for l in c["lettres"]}
        deja_racontees, en_double = [], []
        n0 = len(state["chapitres"])
        nouveaux = []
        for k, ch in enumerate(chapitres, 1):
            lettres = []
            for lid in ch["lettres"]:
                if lid not in valid:
                    continue
                if lid in racontees:
                    deja_racontees.append(lid)
                elif lid in prises:
                    en_double.append(lid)
                else:
                    prises.add(lid)
                    lettres.append(lid)
            fiche_ids = {f["id"] for f in NAPOLEON_FICHE}
            memoires = [int(i) for i in (ch.get("memoires") or []) if str(i).isdigit()][:2]
            ecartes = set(self._oeuvres_ecartees(memoires))
            memoires = [m for m in memoires if m not in ecartes]
            if periode_debut and periode_fin:   # même règle que pour les lettres : la date du passage
                for m, per in self._periodes_oeuvres(memoires).items():
                    if per[:4].isdigit() and not (lo <= per[:7] <= hi):
                        hors_periode.append({"id": m, "oeuvres": True, "date": per})
                        memoires.remove(m)
            faits = []   # la fiche n'est pas une source : un chapitre repose sur des lettres ou des Œuvres
            if not (lettres or memoires or faits):
                continue
            nouveaux.append({"id": f"c{n0 + k}", "moment": int(ch.get("moment") or k),
                             "titre": ch["titre"], "resume": ch.get("resume", ""),
                             "lettres": lettres, "memoires": memoires, "faits": faits,
                             "date": str(ch.get("date") or ""), "statut": "a_raconter"})
        # Des chapitres d'un même moment mais éloignés dans le temps ne sont pas des variantes : ce sont
        # des moments successifs (sinon le choix du visiteur ferait perdre l'un d'eux sans le raconter).
        def debut(c):
            dates = sorted(meta[l][1] for l in c["lettres"] if meta.get(l) and meta[l][1])
            return dates[0] if dates else c.get("date", "")
        separes, prec = [], None          # prec = (moment d'origine, date de référence, nouveau numéro)
        numero = max([c.get("moment") or 0 for c in gardes], default=0)
        for c in sorted(nouveaux, key=lambda c: (c["moment"], debut(c))):
            origine, d = c["moment"], debut(c)
            ecart = _ecart_jours(prec[1], d) if prec and prec[1] and d else None
            if prec and prec[0] == origine and ecart is not None and ecart <= VARIANTE_MAX_JOURS:
                c["moment"] = prec[2]
                continue
            if prec and prec[0] == origine:
                separes.append(c["id"])
            numero += 1
            prec = (origine, d, numero)
            c["moment"] = numero
        nouveaux.sort(key=lambda c: (c["moment"], debut(c)))
        state["plan"] = {"sujet": sujet, "debut": periode_debut, "fin": periode_fin}
        state["chapitres"] = gardes + nouveaux
        state["pistes"] = []
        result = {"ok": True, "chapitres": [{"id": c["id"], "moment": c.get("moment"), "titre": c["titre"],
                                             "statut": c["statut"], "nb_lettres": len(c["lettres"])}
                                            for c in state["chapitres"]],
                  "lettres_ignorees_invalides": sum(len(ch.get("lettres", [])) for ch in chapitres)
                  - sum(len(c["lettres"]) for c in nouveaux)}
        # Retour à l'archiviste (il décide) : un plan sans variantes ne laisse aucun vrai choix au visiteur.
        a_venir = {}
        for c in nouveaux:
            a_venir.setdefault(c["moment"], []).append(c)
        if separes:
            result["variantes_separees"] = (
                f"Chapitres devenus des moments successifs, car leurs lettres sont à plus de {VARIANTE_MAX_JOURS} jours "
                f"de leur « variante » : {separes}. Deux variantes racontent le même passage (même jour ou jours voisins).")
        nb_lettres = len({l for c in nouveaux for l in c["lettres"]})
        if (nb_lettres >= VARIANTES_MIN_LETTRES and len(a_venir) >= 2
                and sum(len(v) >= 2 for v in a_venir.values()) < len(a_venir) / 2):
            result["remarque_variantes"] = (
                "Peu de moments ont deux variantes : le visiteur n'aura guère de vrai choix. Si la matière le permet, "
                "cherche pour chaque moment une seconde lettre sur le même passage (autre destinataire, autre angle, "
                f"même jour ou jours voisins, {VARIANTE_MAX_JOURS} jours d'écart au plus) et révise le plan ; "
                "sinon, garde-le tel quel.")
        # Un chapitre sans lettre alors que la Correspondance en a à cette date : l'archiviste vérifie lui-même.
        sans_lettre = []
        for c in nouveaux:
            if c["lettres"] or len(c.get("date") or "") < 7:
                continue
            ym = c["date"][:7]
            n = self.conn.execute("SELECT COUNT(DISTINCT title) FROM chunks WHERE substr(date_iso, 1, 7) = ? "
                                  "AND date_reliable != 0", (ym,)).fetchone()[0]
            if n:
                sans_lettre.append(f"{c['id']} « {c['titre']} » ({ym} : {n} textes datés de ce mois)")
        if sans_lettre:
            result["chapitres_sans_lettre_a_verifier"] = (
                "Ces chapitres n'ont pas de lettre, mais la Correspondance a des textes à leur date : "
                + " ; ".join(sans_lettre) + ". Regarde-les (explorer_periode ou rechercher avec ces dates) et "
                "ajoute au plan ceux qui racontent ce moment ; la fiche ne sert que quand les lettres se taisent.")
        if deja_racontees:
            result["lettres_deja_racontees"] = (
                f"Lettres déjà racontées dans la conversation, retirées du plan : {sorted(set(deja_racontees))}.")
        if en_double:
            result["lettres_en_double"] = (
                f"Lettres placées dans plusieurs chapitres, gardées seulement dans le premier : {sorted(set(en_double))}. "
                "Deux variantes doivent reposer sur des lettres différentes.")
        if incertaines:
            result["lettres_date_incertaine"] = (
                f"Textes à la date douteuse, refusés dans un plan chronologique : {sorted(incertaines)}.")
        # Le récit avance dans le temps : un moment ne doit pas revenir avant le précédent.
        debuts = []
        for moment in sorted(a_venir):
            dates = [meta[l][1] for c in a_venir[moment] for l in c["lettres"] if meta.get(l) and meta[l][1]]
            if dates:
                debuts.append((moment, min(dates)))
        reculs = [(a[0], b[0]) for a, b in zip(debuts, debuts[1:]) if b[1] < a[1]]
        # Plan maigre alors que la période offre bien plus de lettres : l'archiviste peut l'étoffer.
        if periode_debut and periode_fin:
            kinds = ",".join("?" * len(_ECRITS_NAPOLEON))
            ids_periode = [r[0] for r in self.conn.execute(
                f"SELECT id FROM chunks WHERE source_kind IN ({kinds}) AND date_reliable != 0 "
                "AND date_iso >= ? AND date_iso <= ?",
                (*_ECRITS_NAPOLEON, _norm_start(periode_debut), _norm_end(periode_fin)))]
            disponibles = len(set(self.lettres(ids_periode)))
            if disponibles >= 6 and nb_lettres < disponibles / 3:
                result["plan_maigre"] = (
                    f"Le plan ne retient que {nb_lettres} lettres sur les {disponibles} écrits de Napoléon de la période. "
                    "Si d'autres parlent de l'épisode (cherche-les : rechercher, rechercher_mots sur les lieux et les "
                    "personnes), ajoute-les en moments successifs ; écarte seulement celles qui sont hors sujet.")
        if reculs:
            result["ordre_chronologique"] = (
                f"Moments qui reviennent en arrière dans le temps : {reculs}. Le récit suit l'ordre des dates : "
                "renumérote les moments dans l'ordre chronologique des lettres.")
        dates_plan = sorted(meta[l][1] for c in nouveaux for l in c["lettres"] if meta.get(l) and meta[l][1])
        if dates_plan:
            def mois_de(d):   # « 1796 », « 1796-04 » ou « 1796-04-11 » → nombre de mois
                return int(d[:4]) * 12 + (int(d[5:7]) if len(d) >= 7 and d[5:7].isdigit() else 1)
            mois = mois_de(dates_plan[-1]) - mois_de(dates_plan[0])
            if mois > EPISODE_MAX_MOIS:
                result["episode_trop_long"] = (
                    f"Les lettres du plan couvrent {mois} mois ({dates_plan[0]} → {dates_plan[-1]}) : un plan raconte UN "
                    "épisode (une campagne, une période bien bornée). Garde l'épisode que demande le visiteur ; "
                    "l'épisode suivant se proposera en transition, une fois celui-ci raconté.")
        if hors_periode:
            result["avertissement"] = (
                "Lettres ou passages des Œuvres refusés car hors de la période de l'épisode (un plan = un seul épisode) : "
                f"{hors_periode}. Si elles appartiennent à un autre épisode, garde-les pour une transition.")
        return result

    # ── Contexte d'état donné à l'archiviste ────────────────────────────────
    def _state_summary(self, state) -> str:
        if not state["plan"]:
            plan = "Aucun récit en cours."
        else:
            lines = [f"Sujet en cours : {state['plan']['sujet']} "
                     f"({state['plan'].get('debut') or '?'} → {state['plan'].get('fin') or '?'})"]
            for c in state["chapitres"]:
                lines.append(f"  {c['id']} moment {c.get('moment', '?')} [{c['statut']}] {c['titre']} — "
                             f"{c['resume']} (lettres {c['lettres']})")
            plan = "\n".join(lines)
        pistes = ""
        if state["pistes"]:
            ch = {c["id"]: c for c in state["chapitres"]}
            pistes = "Pistes proposées au visiteur au tour précédent : " + " ; ".join(
                f"{p} = « {ch[p]['titre']} »" for p in state["pistes"] if p in ch)
        amorce = ""
        if state.get("amorce"):
            a = state["amorce"]
            amorce = (f"Au tour précédent, Napoléon a relu la lettre amorce n°{a['id']} ({a.get('date')}) et a proposé : "
                      f"« {a.get('proposition', '')[:300]} ». Si le visiteur accepte, bâtis le plan de cet épisode "
                      "en y intégrant cette lettre.\n")
        hasard = ""
        if state["tour"] == 0 and not state["plan"]:
            letters = self._random_letters()
            if letters:
                hasard = "Lettres tirées au hasard pour ce premier tour :\n" + "\n".join(
                    f"  n°{l['id']} [{l['date']}] {l['titre']} — {l['extrait']}…\n"
                    f"      phrase citable : {l['phrase_citable']}" for l in letters) + "\n"
        return (f"Tour n°{state['tour'] + 1}.\n{plan}\n{pistes}\n{amorce}{hasard}"
                f"Lettres déjà racontées : {state['racontees'] or 'aucune'}\n"
                f"Dernière réponse de Napoléon : {state['derniere_reponse'][:400] or '(aucune)'}")

    # ── Boucle agent ────────────────────────────────────────────────────────
    def _recherche_initiale(self, state, user_message: str) -> str:
        """Recherche faite avec les mots mêmes du visiteur, dans les lettres, les Œuvres et la fiche, jointe à son
        message : l'archiviste part de ce que les sources disent du sujet, et non de sa propre idée du sujet."""
        if self.embed_client is None or len(user_message.split()) < 3:
            return ""
        try:
            r = self.t_rechercher(state, user_message, limite=8)
        except Exception as e:  # la recherche initiale est une aide : l'archiviste peut toujours chercher lui-même
            print(f"[ARCHIVISTE] recherche initiale indisponible : {e}")
            return ""
        return ("\n\nRecherche faite avec ces mots dans tes trois sources (lettres, Œuvres, fiche) — pars de ce "
                "qu'elle trouve, puis cherche davantage si besoin :\n" + json.dumps(r, ensure_ascii=False))

    def decide(self, state: dict, user_message: str) -> dict:
        """Fait enquêter l'archiviste et renvoie sa décision terminale (servir_tour / repondre_librement)."""
        t0 = time.time()
        messages = [
            {"role": "system", "content": ARCHIVIST_PROMPT},
            {"role": "user", "content": f"{self._state_summary(state)}\n\nMessage du visiteur : {user_message}"
                                        + self._recherche_initiale(state, user_message)},
        ]
        for step in range(MAX_AGENT_STEPS):
            force = step == MAX_AGENT_STEPS - 1
            if step == MAX_AGENT_STEPS - 2:
                messages.append({"role": "user", "content": (
                    "Il te reste deux appels : conclus maintenant avec ce que tu as lu "
                    "(fixer_plan puis servir_tour, ou repondre_librement).")})
            resp = self.client.chat.completions.create(
                model=self.model, messages=messages, tools=TOOLS, temperature=0.2,
                tool_choice=("required" if not force else "required"),
            )
            msg = resp.choices[0].message
            calls = msg.tool_calls or []
            messages.append({"role": "assistant", "content": msg.content or "",
                             "tool_calls": [c.model_dump() for c in calls]})
            if not calls:
                messages.append({"role": "user", "content": "Termine avec servir_tour ou repondre_librement."})
                continue
            for call in calls:
                name = call.function.name
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                print(f"[ARCHIVISTE] {name} {json.dumps(args, ensure_ascii=False)[:220]}")
                if name in TERMINAL_TOOLS:
                    decision = self._finalize(state, name, args)
                    if decision is not None and "_erreur" not in decision:
                        print(f"[ARCHIVISTE] décision en {step + 1} étapes, {time.time() - t0:.1f}s")
                        return decision
                    erreur = (decision or {}).get("_erreur") or "vérifie l'identifiant du chapitre et les lettres."
                    print(f"[ARCHIVISTE] décision refusée : {erreur[:160]}")
                    result = {"erreur": f"décision invalide : {erreur}"}
                else:
                    try:
                        result = getattr(self, f"t_{name}")(state, **args)
                    except Exception as exc:  # outil mal appelé → l'agent corrige
                        result = {"erreur": str(exc)}
                messages.append({"role": "tool", "tool_call_id": call.id,
                                 "content": json.dumps(result, ensure_ascii=False)[:12000]})
            if force:
                break
        print("[ARCHIVISTE] aucune décision — repli sur une réponse libre")
        return {"type": "libre", "consigne": "Réponds brièvement et invite le visiteur à préciser sa question."}

    def _finalize(self, state, name, args) -> dict | None:
        decision = self._finalize_core(state, name, args)
        if decision and "_erreur" not in decision:
            allowed = {"meteo": METEOS, "carte": CARTES, "lumiere": LUMIERES, "musique": MUSIQUES,
                       "tableau": ["aucun"] + list(TABLEAUX)}
            decision["scene"] = {k: args.get(k) for k in allowed if args.get(k) in allowed[k]}
            t = TABLEAUX.get(decision["scene"].get("tableau"))
            if t:   # l'interface affiche l'œuvre avec son cartel
                decision["scene"]["tableau"] = {**{k: t[k] for k in ("id", "titre", "peintre", "date")},
                                                "ref": f"tableau:{t['id']}"}
        return decision

    def _finalize_core(self, state, name, args) -> dict | None:
        if name == "repondre_librement":
            amorce = args.get("lettre_amorce")
            try:
                amorce = self.lettre(amorce) if amorce else None
            except (TypeError, ValueError):
                amorce = None
            meta = self._meta([int(amorce)]) if amorce else {}
            if amorce and int(amorce) not in meta:
                amorce = None   # identifiant inconnu : on ignore l'amorce plutôt que d'inventer
            citation = None
            if amorce and int(amorce) in meta:
                ok = self._choisir_citations(
                    state, [int(amorce)],
                    "Napoléon fait entendre à son visiteur UNE phrase de cette lettre pour lui donner "
                    "envie de l'épisode : " + args.get("consigne", ""))
                citation = ok[0]["texte"] if ok else None
            demandees = self.lettres(i for i in (args.get("lettres") or []) if str(i).isdigit())[:3]
            connues = self._meta(demandees) if demandees else {}
            inconnues = [l for l in demandees if l not in connues]
            if inconnues:
                return {"_erreur": f"lettres inconnues {inconnues} : sers des identifiants trouvés par tes recherches."}
            fiche = {f["id"]: f["texte"] for f in NAPOLEON_FICHE}
            faits_demandes = []   # la fiche oriente l'archiviste, elle n'est jamais racontée
            faits_inconnus = [i for i in faits_demandes if i not in fiche]
            if faits_inconnus:
                return {"_erreur": f"faits inconnus {faits_inconnus} : utilise les identifiants de fiche_personnelle."}
            memoires = [int(i) for i in (args.get("memoires") or []) if str(i).isdigit()][:2]
            if self._oeuvres_ecartees(memoires):
                return {"_erreur": f"passages des Œuvres inconnus ou écartés {self._oeuvres_ecartees(memoires)} : "
                                   "utilise les identifiants renvoyés par memoires ou rechercher."}
            return {"type": "libre", "consigne": args.get("consigne", ""),
                    "lettres": demandees, "memoires": memoires,
                    "faits": [fiche[i] for i in faits_demandes],
                    "citations": self._choisir_citations(
                        state, demandees, "Napoléon répond à son visiteur : " + args.get("consigne", ""))
                    if demandees else [],
                    "lettre_amorce": int(amorce) if amorce else None,
                    "citation_amorce": citation,
                    "_amorce_date": meta[int(amorce)][1] if amorce else None}
        ch = {c["id"]: c for c in state["chapitres"]}
        cid = args.get("chapitre")
        if cid not in ch:
            return {"_erreur": f"chapitre « {cid} » inconnu : choisis un chapitre du plan ou fixe un nouveau plan."}
        # Les lettres servies doivent appartenir au chapitre : les notes à l'écran (épisode, chapitre,
        # lettres) et les sources restent ainsi cohérentes avec ce que Napoléon raconte.
        # On ne substitue rien : l'archiviste corrige lui-même sa décision.
        if ch[cid]["statut"] in ("raconte", "ecarte"):
            etat = "déjà raconté" if ch[cid]["statut"] == "raconte" else "écarté (le visiteur a choisi l'autre variante)"
            ouverts = [c["id"] for c in state["chapitres"] if c["statut"] in ("a_raconter", "en_cours")]
            return {"_erreur": (f"le chapitre {cid} est {etat}. Chapitres encore à raconter : {ouverts or 'aucun'} ; "
                                "si tout est raconté, propose une transition (repondre_librement ou nouveau plan).")}
        demandees = self.lettres(i for i in (args.get("lettres") or []) if str(i).isdigit())
        deja = [l for l in demandees if l in set(self.lettres(state["racontees"]))]
        if deja:
            return {"_erreur": (f"les lettres {deja} ont déjà été racontées : ne les sers pas une seconde fois. "
                                f"Lettres du chapitre {cid} pas encore racontées : "
                                f"{[l for l in ch[cid]['lettres'] if l not in state['racontees']] or 'aucune'}.")}
        hors = [l for l in demandees if l not in ch[cid]["lettres"]]
        if hors:
            return {"_erreur": (
                f"les lettres {hors} n'appartiennent pas au chapitre {cid} « {ch[cid]['titre']} » "
                f"(lettres du chapitre : {ch[cid]['lettres']}). Si le visiteur change de sujet, enquête et "
                "fixe un nouveau plan avec fixer_plan avant de servir ces lettres ; s'il s'agit du même "
                "épisode, ajoute-les au plan (fixer_plan, même intitulé) ; sinon sers les lettres du chapitre.")}
        lettres = demandees[:3]
        memoires = [int(i) for i in (args.get("memoires") or ch[cid].get("memoires") or []) if str(i).isdigit()][:2]
        if self._oeuvres_ecartees(memoires):
            return {"_erreur": f"passages des Œuvres inconnus ou écartés {self._oeuvres_ecartees(memoires)} : "
                               "utilise les identifiants renvoyés par memoires ou rechercher."}
        fiche = {f["id"]: f["texte"] for f in NAPOLEON_FICHE}
        faits = []   # la fiche oriente l'archiviste, elle n'est jamais racontée
        if [i for i in faits if i not in fiche]:
            return {"_erreur": "faits inconnus : utilise les identifiants de la fiche."}
        if not lettres and ch[cid]["lettres"]:
            return {"_erreur": f"aucune lettre indiquée pour le chapitre {cid} (lettres du chapitre : {ch[cid]['lettres']})."}
        if not (lettres or memoires or faits):
            return {"_erreur": f"le chapitre {cid} n'a ni lettre, ni passage des Œuvres, ni fait de la fiche à raconter."}
        pistes = [p for p in (args.get("pistes") or []) if p in ch and p != cid
                  and ch[p]["statut"] not in ("raconte", "ecarte")
                  # l'autre variante du moment servi est abandonnée : elle ne peut pas être proposée
                  and not (ch[cid].get("moment") is not None and ch[p].get("moment") == ch[cid]["moment"])][:2]
        return {"type": "tour", "chapitre": ch[cid], "lettres": lettres,
                "memoires": memoires, "faits": [fiche[i] for i in faits],
                "pistes": [ch[p] for p in pistes], "transition": args.get("transition"),
                "citations": self._choisir_citations(
                    state, lettres, f"Ce que Napoléon raconte : {ch[cid]['titre']} — {ch[cid]['resume']}")
                if lettres else [],
                "note": args.get("note")}

    # ── Après narration ─────────────────────────────────────────────────────
    @staticmethod
    def commit(state: dict, decision: dict, speech: str):
        state["tour"] += 1
        state["derniere_reponse"] = speech
        dites = state.setdefault("citations_dites", [])
        dites += [c["texte"] for c in decision.get("citations") or []]
        if decision.get("citation_amorce"):
            dites.append(decision["citation_amorce"])
        if decision["type"] == "tour":
            for l in decision["lettres"]:
                if l not in state["racontees"]:
                    state["racontees"].append(l)
            ch = decision["chapitre"]
            if all(l in state["racontees"] for l in ch["lettres"]):
                ch["statut"] = "raconte"
            else:
                ch["statut"] = "en_cours"
            # Le chemin non pris est abandonné : les autres variantes de ce moment ne seront plus proposées.
            if ch.get("moment") is not None:
                for other in state["chapitres"]:
                    if (other is not ch and other.get("moment") == ch["moment"]
                            and other["statut"] == "a_raconter"):
                        other["statut"] = "ecarte"
            state["pistes"] = [p["id"] for p in decision["pistes"]]
        else:
            # Une réponse libre ne change ni le plan ni les pistes en attente ; ses lettres sont
            # comptées comme racontées, et elle peut poser une amorce.
            for l in decision.get("lettres") or []:
                if l not in state["racontees"]:
                    state["racontees"].append(l)
            if decision.get("lettre_amorce"):
                row = decision.get("_amorce_date")
                state["amorce"] = {"id": int(decision["lettre_amorce"]), "date": row,
                                   "proposition": decision.get("consigne", "")}
            return
        state["amorce"] = None   # l'amorce est consommée dès qu'un tour de récit est servi

    # ── Prompt de narration ─────────────────────────────────────────────────
    def _passages_oeuvres(self, ids: list[int]) -> list[str]:
        if not ids or self.m_conn is None:
            return []
        out = []
        for mid in ids:
            row = self.m_conn.execute("SELECT title, text FROM chunks WHERE id=?", (mid,)).fetchone()
            sec = passage_oeuvres(mid, row[0]) if row else None
            if sec:
                per = f", {sec['periode']}" if sec.get("periode") else ""
                out.append(f"[{sec['ouvrage']}{per}]\n{(row[1] or '')[:900]}")
        return out

    def narrator_prompt(self, state: dict, decision: dict, user_message: str,
                        nouvel_episode: bool = False, premiere_reponse: bool = False) -> str:
        parts = []
        if premiere_reponse:
            parts.append("C'est ta toute première réponse : ton visiteur vient d'arriver. Accueille-le sur ton île "
                         "et pose le décor de l'exil en quelques mots, à ta manière ; ce décor vaudra ensuite "
                         "pour toute la conversation.")
        if decision["type"] == "libre":
            if decision.get("lettre_amorce"):
                l = self.textes([int(decision["lettre_amorce"])], limite=500)
                if l:
                    parts.append(f"Lettre que tu viens de relire ({l[0].get('date_iso')}) :\n"
                                 f"« {(l[0].get('text') or '')[:500]}… »")
                    if decision.get("citation_amorce"):
                        evoque = ("fais entendre cette phrase, telle quelle entre « », en l'amenant pour que son sens "
                                  f"soit clair : « {decision['citation_amorce']} »")
                    else:
                        evoque = "évoques-en UN seul détail, sans guillemets"
                    parts.append(f"Ne raconte PAS cette lettre : {evoque}, comme un souvenir qui te revient, "
                                 "ancré par sa date et son lieu dits à voix haute. Elle sera racontée en entier si le "
                                 "visiteur accepte. Réponse courte : 4 à 5 phrases au total.")
            if decision.get("lettres"):
                letters = self.textes(decision["lettres"], limite=1500)
                parts.append("Conversation libre : ton visiteur te parle à sa façon. Réponds à ce qu'il te dit, "
                             "en t'appuyant sur ces lettres, chacune ancrée par sa date. Tiens-t'en STRICTEMENT à ce "
                             "qu'elles disent : n'ajoute ni fait, ni idée, ni jugement qui n'y figure pas. Distingue le destinataire "
                             "de la lettre et les personnes dont elle parle. Si elles ne répondent qu'en partie à la "
                             "question, dis simplement ce que tu écrivais ces jours-là, sans leur faire dire davantage. "
                             "Ne lui propose pas de choix de suite et ne le ramène pas à un récit : ne termine par une "
                             "question que si elle vient naturellement ou si la consigne le demande :\n" + "\n\n".join(
                    f"[{c.get('date_iso') or 'date inconnue'}] {(c.get('title') or '')[:80]}\n{c.get('text') or ''}"
                    + (" […]" if c["tronquee"] else "") for c in letters))
                if decision.get("citations"):
                    parts.append("Citations choisies — tes propres mots, à faire entendre TELLES QUELLES entre « », "
                                 "si elles servent ta réponse. Ne cite rien d'autre entre guillemets :\n"
                                 + "\n".join(f"- « {c['texte']} »" for c in decision["citations"]))
            mem = self._passages_oeuvres(decision.get("memoires") or [])
            if mem:
                parts.append("Passages de tes Œuvres (tes écrits des campagnes, du règne et de ta jeunesse, réunis "
                             "après coup ; chacun est précédé de son titre) : appuie-toi dessus en NOMMANT l'écrit "
                             "dont il vient, par le titre entre crochets qui le précède, "
                             "sans rien y ajouter. Fais entendre UNE phrase marquante de ces passages, telle quelle "
                             "entre « », en l'amenant pour que son sens soit clair :\n" + "\n\n".join(mem))
            if decision.get("faits"):
                parts.append("Faits de ta fiche personnelle — ce que tu sais de ta propre vie sans tes lettres. "
                             "Tu peux t'appuyer dessus, sans rien y ajouter :\n"
                             + "\n".join(f"- {f}" for f in decision["faits"]))
            if decision.get("faits") or mem:
                parts.append("Raconte, ne récite pas : même sans lettre, fais revivre ce moment comme une histoire, "
                             "au présent, ancrée dans un lieu et une date, en une ou deux scènes qui s'enchaînent "
                             "(où tu es, ce que tu vois, ce que tu fais, ce que tu ressens), plutôt qu'une suite de "
                             "dates et de faits. Ne garde que ce que disent les faits et les passages ci-dessus.")
            parts.append(f"Consigne de l'archiviste : {decision['consigne']}")
            if not decision.get("lettres"):
                parts.append("Aucune lettre n'est fournie : n'avance aucun fait historique qui ne figure pas "
                             "ci-dessus. Si un passage de tes écrits est fourni, nomme-le. Sinon, tu n'as AUCUNE "
                             "source : dis-le simplement, en une ou deux phrases, sans raconter le sujet de mémoire, "
                             "puis propose l'autre sujet indiqué par la consigne.")
            parts.append(f"Message du visiteur : {user_message}")
            return "\n\n---\n\n".join(parts)

        ch = decision["chapitre"]
        sans_lettre = not decision["lettres"]
        if decision["memoires"]:
            mem = self._passages_oeuvres(decision["memoires"])
            if mem:
                usage = ("c'est ta source principale pour ce moment : nomme l'écrit dont il vient, par son titre"
                         if sans_lettre else "sers-t'en seulement s'ils éclairent le moment raconté")
                parts.append("Passages de tes Œuvres (écrits des campagnes, du règne et de ta jeunesse, réunis après "
                             f"coup ; ce ne sont pas des souvenirs de l'exil) : {usage}, sans les présenter comme des "
                             "souvenirs de Sainte-Hélène. Fais entendre au plus UNE phrase marquante, telle quelle "
                             "entre « », amenée pour que son sens soit clair :\n" + "\n\n".join(mem))
        if decision.get("faits"):
            if not decision["memoires"]:
                parts.append("Aucun passage de tes écrits n'est fourni pour ce moment : ne dis pas que tu en parles "
                             "dans tes écrits et n'en nomme aucun ; dis que tu le racontes de mémoire.")
            parts.append("Faits de ta fiche personnelle — ce que tu sais de ta propre vie sans lettre. "
                         "Appuie-toi dessus, sans rien y ajouter :\n" + "\n".join(f"- {f}" for f in decision["faits"]))
        if sans_lettre:
            parts.append("Ce moment n'a pas de lettre : dis-le simplement, et dis clairement d'où vient ce que tu "
                         "racontes — tel écrit, nommé par son titre, ou ta seule mémoire —, puis raconte-le comme une histoire, au "
                         "présent, ancrée dans un lieu et une date, en une ou deux scènes qui s'enchaînent (où tu es, "
                         "ce que tu vois, ce que tu fais, ce que tu ressens), sans rien ajouter aux passages et aux "
                         "faits ci-dessus.")
        if state["plan"]:
            p = state["plan"]
            periode = f" ({p.get('debut') or '?'} → {p.get('fin') or '?'})" if p.get("debut") else ""
            parts.append(f"Épisode : {p['sujet']}{periode}")
            if nouvel_episode:
                parts.append("C'est un NOUVEL épisode : nomme-le clairement "
                             "(campagne ou période, année, adversaire ou enjeu) avant de plonger dans les lettres.")
        parts.append(f"Chapitre de ce tour : « {ch['titre']} » — {ch['resume']}")
        letters = self.textes(decision["lettres"], limite=2400) if decision["lettres"] else []
        if letters: parts.append("Lettres de ce tour (revis-les au présent, chacune ancrée par sa date). Tiens-t'en STRICTEMENT "
                     "à ce qu'elles disent : ne développe pas, ne commente pas, n'interprète pas, n'ajoute ni idée, "
                     "ni jugement, ni conclusion, ni état d'âme (« je médite », « il est évident pour moi »…) qui n'y "
                     "figure pas. Une lettre courte donne une réponse courte :\n" +"\n\n".join(
            f"[{c.get('date_iso') or 'date inconnue'}] {(c.get('title') or '')[:80]}\n{c.get('text') or ''}"
            + (" […]" if c["tronquee"] else "") for c in letters))
        if decision.get("citations"):
            parts.append("Citations choisies — tes propres mots, à faire entendre TELLES QUELLES entre « », chacune "
                         "une fois, amenées pour que le visiteur en saisisse le sens. Ne cite rien d'autre entre guillemets :\n"
                         + "\n".join(f"- « {c['texte']} »" for c in decision["citations"]))
        elif not sans_lettre:
            parts.append("Aucune citation n'est retenue pour ce tour : raconte sans guillemets.")
        if decision.get("note"):
            parts.append(f"Note de l'archiviste (une orientation, pas une source : ne raconte aucun fait "
                         f"qui ne figure pas dans les sources ci-dessus) : {decision['note']}")
        parts.append("Ne répète aucun fait ni aucun chiffre que tu as déjà dit dans tes réponses précédentes : "
                     "si une lettre reprend un détail déjà évoqué, passe dessus et avance dans le récit.")

        pistes = decision["pistes"]
        if len(pistes) >= 2:
            parts.append(
                "Suite du récit — CHOIX À PROPOSER (obligatoire ce tour). Ne raconte pas ces chapitres maintenant. "
                "Termine par UNE phrase interrogative qui laisse ton visiteur choisir "
                "entre ces deux façons de poursuivre le MÊME moment du récit, chacune évoquée par un détail concret "
                "de son résumé (une personne, un lieu, une image), sans en dévoiler la suite. Elles portent sur le même "
                "passage : fais sentir ce qui les distingue (un autre regard, une autre personne, un autre lieu) et "
                "énonce bien les DEUX, reliées par « ou », sans les fondre en une seule proposition :\n"
                + "\n".join(f"{k}) {p['titre']} — {p['resume']}" for k, p in zip("AB", pistes)))
        elif len(pistes) == 1:
            parts.append("Suite du récit — une seule piste : termine par UNE seule proposition précise, "
                         "sans alternative (pas de « ou bien… »), vers :\n"
                         f"{pistes[0]['titre']} — {pistes[0]['resume']}")
        elif decision.get("transition"):
            parts.append("Suite du récit — ce sujet est entièrement raconté. NE propose PAS de choix. "
                         f"Termine par une seule accroche qui propose d'enchaîner sur : {decision['transition']}.")
        else:
            parts.append("Suite du récit — ce sujet est entièrement raconté. NE propose PAS de choix : "
                         "conclus et invite ton visiteur à te poser une autre question.")
        parts.append(f"Message du visiteur : {user_message}")
        parts.append(
            "RAPPEL ABSOLU — registre : tu t'adresses à ton visiteur à Sainte-Hélène, JAMAIS à Joséphine "
            "ni à aucune personne mentionnée dans tes lettres. Traduis en 3e personne : « je lui écris que… »."
        )
        return "\n\n---\n\n".join(parts)

    def annotation(self, state: dict, decision: dict) -> dict | None:
        """Repères affichés à l'écran pour CETTE réponse : épisode, période, chapitre, lettres racontées.

        Toujours renvoyés (même vides) pour que l'écran suive le récit : une réponse sans lettre
        efface les lettres du tour précédent ; la première réponse montre sa lettre d'amorce."""
        p = state["plan"]
        ann = {"episode": p["sujet"] if p else None,
               "periode_debut": p.get("debut") if p else None, "periode_fin": p.get("fin") if p else None,
               "chapitre": None, "lettres": []}
        if decision["type"] == "tour":
            ann["chapitre"] = decision["chapitre"]["titre"]
            ids = decision["lettres"]
            ann["lacune"] = self._lacune(state, decision)
        else:
            ids = list(decision.get("lettres") or [])
            if decision.get("lettre_amorce") and decision["lettre_amorce"] not in ids:
                ids.append(decision["lettre_amorce"])
        ids = self.lettres(ids)
        chunks = sorted(fetch_chunks(self.conn, ids) if ids else [], key=lambda c: c.get("date_iso") or "")
        for c in chunks:
            titre = (c.get("title") or "").strip()
            # « 21582. AU GÉNÉRAL COMTE BERTRAND, … » → « AU GÉNÉRAL COMTE BERTRAND, … »
            if ". " in titre[:8]:
                titre = titre.split(". ", 1)[1]
            ann["lettres"].append({"date": c.get("date_iso"), "titre": titre[:70]})
        # La période affichée couvre toujours les lettres montrées (et celles du plan).
        if p:
            dates = [d for d in self._dates_plan(state) + [l["date"] for l in ann["lettres"]] if d]
            if dates:
                debut, fin = ann["periode_debut"], ann["periode_fin"]
                ann["periode_debut"] = min([debut] + dates) if debut else min(dates)
                ann["periode_fin"] = max([fin] + dates) if fin else max(dates)
        return ann

    def _lacune(self, state, decision) -> dict | None:
        """Silence des archives entre la dernière lettre racontée de l'épisode et celles de ce tour.

        Seulement les vrais manques : aucune lettre, aucun ordre, aucune proclamation ni aucun bulletin
        de Napoléon dans la base pendant au moins LACUNE_MIN_JOURS jours. Affiché dans les notes,
        jamais raconté."""
        def jour(lid):
            m = self._meta([lid]).get(lid)
            try:
                return dt.date.fromisoformat(m[1]) if m and m[1] and len(m[1]) == 10 else None
            except ValueError:
                return None
        actuelles = set(decision["lettres"])
        avant = [jour(l) for c in state["chapitres"] if c["statut"] in ("raconte", "en_cours")
                 for l in c["lettres"] if l in state["racontees"] and l not in actuelles]
        apres = [jour(l) for l in actuelles]
        avant, apres = [d for d in avant if d], [d for d in apres if d]
        if not avant or not apres:
            return None
        d0, d1 = max(avant), min(apres)
        if (d1 - d0).days <= LACUNE_MIN_JOURS:
            return None
        kinds = ",".join("?" * len(_ECRITS_NAPOLEON))
        rows = self.conn.execute(
            f"SELECT DISTINCT date_iso FROM chunks WHERE source_kind IN ({kinds}) AND date_reliable != 0 "
            "AND length(date_iso) = 10 AND date_iso > ? AND date_iso < ? ORDER BY date_iso",
            (*_ECRITS_NAPOLEON, d0.isoformat(), d1.isoformat())).fetchall()
        bornes = [d0]
        for (d,) in rows:
            try:
                bornes.append(dt.date.fromisoformat(d))
            except ValueError:
                pass
        bornes.append(d1)
        a, b = max(zip(bornes, bornes[1:]), key=lambda p: (p[1] - p[0]).days)
        jours = (b - a).days - 1
        # Un saut de plusieurs mois dans le récit n'est pas une lacune : seulement si les archives se
        # taisent sur la plus grande partie de l'intervalle entre les deux lettres.
        if jours < LACUNE_MIN_JOURS or jours < ((d1 - d0).days - 1) / 2:
            return None
        return {"du": (a + dt.timedelta(days=1)).isoformat(), "au": (b - dt.timedelta(days=1)).isoformat(),
                "jours": jours}

    def _dates_plan(self, state) -> list[str]:
        ids = sorted({l for c in state["chapitres"] if c["statut"] != "ecarte" for l in c["lettres"]})
        if not ids:
            return []
        rows = self.conn.execute(f"SELECT date_iso FROM chunks WHERE id IN ({','.join('?' * len(ids))})",
                                 ids).fetchall()
        return [r[0] for r in rows if r[0]]

    def doc_count(self, state) -> int:
        """Lettres retenues dans le plan de l'épisode (celles que Napoléon racontera)."""
        return len({l for c in state["chapitres"] for l in c["lettres"]})

    def period_count(self, state) -> dict | None:
        """Toutes les lettres de la base datées de la période de l'épisode, quel qu'en soit le sujet."""
        p = state["plan"]
        if not p or not p.get("debut") or not p.get("fin"):
            return None
        n = self.t_explorer_periode(state, p["debut"], p["fin"])["total_lettres"]
        return {"total": n, "debut": p["debut"], "fin": p["fin"]}
