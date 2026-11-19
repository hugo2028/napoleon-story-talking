"""
napoleon_api.py — Agent Napoléon avec tool calling pour l'interface web.

Architecture :
  Frontend → Node.js (port 3002) → Flask API (port 5001)

  À chaque tour, un agent LLM choisit parmi deux outils :
    • continuer_recit   → sert le prochain lot de lettres du plan en cours
    • nouvelle_question → re-classifie + re-découvre pour un nouveau sujet

  Aucune règle en dur sur la longueur ou les mots-clés.

Usage :
  python3 pipeline/napoleon_api.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from threading import Lock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from flask import Flask, request, jsonify
from openai import OpenAI

from napoleon_agent import (
    RAG_DB, MEMOIR_DB, EVENTS_FILE, SYSTEM_PROMPT, AVATAR_GESTURE_ANIMATIONS,
    NarrativePlan,
    load_db, discover, classify_event, classify_sub_event, build_narrative_plan,
    build_first_prompt, build_turn_prompt_from_state, execute_turn,
    open_state_db, create_conversation, insert_conversation_letters,
    mark_letters_used, get_random_letter, branch_options_summary, get_pending_letters,
)

# ---------------------------------------------------------------------------
# Init au démarrage
# ---------------------------------------------------------------------------

openai_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("OPEN_AI_KEY")
if not openai_key:
    raise RuntimeError("Clé API OpenAI introuvable dans .env (LLM_API_KEY)")

embed_client = OpenAI(api_key=openai_key)
chat_client  = embed_client
model        = os.getenv("LLM_MODEL", "gpt-4.1-mini")

print(f"Chargement RAG : {RAG_DB} ...")
conn, emb_matrix, chunk_ids = load_db(RAG_DB)
print(f"  {len(emb_matrix)} vecteurs lettres")

if MEMOIR_DB.exists():
    m_conn, m_matrix, m_ids = load_db(MEMOIR_DB)
    print(f"  {len(m_matrix)} vecteurs mémoires")
else:
    m_conn = m_matrix = m_ids = None
    print("  (mémoires absents)")

events_data = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))

# Mode de pilotage du récit : "autonome" (archiviste à outils) ou "classique" (pipeline historique)
AGENT_MODE = os.getenv("AGENT_MODE", "autonome").strip().lower()
from napoleon_archivist import Archivist, AGENT_MODEL  # noqa: E402
archivist = Archivist(embed_client, conn, emb_matrix, chunk_ids, m_conn, m_matrix, m_ids, events_data)
print(f"Mode de récit : {AGENT_MODE}" + (f" (archiviste : {AGENT_MODEL})" if AGENT_MODE == "autonome" else ""))


# Métadonnées Gallica par tome de correspondance.
# offset     = nombre de vues Gallica avant la page imprimée n°1 du livre
#              (couvertures, faux-titres, tables… non numérotés).
# max_letter = numéro de lettre maximal extrait dans ce tome.
# total_vues = nombre total de vues dans le document Gallica.
#
# Formule :
#   Si max_letter ≤ total_vues → chunk_num est un numéro de PAGE imprimée :
#       vue = chunk_num + offset
#   Sinon → chunk_num est un numéro de LETTRE, il faut interpoler :
#       vue = round(offset + (chunk_num / max_letter) * (total_vues - offset))
_TOME_META: dict[int, dict] = {
    1:  {"ark": "bpt6k63323895",  "offset": 26,  "max_letter": 1471, "total_vues": 878},
    2:  {"ark": "bpt6k6295821n",  "offset": 12,  "max_letter": 1141, "total_vues": 552},
    3:  {"ark": "bpt6k6295853m",  "offset": 29,  "max_letter": 1130, "total_vues": 554},
    4:  {"ark": "bpt6k6332764q",  "offset": 12,  "max_letter": 1255, "total_vues": 806},
    5:  {"ark": "bpt6k96389458",  "offset": 12,  "max_letter": 1387, "total_vues": 814},
    6:  {"ark": "bpt6k6296310f",  "offset": 12,  "max_letter": 1313, "total_vues": 658},
    7:  {"ark": "bpt6k62963462",  "offset": 12,  "max_letter": 1251, "total_vues": 628},
    8:  {"ark": "bpt6k96414306",  "offset": 16,  "max_letter": 1110, "total_vues": 756},
    9:  {"ark": "bpt6k9634014c",  "offset": 27,  "max_letter": 1209, "total_vues": 768},
    10: {"ark": "bpt6k9634014c",  "offset": 13,  "max_letter": 1210, "total_vues": 768},
    11: {"ark": "bpt6k6328251z",  "offset": 12,  "max_letter": 1353, "total_vues": 758},
    12: {"ark": "bpt6k6294040x",  "offset": 15,  "max_letter": 1333, "total_vues": 632},
    13: {"ark": "bpt6k6328645m",  "offset": 12,  "max_letter": 1395, "total_vues": 783},
    14: {"ark": "bpt6k6296790v",  "offset": 22,  "max_letter": 1393, "total_vues": 654},
    15: {"ark": "bpt6k6294033s",  "offset": 20,  "max_letter": 1331, "total_vues": 620},
    16: {"ark": "bpt6k62981230",  "offset": 20,  "max_letter": 1386, "total_vues": 592},
    17: {"ark": "bpt6k96341740",  "offset": 31,  "max_letter": 1302, "total_vues": 754},
    18: {"ark": "bpt6k63285295",  "offset": 12,  "max_letter": 1463, "total_vues": 732},
    19: {"ark": "bpt6k96411995",  "offset": 11,  "max_letter": 1463, "total_vues": 760},
    20: {"ark": "bpt6k9642186v",  "offset": 25,  "max_letter": 1485, "total_vues": 732},
    21: {"ark": "bpt6k9641472j",  "offset": 18,  "max_letter": 1327, "total_vues": 730},
    22: {"ark": "bpt6k6336529t",  "offset": 12,  "max_letter": 1446, "total_vues": 717},
    23: {"ark": "bpt6k9667296p",  "offset": 34,  "max_letter": 1375, "total_vues": 708},
    24: {"ark": "bpt6k63342473",  "offset": 18,  "max_letter": 1640, "total_vues": 770},
    25: {"ark": "bpt6k62962170",  "offset": 30,  "max_letter": 1245, "total_vues": 592},
    26: {"ark": "bpt6k9634170b",  "offset": 18,  "max_letter": 1371, "total_vues": 728},
    27: {"ark": "bpt6k6312497h",  "offset": 11,  "max_letter":  803, "total_vues": 601},
    28: {"ark": "bpt6k6293077n",  "offset": 35,  "max_letter":  803, "total_vues": 360},
    29: {"ark": "bpt6k96413081",  "offset": 73,  "max_letter": 1110, "total_vues": 680},
    30: {"ark": "bpt6k9642292x",  "offset": 113, "max_letter": 1289, "total_vues": 700},
    31: {"ark": "bpt6k6329610q",  "offset": 55,  "max_letter":  566, "total_vues": 614},
    32: {"ark": "bpt6k6336619s",  "offset": 89,  "max_letter":  632, "total_vues": 634},
}

_CHUNK_KEY_RE = re.compile(r'^correspondance_(\d+)_(\d+)$')

def _gallica_url(chunk_key: str) -> str | None:
    """Retourne l'URL Gallica pointant approximativement sur la bonne page."""
    m = _CHUNK_KEY_RE.match(chunk_key)
    if not m:
        return None
    tome, chunk_num = int(m.group(1)), int(m.group(2))
    meta = _TOME_META.get(tome)
    if not meta:
        return None
    offset     = meta["offset"]
    max_letter = meta["max_letter"]
    total_vues = meta["total_vues"]
    # Les PDFs Gallica ne contiennent pas les plats physiques (plat.sup, contreplat.sup)
    # qui apparaissent en f1 et f2 dans le viewer web → décalage systématique de +2.
    GALLICA_COVER_OFFSET = 2

    if max_letter <= total_vues:
        # chunk_num est un numéro de page imprimée (ex: tome 32 = Précis des guerres)
        vue = chunk_num + offset + GALLICA_COVER_OFFSET
    else:
        # chunk_num est un numéro de lettre → interpolation linéaire
        vue = round(offset + (chunk_num / max_letter) * (total_vues - offset)) + GALLICA_COVER_OFFSET
    vue = max(1, min(vue, total_vues + GALLICA_COVER_OFFSET))
    return f"https://gallica.bnf.fr/ark:/12148/{meta['ark']}/f{vue}"


