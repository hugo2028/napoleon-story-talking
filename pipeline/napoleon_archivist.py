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

import json
import os
import re
import time
from collections import Counter
from difflib import SequenceMatcher

import numpy as np

from napoleon_agent import cosine_sim, embed_question, fetch_chunks
from llm_connector import parse_json_object

AGENT_MODEL = os.getenv("AGENT_MODEL", "gpt-4.1")
MAX_AGENT_STEPS = int(os.getenv("AGENT_MAX_STEPS", "14"))

_MOT_RE = re.compile(r"\w+", re.UNICODE)


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
2. Enquêter quand c'est nécessaire : situer la période (chronologie), mesurer la matière \
disponible (explorer_periode), chercher (rechercher / rechercher_mots), lire les lettres prometteuses.
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
avec deux variantes pour la plupart des moments. \
Un plan d'un seul moment n'est acceptable que si les lettres manquent vraiment.
   - Commence le récit au début de l'épisode, sauf si le visiteur demande un moment précis.
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
Si le visiteur pose déjà une question précise, ignore ces lettres.
   Plus tard dans la conversation, quand le visiteur veut autre chose sans dire quoi, le hasard peut \
de nouveau ouvrir la voie : tirer_au_hasard te donne d'autres lettres, et tu procèdes de la même façon \
(sans saluer à nouveau : la conversation continue). C'est à toi de juger quand c'est le meilleur choix. \
Ne propose pas un épisode de mémoire, sans lettre pour l'appuyer.
   Au tour suivant, si le visiteur accepte l'épisode proposé, construis le plan de CET épisode \
en y intégrant la lettre amorce.