def _get_sources(letter_ids: list[int]) -> list[dict]:
    """Retourne date + début de texte + lien Gallica pour chaque lettre utilisée."""
    sources = []
    for lid in letter_ids:
        row = conn.execute("SELECT date_iso, text, chunk_key FROM chunks WHERE id=?", (lid,)).fetchone()
        if row:
            sources.append({
                "date":    row[0] or "?",
                "snippet": (row[1] or "").strip()[:100],
                "url":     _gallica_url(row[2] or ""),
            })
    sources.sort(key=lambda s: s["date"])   # même ordre que les lettres des notes
    return sources


_ALLOWED_ANIMATIONS = set(AVATAR_GESTURE_ANIMATIONS)
_ANIM_TAG_RE = re.compile(r"\s*\[anim:([^\]]+)\]\s*", re.IGNORECASE)
_MAX_ACTION_REPEATS = 3
_PAUSE_TOKEN = "[pause]"   # respiration du récit : silence SSML côté frontend, masquée à l'affichage
_PAUSE_RE = re.compile(r"\s*\[\s*pause\s*\]\s*", re.IGNORECASE)


def _cap_repeated_actions(actions: list[dict]) -> list[dict]:
    if "waiting" not in _ALLOWED_ANIMATIONS:
        return actions

    counts: dict[str, int] = {}
    capped = []
    for action in actions:
        animation = action["animation"]
        counts[animation] = counts.get(animation, 0) + 1
        if counts[animation] > _MAX_ACTION_REPEATS:
            capped.append({**action, "animation": "waiting"})
        else:
            capped.append(action)
    return capped

def _parse_actions(raw: str) -> tuple[str, list[dict]]:
    """
    Extrait les balises d'animation [anim:nom exact] du texte LLM.
    Retourne (texte_propre, [{word_start, animation}, ...]).
    word_start = index du premier mot de ce segment dans le texte propre (0-based).
    Le texte propre est stocké dans l'historique LLM pour ne pas polluer les tours suivants.
    """
    actions = []
    clean_words: list[str] = []
    pending_anim: str | None = None

    # Normaliser les variantes ([Pause], [ pause ]) en un mot isolé « [pause] »
    raw = _PAUSE_RE.sub(f" {_PAUSE_TOKEN} ", raw)
    parts = _ANIM_TAG_RE.split(raw)
    # parts alterne : texte, nom anim, texte, nom anim, ...
    for i in range(0, len(parts), 2):
        text = parts[i] or ""
        words = text.split()
        spoken = [w for w in words if w.lower() != _PAUSE_TOKEN]
        if pending_anim and spoken:
            # word_start compte les mots prononcés : les balises [pause] ne génèrent pas
            # d'événement wordBoundary côté Azure et ne doivent pas décaler les gestes.
            spoken_so_far = sum(1 for w in clean_words if w.lower() != _PAUSE_TOKEN)
            actions.append({"word_start": spoken_so_far, "animation": pending_anim})
            pending_anim = None
        clean_words.extend(words)

        if i + 1 >= len(parts):
            continue
        candidate = (parts[i + 1] or "").strip()
        pending_anim = candidate if candidate in _ALLOWED_ANIMATIONS else None

    clean_text = " ".join(clean_words)
    if not actions and clean_text.split() and "waiting" in _ALLOWED_ANIMATIONS:
        actions.append({"word_start": 0, "animation": "waiting"})
    return clean_text, _cap_repeated_actions(actions)


# Langues proposées à l'interface : code → nom (pour les consignes données au modèle).
LANGUES = {"fr": "français", "en": "anglais", "es": "espagnol", "it": "italien",
           "de": "allemand", "pt": "portugais"}


def _langue(code) -> str:
    return code if code in LANGUES else "fr"


def _consigne_langue(lang: str) -> str:
    """Consigne ajoutée au narrateur quand la conversation n'est pas en français."""
    nom = LANGUES[lang]
    return (f"LANGUE : réponds entièrement en {nom}, dans une langue naturelle et soutenue, "
            f"même si ces consignes et les lettres sont en français. Les citations entre « » sont "
            f"tes propres mots : fais-les entendre traduites fidèlement en {nom}, sans rien y ajouter, "
            f"entre les guillemets de cette langue. Garde les noms propres et les dates exacts. "
            f"La balise [pause] reste telle quelle.")


_traductions: dict[tuple[str, str], str] = {}


def _traduire(textes: list[str], lang: str) -> list[str]:
    """Traduit de courts libellés (titres d'épisode, de chapitre) ; mis en cache."""
    if lang == "fr":
        return textes
    manquants = [t for t in dict.fromkeys(textes) if t and (lang, t) not in _traductions]
    if manquants:
        try:
            resp = chat_client.chat.completions.create(
                model=model, temperature=0, response_format={"type": "json_object"},
                messages=[{"role": "user", "content": (
                    f"Traduis en {LANGUES[lang]} ces libellés d'un récit sur Napoléon, fidèlement et sans "
                    "rien ajouter. Réponds en JSON : {\"traductions\": [...]} dans le même ordre.\n"
                    + json.dumps(manquants, ensure_ascii=False))}])
            out = json.loads(resp.choices[0].message.content or "{}").get("traductions") or []
            for src, dst in zip(manquants, out):
                if isinstance(dst, str) and dst.strip():
                    _traductions[(lang, src)] = dst.strip()
        except Exception as exc:
            print(f"[TRADUCTION] échec : {exc}")
    return [_traductions.get((lang, t), t) if t else t for t in textes]