Règles :
- Tout ce que Napoléon racontera doit venir des lettres servies : choisis-les avec soin.
- Ne sers jamais une lettre déjà racontée, sauf si le visiteur le demande expressément.
- Sois efficace : une enquête complète tient en 3 à 8 appels d'outils ; un tour de suite en 0 à 2.
- Termine TOUJOURS par servir_tour ou repondre_librement.
"""

# ---------------------------------------------------------------------------
# Schémas d'outils (OpenAI function calling)
# ---------------------------------------------------------------------------

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
        "Recherche sémantique dans les lettres. Renvoie les résultats triés par score (cosinus) avec "
        "un extrait, plus la distribution des scores pour t'aider à choisir un seuil.",
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
         "limite": {"type": "integer", "description": "1-8, défaut 4."}},
        ["requete"]),
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
             "resume": {"type": "string", "description": "1-2 phrases factuelles tirées des lettres."},
             "lettres": {"type": "array", "items": {"type": "integer"}},
         }, "required": ["titre", "resume", "lettres"]}}},
        ["sujet", "chapitres"]),
    _fn("servir_tour",
        "Termine le tour : transmet au narrateur le chapitre à raconter, les lettres, les passages des "
        "Œuvres éventuels et les pistes à proposer au visiteur.",
        {"chapitre": {"type": "string", "description": "Identifiant du chapitre (ex. c2)."},
         "lettres": {"type": "array", "items": {"type": "integer"}, "description": "1 à 3 lettres à raconter."},
         "memoires": {"type": "array", "items": {"type": "integer"}, "description": "0 à 2 passages des Œuvres de Napoléon (outil memoires)."},
         "pistes": {"type": "array", "items": {"type": "string"}, "description": "0 à 2 identifiants de chapitres non racontés : les variantes du moment suivant."},
         "transition": {"type": "string", "description": "Si aucune piste : moment de la vie vers lequel proposer d'enchaîner."},
         "note": {"type": "string", "description": "Consigne courte au narrateur (angle, émotion, lien avec la demande)."}},
        ["chapitre", "lettres", "pistes"]),
    _fn("repondre_librement",
        "Termine le tour hors du récit guidé : salutation, échange, question hors correspondance, "
        "ou conversation libre où Napoléon répond directement au visiteur, sans plan ni choix à proposer.",
        {"consigne": {"type": "string", "description": "Ce que Napoléon doit dire ou à quoi il répond, sous quel angle, "
                      "et s'il relance ou non, en une ou deux phrases."},
         "lettres": {"type": "array", "items": {"type": "integer"},
                     "description": "Optionnel : 1 à 3 lettres sur lesquelles Napoléon fonde sa réponse (conversation libre)."},
         "lettre_amorce": {"type": "integer", "description": "Optionnel : une lettre dont citer un détail pour proposer un sujet."}},
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
        self.conn = conn
        self.emb = emb_matrix
        self.ids = np.array(chunk_ids)
        self.m_conn, self.m_emb, self.m_ids = m_conn, m_matrix, (np.array(m_ids) if m_ids else None)
        self.events = events
        self.model = model

    # ── Session ─────────────────────────────────────────────────────────────
    @staticmethod
    def new_state() -> dict:
        return {"plan": None, "chapitres": [], "racontees": [], "pistes": [], "tour": 0,
                "derniere_reponse": "", "amorce": None, "citations_dites": []}

    def _random_letters(self, n: int = 5, exclure=()) -> list[dict]:
        """Lettres tirées au hasard pour amorcer un sujet (lettres/proclamations de Napoléon, datées)."""
        exclure = [int(i) for i in exclure]
        rows = self.conn.execute(
            "SELECT id, date_iso, title, substr(text,1,700) FROM chunks "
            "WHERE length(date_iso) = 10 AND date_reliable != 0 "
            "AND source_kind IN ('napoleon_letter','napoleon_proclamation') AND length(text) > 400 "
            + (f"AND id NOT IN ({','.join('?' * len(exclure))}) " if exclure else "")
            + "ORDER BY RANDOM() LIMIT ?", (*exclure, n)).fetchall()
        letters = [{"id": r[0], "date": r[1], "titre": (r[2] or "")[:80], "extrait": (r[3] or "").replace("\n", " ")}
                   for r in rows]
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
        chunks = fetch_chunks(self.conn, lettres)
        if not chunks:
            return []
        dites = (state or {}).get("citations_dites") or []
        corps = "\n\n".join(f"[lettre {c['id']} — {c.get('date_iso') or '?'}]\n{(c.get('text') or '')[:2500]}"
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
                lid = int(c.get("lettre"))
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
            "SELECT id FROM chunks WHERE date_iso >= ? AND date_iso <= ?",
            (_norm_start(start) or "0000", _norm_end(end) or "9999\xff")).fetchall()
        return {r[0] for r in rows}

    def _meta(self, ids: list[int]) -> dict[int, tuple]:
        if not ids:
            return {}
        q = ",".join("?" * len(ids))
        rows = self.conn.execute(
            f"SELECT id, date_iso, title, source_kind, substr(text,1,220) FROM chunks WHERE id IN ({q})", ids
        ).fetchall()
        return {r[0]: r for r in rows}

    def t_chronologie(self, state):
        return [{"evenement": e["event"], "debut": e["start"], "fin": e["end"]} for e in self.events]

    def t_explorer_periode(self, state, date_debut, date_fin):
        rows = self.conn.execute(
            "SELECT id, date_iso, title, source_kind FROM chunks WHERE date_iso >= ? AND date_iso <= ? "
            "ORDER BY date_iso", (_norm_start(date_debut), _norm_end(date_fin))).fetchall()
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
        scores = sims[idx]
        dist = {}
        if len(scores):
            dist = {"lettres_dans_perimetre": int(len(scores)),
                    "max": round(float(scores.max()), 3),
                    "p90": round(float(np.percentile(scores, 90)), 3),
                    "mediane": round(float(np.median(scores)), 3),
                    **{f"nb>={s}": int((scores >= s).sum()) for s in (0.30, 0.35, 0.40, 0.45, 0.50)}}
        order = idx[np.argsort(-scores)]
        top = [(int(self.ids[i]), float(sims[i])) for i in order if sims[i] >= float(seuil_min or 0)][:limite]
        meta = self._meta([t[0] for t in top])
        racontees = set(state["racontees"])
        res = []
        for cid, sc in top:
            m = meta.get(cid)
            if not m:
                continue
            res.append({"id": cid, "date": m[1], "score": round(sc, 3), "type": m[3],
                        "titre": (m[2] or "")[:80], "extrait": (m[4] or "").replace("\n", " ")[:200],
                        **({"deja_racontee": True} if cid in racontees else {})})
        return {"distribution_scores": dist, "resultats": res}

    def t_rechercher_mots(self, state, mots, date_debut=None, date_fin=None, limite=25):
        limite = max(1, min(50, int(limite or 25)))
        conds = " OR ".join("lower(text) LIKE ?" for _ in mots)
        params = [f"%{m.lower()}%" for m in mots]
        sql = f"SELECT id, date_iso, title, source_kind, text FROM chunks WHERE ({conds})"
        if date_debut or date_fin:
            sql += " AND date_iso >= ? AND date_iso <= ?"
            params += [_norm_start(date_debut) or "0000", _norm_end(date_fin) or "9999\xff"]
        rows = self.conn.execute(sql + " ORDER BY date_iso", params).fetchall()
        res = []
        for r in rows[:limite]:
            low = (r[4] or "").lower()
            pos = min((low.find(m.lower()) for m in mots if low.find(m.lower()) >= 0), default=0)
            res.append({"id": r[0], "date": r[1], "type": r[3], "titre": (r[2] or "")[:80],
                        "extrait": (r[4] or "")[max(0, pos - 80): pos + 140].replace("\n", " ")})
        return {"total_trouve": len(rows), "resultats": res}

    def t_lire_lettres(self, state, ids):
        # Plafonné (6 lettres × 1000 caractères) : lire beaucoup coûte cher en temps de réponse
        out = []
        for c in fetch_chunks(self.conn, [int(i) for i in ids[:6]]):
            out.append({"id": c["id"], "date": c.get("date_iso"), "type": c.get("source_kind"),
                        "titre": (c.get("title") or "")[:120], "texte": (c.get("text") or "")[:1000]})
        if len(ids) > 6:
            out.append({"note": f"{len(ids) - 6} lettres non lues : 6 au maximum par appel, choisis les plus prometteuses."})
        return out

    def t_tirer_au_hasard(self, state):
        letters = self._random_letters(exclure=state["racontees"])
        return [{"id": l["id"], "date": l["date"], "titre": l["titre"], "extrait": l["extrait"],
                 "phrase_citable": l["phrase_citable"]} for l in letters]

    def t_memoires(self, state, requete, limite=4):
        if self.m_emb is None:
            return {"erreur": "mémoires indisponibles"}
        limite = max(1, min(8, int(limite or 4)))
        if self.embed_client is None:
            return self._memoires_par_mots(requete, limite)
        sims = cosine_sim(embed_question(self.embed_client, requete), self.m_emb)
        order = np.argsort(-sims)[:limite]
        out = []
        for i in order:
            cid = int(self.m_ids[i])
            row = self.m_conn.execute("SELECT title, text FROM chunks WHERE id=?", (cid,)).fetchone()
            if row:
                out.append({"id": cid, "score": round(float(sims[i]), 3), "titre": (row[0] or "")[:80],
                            "texte": (row[1] or "")[:400]})
        return out

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
        meta = self._meta([int(i) for ch in chapitres for i in ch.get("lettres", [])])
        # Garde-fou « un plan = un épisode » : refuser les lettres datées hors de la période annoncée
        hors_periode = []
        if periode_debut and periode_fin:
            lo, hi = periode_debut[:7], periode_fin[:7] + "\xff"
            for lid, m in meta.items():
                d = (m[1] or "")[:7]
                if d and not (lo <= d <= hi):
                    hors_periode.append({"id": lid, "date": m[1]})
        valid = set(meta.keys()) - {h["id"] for h in hors_periode}
        gardes = [c for c in state["chapitres"] if c["statut"] in ("raconte", "ecarte")]
        n0 = len(state["chapitres"])
        nouveaux = []
        for k, ch in enumerate(chapitres, 1):
            lettres = [int(i) for i in ch.get("lettres", []) if int(i) in valid]
            if not lettres:
                continue
            nouveaux.append({"id": f"c{n0 + k}", "moment": int(ch.get("moment") or k),
                             "titre": ch["titre"], "resume": ch.get("resume", ""),
                             "lettres": lettres, "statut": "a_raconter"})
        new_topic = not state["plan"] or state["plan"].get("sujet") != sujet
        state["plan"] = {"sujet": sujet, "debut": periode_debut, "fin": periode_fin}
        state["chapitres"] = ([] if new_topic else gardes) + nouveaux
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
        if len(a_venir) >= 2 and sum(len(v) >= 2 for v in a_venir.values()) < len(a_venir) / 2:
            result["remarque_variantes"] = (
                "Peu de moments ont deux variantes : le visiteur n'aura guère de vrai choix. Si la matière le permet, "
                "cherche pour chaque moment une seconde lettre sur le même passage (autre destinataire, autre angle, "
                "jour voisin) et révise le plan ; sinon, garde-le tel quel.")
        if hors_periode:
            result["avertissement"] = (
                "Lettres refusées car hors de la période de l'épisode (un plan = un seul épisode) : "
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
    def decide(self, state: dict, user_message: str) -> dict:
        """Fait enquêter l'archiviste et renvoie sa décision terminale (servir_tour / repondre_librement)."""
        t0 = time.time()
        messages = [
            {"role": "system", "content": ARCHIVIST_PROMPT},
            {"role": "user", "content": f"{self._state_summary(state)}\n\nMessage du visiteur : {user_message}"},
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
        if name == "repondre_librement":
            amorce = args.get("lettre_amorce")
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
            demandees = [int(i) for i in (args.get("lettres") or []) if str(i).isdigit()][:3]
            connues = self._meta(demandees) if demandees else {}
            inconnues = [l for l in demandees if l not in connues]
            if inconnues:
                return {"_erreur": f"lettres inconnues {inconnues} : sers des identifiants trouvés par tes recherches."}
            return {"type": "libre", "consigne": args.get("consigne", ""),
                    "lettres": demandees,
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
        demandees = [int(i) for i in (args.get("lettres") or []) if str(i).isdigit()]
        hors = [l for l in demandees if l not in ch[cid]["lettres"]]
        if hors:
            return {"_erreur": (
                f"les lettres {hors} n'appartiennent pas au chapitre {cid} « {ch[cid]['titre']} » "
                f"(lettres du chapitre : {ch[cid]['lettres']}). Si le visiteur change de sujet, enquête et "
                "fixe un nouveau plan avec fixer_plan avant de servir ces lettres ; s'il s'agit du même "
                "épisode, ajoute-les au plan (fixer_plan, même intitulé) ; sinon sers les lettres du chapitre.")}
        lettres = demandees[:3]
        if not lettres:
            return {"_erreur": f"aucune lettre indiquée pour le chapitre {cid}."}
        pistes = [p for p in (args.get("pistes") or []) if p in ch and p != cid
                  and ch[p]["statut"] not in ("raconte", "ecarte")
                  # l'autre variante du moment servi est abandonnée : elle ne peut pas être proposée
                  and not (ch[cid].get("moment") is not None and ch[p].get("moment") == ch[cid]["moment"])][:2]
        return {"type": "tour", "chapitre": ch[cid], "lettres": lettres,
                "memoires": [int(i) for i in (args.get("memoires") or [])][:2],
                "pistes": [ch[p] for p in pistes], "transition": args.get("transition"),
                "citations": self._choisir_citations(
                    state, lettres, f"Ce que Napoléon raconte : {ch[cid]['titre']} — {ch[cid]['resume']}"),
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
    def narrator_prompt(self, state: dict, decision: dict, user_message: str,
                        nouvel_episode: bool = False, premiere_reponse: bool = False) -> str:
        parts = []
        if premiere_reponse:
            parts.append("C'est ta toute première réponse : ton visiteur vient d'arriver. Accueille-le sur ton île "
                         "et pose le décor de l'exil en quelques mots, à ta manière ; ce décor vaudra ensuite "
                         "pour toute la conversation.")
        if decision["type"] == "libre":
            if decision.get("lettre_amorce"):
                l = fetch_chunks(self.conn, [int(decision["lettre_amorce"])])
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
                letters = fetch_chunks(self.conn, decision["lettres"])
                parts.append("Conversation libre : ton visiteur te parle à sa façon. Réponds à ce qu'il te dit, "
                             "en t'appuyant sur ces lettres, chacune ancrée par sa date. Tiens-t'en STRICTEMENT à ce "
                             "qu'elles disent : n'ajoute ni fait, ni idée, ni jugement qui n'y figure pas. Distingue le destinataire "
                             "de la lettre et les personnes dont elle parle. Si elles ne répondent qu'en partie à la "
                             "question, dis simplement ce que tu écrivais ces jours-là, sans leur faire dire davantage. "
                             "Ne lui propose pas de choix de suite et ne le ramène pas à un récit : ne termine par une "
                             "question que si elle vient naturellement ou si la consigne le demande :\n" + "\n\n".join(
                    f"[{c.get('date_iso') or 'date inconnue'}] {(c.get('title') or '')[:80]}\n{(c.get('text') or '')[:900]}"
                    for c in letters))
                if decision.get("citations"):
                    parts.append("Citations choisies — tes propres mots, à faire entendre TELLES QUELLES entre « », "
                                 "si elles servent ta réponse. Ne cite rien d'autre entre guillemets :\n"
                                 + "\n".join(f"- « {c['texte']} »" for c in decision["citations"]))
            parts.append(f"Consigne de l'archiviste : {decision['consigne']}")
            if not decision.get("lettres"):
                parts.append("Aucune autre lettre n'est fournie : n'avance aucun fait historique précis "
                             "qui ne figure pas ci-dessus.")
            parts.append(f"Message du visiteur : {user_message}")
            return "\n\n---\n\n".join(parts)

        ch = decision["chapitre"]
        if decision["memoires"] and self.m_conn is not None:
            mem = []
            for mid in decision["memoires"]:
                row = self.m_conn.execute("SELECT title, text FROM chunks WHERE id=?", (mid,)).fetchone()
                if row:
                    mem.append(f"[{(row[0] or 'Œuvres')[:60]}]\n{(row[1] or '')[:400]}")
            if mem:
                parts.append("Passages de tes Œuvres (écrits des campagnes et du règne, réunis après coup ; ce ne sont pas "
                             "des souvenirs de l'exil) : sers-t'en seulement s'ils éclairent le moment raconté, sans "
                             "les présenter comme des souvenirs de Sainte-Hélène :\n"
                             + "\n\n".join(mem))
        if state["plan"]:
            p = state["plan"]
            periode = f" ({p.get('debut') or '?'} → {p.get('fin') or '?'})" if p.get("debut") else ""
            parts.append(f"Épisode : {p['sujet']}{periode}")
            if nouvel_episode:
                parts.append("C'est un NOUVEL épisode : nomme-le clairement "
                             "(campagne ou période, année, adversaire ou enjeu) avant de plonger dans les lettres.")
        parts.append(f"Chapitre de ce tour : « {ch['titre']} » — {ch['resume']}")
        letters = fetch_chunks(self.conn, decision["lettres"])
        parts.append("Lettres de ce tour (revis-les au présent, chacune ancrée par sa date). Tiens-t'en STRICTEMENT "
                     "à ce qu'elles disent : ne développe pas, ne commente pas, n'interprète pas, n'ajoute ni idée, "
                     "ni jugement, ni conclusion, ni état d'âme (« je médite », « il est évident pour moi »…) qui n'y "
                     "figure pas. Une lettre courte donne une réponse courte :\n" +"\n\n".join(
            f"[{c.get('date_iso') or 'date inconnue'}] {(c.get('title') or '')[:80]}\n{(c.get('text') or '')[:900]}"
            for c in letters))
        if decision.get("citations"):
            parts.append("Citations choisies — tes propres mots, à faire entendre TELLES QUELLES entre « », chacune "
                         "une fois, amenées pour que le visiteur en saisisse le sens. Ne cite rien d'autre entre guillemets :\n"
                         + "\n".join(f"- « {c['texte']} »" for c in decision["citations"]))
        else:
            parts.append("Aucune citation n'est retenue pour ce tour : raconte sans guillemets.")
        if decision.get("note"):
            parts.append(f"Note de l'archiviste (une orientation, pas une source : ne raconte aucun fait "
                         f"qui ne figure pas dans les lettres ci-dessus) : {decision['note']}")
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
        else:
            ids = list(decision.get("lettres") or [])
            if decision.get("lettre_amorce") and decision["lettre_amorce"] not in ids:
                ids.append(decision["lettre_amorce"])
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

    def _dates_plan(self, state) -> list[str]:
        ids = sorted({l for c in state["chapitres"] if c["statut"] != "ecarte" for l in c["lettres"]})
        if not ids:
            return []
        rows = self.conn.execute(f"SELECT date_iso FROM chunks WHERE id IN ({','.join('?' * len(ids))})",
                                 ids).fetchall()
        return [r[0] for r in rows if r[0]]

    def doc_count(self, state) -> int:
        return len({l for c in state["chapitres"] for l in c["lettres"]})