def _annotation_traduite(ann: dict | None, lang: str) -> dict | None:
    if not ann or lang == "fr":
        return ann
    episode, chapitre = _traduire([ann.get("episode") or "", ann.get("chapitre") or ""], lang)
    return {**ann, "episode": episode, "chapitre": chapitre}


def generate_context(event: dict, lang: str = "fr") -> str:
    """Génère un bref contexte historique (1-3 phrases) sur l'événement, style encyclopédique."""
    period = f"{event['start'][:4]}–{event['end'][:4]}"
    resp = chat_client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": (
            f"En 1 à 3 phrases, donne un contexte historique factuel sur "
            f"« {event['event']} » dans la vie de Napoléon Bonaparte ({period}). "
            "Style encyclopédique, neutre, informatif. Pas d'introduction ni de commentaire. "
            f"Réponds en {LANGUES[_langue(lang)]}."
        )}],
        max_tokens=120,
        temperature=0.3,
    )
    return resp.choices[0].message.content.strip()


# ---------------------------------------------------------------------------
# Outils de l'agent
# ---------------------------------------------------------------------------

AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "repondre_librement",
            "description": "Répondre sans puiser dans la correspondance — pour les salutations et les échanges conversationnels.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "continuer_recit",
            "description": "Servir le prochain lot de lettres du récit actif.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lettres_ce_tour": {
                        "type": "integer",
                        "description": (
                            "Nombre de lettres à inclure ce tour (1 à 4). "
                            "Choisis 1 pour approfondir un moment clé, "
                            "2-3 pour un flux narratif naturel, "
                            "4 pour une séquence rapide ou une période de transition."
                        ),
                        "minimum": 1,
                        "maximum": 4,
                    },
                    "choix": {
                        "type": "string",
                        "enum": ["A", "B"],
                        "description": (
                            "Si Napoléon vient de proposer deux pistes (A et B) et que le visiteur "
                            "en choisit une, même implicitement (un lieu, une personne, « la première », "
                            "« la seconde »…), indique laquelle. Omettre s'il ne choisit pas."
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "nouvelle_question",
            "description": "Chercher dans la correspondance les lettres pertinentes pour le sujet, la personne, la bataille ou la période évoqués.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "La question ou le sujet exprimé par l'utilisateur, reformulé si nécessaire.",
                    },
                    "date_start": {
                        "type": "string",
                        "description": (
                            "Début de la période à cibler (format YYYY-MM). "
                            "À fournir quand la question mentionne une date, un mois ou une année précise."
                        ),
                    },
                    "date_end": {
                        "type": "string",
                        "description": (
                            "Fin de la période à cibler (format YYYY-MM). "
                            "Peut être identique à date_start pour cibler un seul mois."
                        ),
                    },
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Mots-clés importants à booster dans la recherche : noms propres, lieux, batailles."
                        ),
                    },
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lettre_aleatoire",
            "description": "Ouvrir un récit en tirant une lettre au hasard quand aucun récit n'est en cours.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


def _route(user_message: str, event_name: str, turn: int,
           has_letters: bool = True,
           proposed_event: dict | None = None,
           branch_options: list[dict] | None = None) -> tuple[str, dict]:
    """Le LLM décide seul du routage — aucune règle en dur."""
    if proposed_event:
        narrative_ctx = (
            f"Napoléon vient de proposer le sujet « {proposed_event['event']} » "
            f"et attend la réponse du visiteur. "
            f"RÈGLE : si le visiteur accepte (« oui », « bien sûr », « racontez », « absolument », "
            f"« je veux bien », « continuez »…) → utilise OBLIGATOIREMENT continuer_recit. "
            f"Si le visiteur refuse ou change de sujet → utilise nouvelle_question. "
            f"N'utilise jamais repondre_librement quand un sujet est proposé."
        )
    elif event_name != "aucun" and has_letters:
        narrative_ctx = f"Récit actif : « {event_name} » (tour {turn}) — lettres disponibles dans la correspondance. "
    elif event_name != "aucun":
        narrative_ctx = (
            f"Récit actif : « {event_name} » (tour {turn}) — toutes les lettres de ce sujet ont déjà été racontées. "
            "Si le visiteur demande un moment ou un détail précis (un lieu, une date, une personne), "
            "utilise nouvelle_question pour chercher ces lettres. "
            "S'il veut simplement la suite, utilise continuer_recit (passage au chapitre suivant). "
        )
    else:
        narrative_ctx = "La correspondance de Napoléon n'est pas encore ouverte dans cette conversation. "

    if branch_options and len(branch_options) >= 2 and not proposed_event:
        pistes = " ; ".join(f"{o['key']}) {o['teaser']}" for o in branch_options)
        narrative_ctx += (
            f"Napoléon vient de proposer deux pistes pour la suite : {pistes}. "
            "Si le visiteur choisit l'une d'elles (même implicitement : un lieu, une personne, "
            "« la première », « l'autre »…), utilise continuer_recit avec choix=A ou choix=B. "
            "S'il veut simplement la suite sans choisir, continuer_recit sans choix. "
        )

    resp = chat_client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Tu gères une conversation avec Napoléon Bonaparte. "
                    + narrative_ctx
                    + "Choisis l'outil le plus approprié pour répondre à ce message. "
                    "Pour nouvelle_question, extrais date_start/date_end (YYYY-MM) et keywords si présents."
                ),
            },
            {"role": "user", "content": user_message},
        ],
        tools=AGENT_TOOLS,
        tool_choice="required",
        max_tokens=80,
        temperature=0,
    )
    tool_call = resp.choices[0].message.tool_calls[0]
    tool_name = tool_call.function.name
    tool_args = json.loads(tool_call.function.arguments or "{}")
    return tool_name, tool_args


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

sessions: dict[str, dict] = {}
sessions_lock = Lock()

# ---------------------------------------------------------------------------
# Flask
# ---------------------------------------------------------------------------

app = Flask(__name__)


@app.post("/chat")
def chat():
    data = request.json or {}
    frontend_conv_id = (data.get("conversation_id") or "").strip()
    message = (data.get("message") or "").strip()
    lang = _langue(data.get("lang"))

    if not message:
        return jsonify({"error": "message requis"}), 400

    if AGENT_MODE == "autonome":
        with sessions_lock:
            return _chat_autonome(frontend_conv_id or None, message, lang)

    with sessions_lock:
        if not frontend_conv_id or frontend_conv_id not in sessions:
            return _start(frontend_conv_id or None, message)
        else:
            return _continue(frontend_conv_id, message)


@app.delete("/chat")
def delete_chat():
    data = request.json or {}
    conv_id = data.get("conversation_id", "")
    with sessions_lock:
        state = sessions.pop(conv_id, None)
        if state:
            try:
                state["sconn"].close()
            except Exception:
                pass
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------

def _load_topic(state: dict, question: str,
                date_start: str | None = None,
                date_end: str | None = None,
                keywords: list[str] | None = None):
    """Classifie + découvre les lettres pour une question et met à jour la session."""
    classified_event = classify_event(chat_client, question, events_data, model)
    sub_topic = classify_sub_event(chat_client, question, classified_event, model) if classified_event else None
    plan = discover(
        embed_client, question,
        conn, emb_matrix, chunk_ids,
        m_conn, m_matrix, m_ids,
        forced_event=classified_event,
        sub_topic=sub_topic,
        date_start=date_start,
        date_end=date_end,
        keywords=keywords,
    )
    narrative_plan = build_narrative_plan(chat_client, plan, question, model)
    sconn      = state["sconn"]
    db_conv_id = state["db_conv_id"]
    sconn.execute("DELETE FROM conversation_letters WHERE conversation_id=?", (db_conv_id,))
    sconn.commit()
    if plan.letters:
        insert_conversation_letters(sconn, db_conv_id, plan.letters)
    state["plan"]           = plan
    state["narrative_plan"] = narrative_plan
    state["amorce_event"]   = None
    return plan


# ---------------------------------------------------------------------------
# Démarrage d'une nouvelle conversation
# ---------------------------------------------------------------------------

def _event_for_date(date_iso: str) -> dict | None:
    """Retourne l'événement le plus spécifique (fenêtre la plus courte) couvrant date_iso."""
    ym = date_iso[:7]
    if not ym:
        return None
    matching = [
        evt for evt in events_data
        if evt["start"][:7] <= ym <= evt["end"][:7]
    ]
    if not matching:
        return None
    # Parmi les candidats, préférer la fenêtre la plus courte (sous-période la plus précise)
    def _months(evt):
        sp = evt["start"].split("-")
        ep = evt["end"].split("-")
        sy, sm = int(sp[0]), int(sp[1])
        ey, em = int(ep[0]), int(ep[1])
        return (ey - sy) * 12 + (em - sm)
    return min(matching, key=_months)


def _discover_random(user_message: str = "") -> tuple["NarrativePlan", str, str | None] | None:
    """
    Choisit une lettre aléatoire, identifie l'événement correspondant,
    charge le plan complet et retourne (plan, event_name, narrative_plan).
    Utilise le texte de la lettre (+ message utilisateur) comme ancre sémantique
    pour trouver des lettres thématiquement proches, pas juste dans la même fenêtre temporelle.
    Retourne None si aucune lettre disponible.
    """
    rand = get_random_letter(conn)
    if not rand:
        return None
    amorce_event = _event_for_date(rand.get("date_iso", ""))
    if not amorce_event:
        return None
    # Ancre sémantique = texte de la lettre + message utilisateur (si thème exprimé)
    letter_text    = (rand.get("text") or "").strip()[:400]
    semantic_query = f"{user_message} {letter_text}".strip() if user_message else letter_text
    plan = discover(
        embed_client, semantic_query,
        conn, emb_matrix, chunk_ids,
        m_conn, m_matrix, m_ids,
        forced_event=amorce_event,
    )
    narrative = build_narrative_plan(chat_client, plan, amorce_event["event"], model)
    return plan, amorce_event["event"], narrative


def _start(frontend_conv_id: str | None, question: str):
    tool_name, tool_args = _route(question, "aucun", 0)

    plan           = NarrativePlan(letters=[], segments=[[]], event=None, next_events=[], memoir_chunks=[], has_source=False)
    narrative_plan = None
    prompt_topic   = question   # sujet affiché dans le prompt

    if tool_name == "nouvelle_question":
        routed_question  = tool_args.get("question", question)
        classified_event = classify_event(chat_client, routed_question, events_data, model)
        sub_topic        = classify_sub_event(chat_client, routed_question, classified_event, model) if classified_event else None
        plan = discover(
            embed_client, routed_question,
            conn, emb_matrix, chunk_ids,
            m_conn, m_matrix, m_ids,
            forced_event=classified_event, sub_topic=sub_topic,
            date_start=tool_args.get("date_start"),
            date_end=tool_args.get("date_end"),
            keywords=tool_args.get("keywords"),
        )
        narrative_plan = build_narrative_plan(chat_client, plan, routed_question, model)
        prompt_topic   = routed_question

    elif tool_name == "lettre_aleatoire":
        result = _discover_random(question)
        if result:
            plan, prompt_topic, narrative_plan = result

    # repondre_librement : salutation — proposer un sujet à partir d'une lettre aléatoire
    proposed_event = None
    proposed_letter_id = None
    if tool_name == "repondre_librement":
        rand = get_random_letter(conn)
        if rand:
            proposed_event = _event_for_date(rand.get("date_iso", ""))
        if proposed_event:
            proposed_letter_id = rand.get("id")
            letter_snippet = (rand.get("text") or "").strip()[:350]
            letter_date    = rand.get("date_iso", "")
            date_str       = f" ({letter_date})" if letter_date else ""
            prompt_topic = (
                f"{question}\n\n"
                f"(Tu viens de relire cette lettre que tu as écrite{date_str} :\n"
                f"« {letter_snippet}… »\n\n"
                f"Salue ton visiteur, mentionne que tu étais en train de relire cette lettre "
                f"et cite un détail précis qu'elle contient — sans la reproduire mot pour mot. "
                f"Enchaîne naturellement sur une proposition d'évoquer « {proposed_event['event']} ». "
                f"Question courte à la fin pour inviter à accepter ou rediriger.)"
            )

    sconn      = open_state_db()
    db_conv_id = create_conversation(sconn, question, plan.event["event"] if plan.event else None)
    if plan.letters:
        insert_conversation_letters(sconn, db_conv_id, plan.letters)

    messages     = [{"role": "system", "content": SYSTEM_PROMPT}]
    options: list[dict] = []
    first_prompt = build_first_prompt(plan, prompt_topic, narrative_plan=narrative_plan, options_out=options)
    messages.append({"role": "user", "content": first_prompt})

    current_ids = [l["id"] for l in plan.segments[0]] if plan.segments and plan.segments[0] else []
    if proposed_letter_id and not current_ids:
        current_ids = [proposed_letter_id]
    raw_answer  = execute_turn(chat_client, messages, model)
    speech, anim_actions = _parse_actions(raw_answer)
    messages.append({"role": "assistant", "content": speech})

    if current_ids:
        mark_letters_used(sconn, db_conv_id, current_ids, 1)

    session_key = frontend_conv_id or db_conv_id
    sessions[session_key] = {
        "messages":       messages,
        "plan":           plan,
        "narrative_plan": narrative_plan,
        "sconn":          sconn,
        "db_conv_id":     db_conv_id,
        "turn":           1,
        "proposed_event": proposed_event,
        "branch_options": branch_options_summary(options),
    }

    context_text = generate_context(plan.event) if plan.event else None
    return jsonify({
        "conversation_id": session_key,
        "speech":          speech,
        "event":           plan.event["event"] if plan.event else "thématique",
        "turn":            1,
        "doc_count":       len(plan.letters),
        "context":         context_text,
        "sources":         _get_sources(current_ids),
        "actions":         anim_actions,
    })


# ---------------------------------------------------------------------------
# Continuation — l'agent choisit l'outil
# ---------------------------------------------------------------------------

def _continue(conv_id: str, user_message: str):
    state      = sessions[conv_id]
    messages   = state["messages"]
    plan       = state["plan"]
    sconn      = state["sconn"]
    db_conv_id = state["db_conv_id"]
    turn       = state["turn"]
    narrative_plan = state.get("narrative_plan")

    event_name  = plan.event["event"] if plan.event else "aucun"
    # "Lettres disponibles" = lettres encore non racontées, pas seulement trouvées
    pending_count = len(get_pending_letters(sconn, db_conv_id))
    has_letters = plan.has_source and pending_count > 0
    tool_name, tool_args = _route(user_message, event_name, turn,
                                   has_letters=has_letters,
                                   proposed_event=state.get("proposed_event"),
                                   branch_options=state.get("branch_options"))

    pending_ids = []
    options: list[dict] | None = []   # pistes proposées en fin de tour ; None = conserver les précédentes

    if tool_name == "nouvelle_question":
        question = tool_args.get("question", user_message)
        plan     = _load_topic(state, question,
                               date_start=tool_args.get("date_start"),
                               date_end=tool_args.get("date_end"),
                               keywords=tool_args.get("keywords"))
        narrative_plan = state.get("narrative_plan")
        # Réinitialiser l'historique : le contexte précédent parasite le nouveau sujet
        state["messages"] = [state["messages"][0]]
        messages    = state["messages"]
        next_prompt = build_first_prompt(plan, question, narrative_plan=narrative_plan, options_out=options)
        pending_ids = [l["id"] for l in plan.segments[0]] if plan.segments and plan.segments[0] else []

    elif tool_name == "lettre_aleatoire":
        result = _discover_random(user_message)
        if result:
            plan, event_name, narrative_plan = result
            if plan.letters:
                sconn.execute("DELETE FROM conversation_letters WHERE conversation_id=?", (db_conv_id,))
                sconn.commit()
                insert_conversation_letters(sconn, db_conv_id, plan.letters)
            state["plan"]           = plan
            state["narrative_plan"] = narrative_plan
            next_prompt = build_first_prompt(plan, event_name, narrative_plan=narrative_plan, options_out=options)
            pending_ids = [l["id"] for l in plan.segments[0]] if plan.segments and plan.segments[0] else []
        else:
            next_prompt, pending_ids, _ = build_turn_prompt_from_state(
                sconn, db_conv_id, plan, turn + 1, conn, narrative_plan=narrative_plan,
                options_out=options,
            )

    elif tool_name == "continuer_recit":
        proposed_event = state.pop("proposed_event", None)
        if not proposed_event and pending_count == 0 and plan.next_events:
            # Sujet épuisé : on passe réellement au chapitre suivant (lettres + sources),
            # au lieu de raconter des lettres « d'aperçu » non déclarées.
            proposed_event = plan.next_events[0]
        if proposed_event and not has_letters:
            # L'utilisateur accepte le sujet proposé — charger le plan complet
            plan = discover(
                embed_client, proposed_event["event"],
                conn, emb_matrix, chunk_ids,
                m_conn, m_matrix, m_ids,
                forced_event=proposed_event,
            )
            narrative_plan = build_narrative_plan(chat_client, plan, proposed_event["event"], model)
            if plan.letters:
                sconn.execute("DELETE FROM conversation_letters WHERE conversation_id=?", (db_conv_id,))
                sconn.commit()
                insert_conversation_letters(sconn, db_conv_id, plan.letters)
            state["plan"]           = plan
            state["narrative_plan"] = narrative_plan
            next_prompt = build_first_prompt(plan, proposed_event["event"], narrative_plan=narrative_plan,
                                             options_out=options)
            pending_ids = [l["id"] for l in plan.segments[0]] if plan.segments and plan.segments[0] else []
        else:
            n_letters = max(1, min(4, int(tool_args.get("lettres_ce_tour") or 2)))
            choix = tool_args.get("choix")
            chosen_id = next(
                (o["id"] for o in (state.get("branch_options") or []) if o["key"] == choix), None
            )
            next_prompt, pending_ids, _ = build_turn_prompt_from_state(
                sconn, db_conv_id, plan, turn + 1, conn,
                narrative_plan=narrative_plan, n_letters=n_letters,
                prioritize_id=chosen_id, options_out=options,
            )

    else:  # repondre_librement
        state.pop("proposed_event", None)
        # Aucune lettre n'est fournie — interdire tout contenu historique inventé.
        if plan.next_events:
            evt_list = " / ".join(e["event"] for e in plan.next_events[:2])
            no_source_note = (
                "\n\n(RÈGLE ABSOLUE : si ce message porte sur un événement historique, "
                "une bataille, une campagne ou une période, tu ne peux pas répondre "
                "sans lettre. Dis en une phrase que tu n'as pas ta correspondance "
                "sous la main pour ce sujet, puis propose immédiatement : "
                f"{evt_list}. Jamais de contenu inventé.)"
            )
        else:
            no_source_note = (
                "\n\n(RÈGLE ABSOLUE : si ce message porte sur un événement historique, "
                "dis en une phrase que tu n'as pas de correspondance disponible "
                "pour ce sujet et invite ton visiteur à poser une autre question.)"
            )
        next_prompt = user_message + no_source_note
        pending_ids = []
        options = None   # échange libre : les pistes précédentes restent valables

    messages.append({"role": "user", "content": next_prompt})
    raw_answer = execute_turn(chat_client, messages, model)
    speech, anim_actions = _parse_actions(raw_answer)
    messages.append({"role": "assistant", "content": speech})

    if pending_ids:
        mark_letters_used(sconn, db_conv_id, pending_ids, turn + 1)

    state["turn"] = turn + 1
    if options is not None:
        state["branch_options"] = branch_options_summary(options)

    context_text = generate_context(plan.event) if (tool_name != "continuer_recit" and plan.event) else None
    return jsonify({
        "conversation_id": conv_id,
        "speech":          speech,
        "event":           plan.event["event"] if plan.event else "thématique",
        "turn":            state["turn"],
        "doc_count":       len(plan.letters) if tool_name != "continuer_recit" else None,
        "context":         context_text,
        "sources":         _get_sources(pending_ids),
        "actions":         anim_actions,
    })


# ---------------------------------------------------------------------------
# Mode autonome — l'archiviste enquête et pilote, Napoléon raconte
# ---------------------------------------------------------------------------

# Nombre de tours (question + réponse) gardés dans la mémoire du narrateur.
_NARRATION_TURNS_KEPT = 12


def _chat_autonome(frontend_conv_id: str | None, user_message: str, lang: str = "fr"):
    session_key = frontend_conv_id or f"auto-{len(sessions) + 1}"
    session = sessions.get(session_key)
    if session is None or "archive" not in session:
        session = {"archive": Archivist.new_state(),
                   "messages": [{"role": "system", "content": SYSTEM_PROMPT}]}
        sessions[session_key] = session
    state = session["archive"]
    previous_subject = (state["plan"] or {}).get("sujet")

    decision = archivist.decide(state, user_message)

    # L'historique de narration couvre toute la conversation (même après un changement
    # d'épisode) : Napoléon sait ce qu'il a déjà dit et comment il l'a dit.
    subject = (state["plan"] or {}).get("sujet")

    prompt = archivist.narrator_prompt(state, decision, user_message,
                                       nouvel_episode=bool(subject) and subject != previous_subject,
                                       premiere_reponse=len(session["messages"]) == 1)
    if lang != "fr":
        prompt += "\n\n---\n\n" + _consigne_langue(lang)
    session["messages"].append({"role": "user", "content": prompt})
    raw_answer = execute_turn(chat_client, session["messages"], model)
    speech, anim_actions = _parse_actions(raw_answer)
    # Les lettres du tour ne servent qu'une fois : dans l'historique, on ne garde que la
    # question du visiteur (et l'épisode), pour rester léger sur une longue conversation.
    resume = f"Message du visiteur : {user_message}"
    if subject:
        resume = f"Épisode : {subject}\n{resume}"
    session["messages"][-1] = {"role": "user", "content": resume}
    session["messages"].append({"role": "assistant", "content": speech})
    if len(session["messages"]) > 1 + 2 * _NARRATION_TURNS_KEPT:
        session["messages"] = [session["messages"][0]] + session["messages"][-2 * _NARRATION_TURNS_KEPT:]
    Archivist.commit(state, decision, speech)

    # Lettres jointes à la réponse = celles montrées dans les notes (y compris la lettre d'amorce).
    if decision["type"] == "tour":
        served = decision["lettres"]
    else:
        served = [decision["lettre_amorce"]] if decision.get("lettre_amorce") else []
    context_text = None
    if subject and subject != previous_subject and state["plan"].get("debut") and state["plan"].get("fin"):
        context_text = generate_context({"event": subject, "start": state["plan"]["debut"],
                                         "end": state["plan"]["fin"]}, lang)
    return jsonify({
        "conversation_id": session_key,
        "speech":          speech,
        "event":           subject or "thématique",
        "turn":            state["tour"],
        "doc_count":       archivist.doc_count(state) if subject != previous_subject else None,
        "context":         context_text,
        "sources":         _get_sources(served),
        "actions":         anim_actions,
        "chapitre":        decision["chapitre"]["titre"] if decision["type"] == "tour" else None,
        "pistes":          [p["titre"] for p in decision.get("pistes", [])] if decision["type"] == "tour" else [],
        "annotation":      _annotation_traduite(archivist.annotation(state, decision), lang),
    })


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.getenv("NAPOLEON_API_PORT", 5001))
    print(f"Napoleon API ready on :{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
