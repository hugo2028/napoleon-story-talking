"""
Agent Napoléon v2 — récit multi-tour planifié.

Architecture :
  1. Découverte  : toutes les lettres de la période/événement pré-filtrées
  2. Plan        : inventaire complet visible par le LLM + segmentation en tours
  3. Récit       : tour par tour, s'arrête si l'utilisateur ne continue pas
  4. Transition  : quand le sujet est épuisé → événement suivant ou anecdote aléatoire
  5. Fallback    : si aucune lettre trouvée → répond depuis le system prompt + lettre aléatoire comme amorce

Usage :
  python3 pipeline/napoleon_agent.py --question "Quel rôle as-tu joué lors du siège de Toulon ?"
  python3 pipeline/napoleon_agent.py --question "Quand êtes-vous né ?" --auto
  python3 pipeline/napoleon_agent.py  # mode interactif
"""

from __future__ import annotations

import json
import math
import os
import random
import sqlite3
import struct
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
RAG_DB      = ROOT / "data" / "rag" / "napoleon_clean.sqlite"
MEMOIR_DB   = ROOT / "data" / "rag" / "napoleon_memoirs.sqlite"
EVENTS_FILE = ROOT / "napoleon-corpus" / "metadata" / "events_timeline.json"
STATE_DB    = ROOT / "data" / "agent_state.sqlite"

_FIRST_TURN_WINDOW = 2  # lettres pour le tour 1 (avant que le LLM choisisse le rythme)
MAX_ANECDOTE_POOL = 20  # pool pour la lettre aléatoire

AVATAR_GLB_CANDIDATES = [
    ROOT / "web" / "avatar" / "avatar.glb",
    ROOT / "web" / "dist" / "assets" / "avatar-9V8uFWlK.glb",
]

DEFAULT_AVATAR_ANIMATIONS = [
    "parle avec les bras",
    "opening arms",
    "oui de la tête",
    "petit oui de la tête",
    "léger oui vers la droite",
    "soft head no",
    "hard no head",
    "salut militaire bras droit",
    "salutation du corps",
    "coucou bras droit",
    "c'est gagné bras droit",
    "en avant chargez bras droit",
    "geste en colère en boule",
    "lève le point bras droit",
    "montre en haut du bras droit",
    "tend la main droite",
    "pose les cartes bras droit",
    "regarde à l'horizon",
    "regarde à droite",
    "regarde vers la gauche",
    "pleure",
    "implore au sol",
]

ANIMATION_DESCRIPTIONS = {
    # ── Avatar Mixamo actuel (web/avatar/avatar.glb) ──
    "talk_speaking_with_gestures": "gestes de parole génériques avec les deux bras ; narration continue, transition neutre, discours animé",
    "head_nod_yes": "hochement de tête affirmatif ; oui, validation, accord clair",
    "head_nod_hard_emphatic": "hochement de tête appuyé ; affirmation forte, certitude, « absolument »",
    "head_nod_long_agree": "long hochement de tête ; accord réfléchi, approbation calme, « en effet »",
    "head_nod_sarcastic": "hochement de tête ironique ; sarcasme, fausse approbation, mépris amusé",
    "head_shake_no": "secoue la tête ; non, refus, négation",
    "head_shake_annoyed": "secoue la tête avec agacement ; irritation, exaspération, désapprobation",
    "head_shake_thoughtful": "secoue lentement la tête, pensif ; doute, regret, perplexité, « hélas »",
    "gesture_acknowledge_nod": "petit signe de tête de reconnaissance ; prendre acte, saluer un propos, « je vous entends »",
    "gesture_dismiss_wave_off": "geste de la main qui balaie ; écarter une idée, dédain, « peu importe »",
    "gesture_look_away": "détourne le regard ; souvenir pénible, gêne, réflexion, évitement",
    "emotion_angry_gesture": "geste de colère ; indignation, fureur, reproche, trahison",
    "emotion_cocky_confident": "posture fière et sûre de soi ; vantardise, assurance, triomphe personnel, « c'est moi qui l'ai fait »",
    "emotion_happy_hand_gesture": "geste joyeux des mains ; enthousiasme, bonne nouvelle, victoire, plaisir",
    "emotion_relieved_sigh": "soupir de soulagement ; danger écarté, fin d'une épreuve, lassitude",
    "emotion_angry_point": "pointe du doigt avec colère ; accusation, reproche direct, désigner un coupable, « vous ! »",
    "emotion_shake_fist": "secoue le poing ; rage, menace, défi lancé à l'ennemi, révolte",
    "emotion_fist_pump": "poing serré de victoire ; triomphe, succès éclatant, « nous avons gagné ! »",
    "emotion_disappointed": "abattement déçu ; déception, échec, espoir trahi, constat amer",
    "emotion_pouting": "moue boudeuse et contrariée ; vexation, rancune, mécontentement, dépit",
    "gesture_charge": "ordre de charge vers l'avant ; attaque, commandement militaire, élan, « en avant ! »",
    "gesture_salute": "salut militaire ; respect, honneur, armée, discipline, hommage aux soldats",
    "gesture_pointing": "désigne quelque chose du doigt ; un lieu sur la carte, une direction, « là-bas », une armée ennemie",
    "gesture_bow_formal": "révérence formelle ; salutation solennelle, déférence, respect protocolaire",
    "gesture_bow_informal": "petite inclinaison rapide ; salut courtois, remerciement, politesse légère",
    "gesture_waving": "fait signe de la main ; bonjour, au revoir, accueil, appel amical",
    "gesture_telling_secret": "se penche pour faire une confidence ; secret, aparté, révélation, « entre nous »",
    "gesture_shoulder_rubbing": "se frotte l'épaule ; fatigue, douleur, blessure, lassitude après l'effort",
    "idle_weight_shift": "posture de repos, transfert du poids d'une jambe à l'autre ; attente sans parler",
    # ── Ancien avatar ──
    "c'est gagné bras droit": "geste de victoire avec le bras droit ; conclusion forte, succès, triomphe, point remporté",
    "coucou bras droit": "salutation du bras droit",
    "en avant chargez bras droit": "ordre énergique vers l'avant avec le bras droit ; attaque, décision militaire, impulsion",
    "et bas alors ?": "à utiliser lorsqu'on veut dire « regardez ça ! » ou « c'est moi qui l'ai fait »",
    "geste en colère en boule": "posture tendue et colère contenue ; indignation, tension, menace, frustration",
    "hard no head": "refus net de la tête ; désaccord ferme, négation catégorique",
    "hof": "haussement d'épaule et tête penchée sur le côté ; à utiliser lorsqu'il pousse un soupir",
    "implore au sol": "se met à genou et lève les mains ; implore",
    "incline tête à droite": "inclinaison de tête ; réflexion, nuance, écoute, prudence",
    "laisse tomber main droite": "main droite qui retombe ; déception, abandon, lassitude",
    "laisser tomber bras droit": "bras droit qui s'abaisse ; renoncement, constat amer, fin d'élan",
    "lève le point bras droit": "poing droit levé ; autorité, serment, colère, volonté",
    "lève le tête vers la gauche": "regard et tête levés vers la gauche ; souvenir, réflexion, regard vers le passé",
    "lève les épaules": "haussement d'épaules ; fatalisme, incertitude, relativisation",
    "léger oui vers la droite": "petit acquiescement vers la droite ; accord discret, confirmation nuancée",
    "montre en haut du bras droit": "désigne vers le haut avec le bras droit ; idée importante, direction, démonstration",
    "opening arms": "bras ouverts ; explication ample, accueil, grandeur, émotion généreuse",
    "oui de la tête": "acquiescement clair ; validation, certitude, conclusion affirmative",
    "parle avec les bras": "gestes de parole génériques avec les bras ; narration continue, transition neutre, discours animé",
    "petit oui de la tête": "petit acquiescement ; confirmation douce, assentiment léger",
    "pleure": "geste de tristesse ; perte, douleur, exil, souvenir pénible",
    "pose les cartes bras droit": "pose ou désigne des cartes avec le bras droit ; stratégie, plan, campagne, explication tactique",
    "regarde discrètement en se penchant vers la droite": "regard discret en se penchant ; confidence, secret, méfiance, aparté",
    "regarde vers la gauche": "regard à gauche ; souvenir, hésitation, détour narratif",
    "regarde à droite": "regard à droite ; réaction, transition, adresse latérale",
    "regarde à l'horizon": "regard lointain ; mémoire, ambition, exil, vision d'ensemble",
    "s'essuie visage bras gauche": "s'essuie le visage ; fatigue, douleur, émotion contenue",
    "salut militaire bras droit": "salut militaire du bras droit ; respect, armée, honneur, discipline",
    "salutation du corps": "salutation formelle du corps ; accueil solennel, prise de parole, respect",
    "soft head no": "refus doux de la tête ; doute, correction, désaccord mesuré",
    "tend la main droite": "main droite tendue ; appel, invitation, offre, demande d'attention",
    "waiting": "posture neutre ; aucun geste spécifique ne convient, pause ou respiration",
}

def _load_avatar_animation_names() -> list[str]:
    for path in AVATAR_GLB_CANDIDATES:
        try:
            data = path.read_bytes()
            json_len, json_type = struct.unpack_from("<II", data, 12)
            if json_type != 0x4E4F534A:
                continue
            gltf = json.loads(data[20:20 + json_len].decode("utf-8"))
        except (OSError, struct.error, json.JSONDecodeError, UnicodeDecodeError):
            continue

        names = []
        for animation in gltf.get("animations", []):
            name = animation.get("name")
            if not name:
                continue
            # "_backup_*" : sources Mixamo brutes conservées dans le .blend, jamais à jouer
            if name.startswith(("Armature", "_")) or name in {"faceit_shape_action", "overwrite_shape_action"}:
                continue
            names.append(name)
        if names:
            return names
    return DEFAULT_AVATAR_ANIMATIONS


AVATAR_ANIMATIONS = _load_avatar_animation_names()
# Les animations "idle_*" servent de posture de repos côté frontend : on ne les
# propose pas au LLM comme gestes. "waiting" est un geste neutre virtuel (le
# frontend ne joue rien de particulier) utilisé quand aucun geste ne convient.
# Gestes retirés des choix du narrateur (ils restent dans le modèle) : la confidence penchée sonnait faux.
EXCLUDED_GESTURES = {"gesture_telling_secret"}
AVATAR_GESTURE_ANIMATIONS = [
    name for name in AVATAR_ANIMATIONS
    if not name.startswith(("idle_", "turn_")) and name not in EXCLUDED_GESTURES   # turn_* : pas de pivot
]
if "waiting" not in AVATAR_GESTURE_ANIMATIONS:
    AVATAR_GESTURE_ANIMATIONS.append("waiting")


def _format_animation_prompt(names: list[str]) -> str:
    lines = []
    for name in names:
        description = ANIMATION_DESCRIPTIONS.get(
            name,
            "animation disponible ; choisis-la uniquement si son nom correspond clairement au segment",
        )
        lines.append(f"- {name} — {description}")
    return "\n".join(lines)


ANIMATION_PROMPT = _format_animation_prompt(AVATAR_GESTURE_ANIMATIONS)

# ---------------------------------------------------------------------------
# Fiche de ce que Napoléon sait de lui-même à Sainte-Hélène (hors lettres), injectée dans le system prompt
# ---------------------------------------------------------------------------

FICHE_FILE = ROOT / "napoleon-corpus" / "metadata" / "napoleon_fiche.md"


def load_fiche() -> list[dict]:
    """Faits de la fiche : une entrée par ligne « - … », avec un identifiant (f1, f2…) et sa rubrique « ## … ».
    Le reste du fichier est de la documentation. Pas injectée dans chaque prompt : l'archiviste la consulte
    (outil fiche_personnelle) et ne transmet au narrateur que les faits utiles au tour."""
    try:
        text = FICHE_FILE.read_text(encoding="utf-8")
    except OSError:
        return []
    faits, rubrique = [], ""
    for line in text.splitlines():
        if line.startswith("## "):
            rubrique = line[3:].strip()
        elif line.startswith("- "):
            faits.append({"id": f"f{len(faits) + 1}", "rubrique": rubrique, "texte": line[2:].strip()})
    return faits


NAPOLEON_FICHE = load_fiche()

SYSTEM_PROMPT = f"""\
Tu es Napoléon Bonaparte à Sainte-Hélène. Tu racontes ta vie à ton interlocuteur \
comme un récit vivant, à la première personne, en français \n(ou dans la langue de la conversation si une consigne de LANGUE te l'indique).

Tu t'appuies UNIQUEMENT sur les lettres et passages fournis dans le contexte de chaque tour. \
Tu parles de vive voix depuis ta mémoire — jamais depuis une correspondance lue à voix haute. \
N'annonce jamais « dans une de mes lettres… », « dans cette lettre… » ou « je notais que… ». \
Seule exception : quand le tour ne te fournit aucune lettre, dis-le franchement, en personnage — \
« Je n'ai pas trouvé de lettre sur ce sujet, mais dans mes écrits je reviens sur ce passage… », \
« Je n'en ai pas de trace écrite sous la main, mais je m'en souviens… », ou « Je ne trouve aucune trace \
écrite de ce passage ; en revanche, je peux vous parler de… ».

Fais entendre tes propres mots : quand des « citations choisies » te sont fournies, glisse-les telles quelles \
entre guillemets « », chacune une seule fois, comme les paroles que tu écris ou dictes à cet instant \
(« J'écris à Joséphine : « … » »), en amenant la citation pour que son sens soit clair (à qui, pourquoi). \
Si aucune citation n'est fournie, tu peux citer au plus une phrase complète de la lettre, recopiée mot pour mot, \
qui dit quelque chose par elle-même (une pensée, un sentiment, une décision) — jamais un chiffre, \
un ordre de marche ou un fragment de phrase. Tout le reste est raconté de vive voix.

Construction du récit — une seule conversation, au présent :
- Tu es à Sainte-Hélène, face à ton visiteur : c'est le décor de toute la conversation, posé une fois pour toutes. Ce n'est pas une formule à répéter : ton visiteur sait où il est. Chaque réponse reprend le fil exactement là où la précédente l'a laissé, comme un conteur qui poursuit au cours d'une même soirée. Relis ce que tu as déjà dit et ne recommence jamais par les mêmes mots ni par la même tournure ; l'exil n'affleure que quand il apporte quelque chose (un regret, une comparaison, un jugement d'aujourd'hui).
- Plonge dans chaque lettre comme si tu y étais : ancre le moment avec sa date dite à voix haute et, si la lettre l'indique, le lieu, puis raconte AU PRÉSENT, comme une scène que tu revis : « je suis…, je vois…, je dis à Berthier…, j'écris à Joséphine qu'elle me manque… ».
- Pour passer à la lettre suivante, nouvelle ancre temporelle (« Quelques jours plus tard, le 20… »).
- Termine en relevant la tête vers ton visiteur pour proposer la suite, sans formule rituelle.
- Nomme toujours la personne à qui tu écris ou donnes un ordre (« j'écris à Joséphine… », \
« j'ordonne à Murat… ») : jamais de « je lui écris » sans que l'on sache de qui il s'agit.
- Quand tu ouvres un nouvel épisode, nomme-le clairement avant de plonger dans les lettres : \
la campagne ou la période, l'année, l'adversaire ou l'enjeu (« C'était la campagne de 1805 contre \
l'Autriche et la Russie, celle qui me mena jusqu'à Austerlitz. »). Ton visiteur doit toujours savoir où il est.
- Marque les respirations du récit avec la balise [pause], seule entre deux phrases : entre deux scènes ou deux lettres, et juste avant la question finale. \
2 à 4 balises [pause] par réponse, jamais au milieu d'une phrase.

Tu parles TOUJOURS À ton interlocuteur (le visiteur en face de toi à Sainte-Hélène), \
jamais AUX personnes mentionnées dans tes lettres. \
Même si une lettre est adressée à Joséphine, à un général ou à un ministre, \
tu en restitues le contenu à la 3e personne : \
« Je lui disais que… », « Elle me manquait terriblement », « J'espérais qu'elle viendrait me rejoindre ». \
N'emploie jamais le "tu" ou le "vous" pour t'adresser à Joséphine, à tes généraux ou à quiconque \
figurant dans tes lettres — seul ton interlocuteur du moment peut être interpellé.

Règles absolues :
- Tu vis au printemps 1821, à Sainte-Hélène. Tu ignores tout ce qui s'est passé après, y compris ta propre mort. \
Si ton visiteur évoque une invention, un pays, un événement ou une personne postérieurs à ton temps, \
tu ne sais pas de quoi il parle : réponds en homme de 1821, sans jamais faire semblant de savoir.
- Tout fait précis — nom, date, lieu, chiffre, événement — doit figurer explicitement \
dans les lettres fournies ou dans les faits de ta fiche personnelle quand le tour t'en donne. \
N'invente rien, n'ajoute aucun détail \
tiré de ta connaissance générale.
- Il en va de même des idées : ne dis que ce que disent les lettres. Pas de développement, de \
commentaire, de morale ni de conclusion de ton cru ; reformule fidèlement, sans amplifier.
- Si les lettres disponibles ne couvrent pas la question posée, dis-le en restant en personnage \
et sans méta-commentaire : "Mes souvenirs de cette période sont flous sur ce point…", \
"Je n'ai plus trace précise de cet événement…" Puis rattache-toi \
à ce que tes lettres disent réellement.
- Ne mentionne jamais un nom propre, une bataille, un amiral, un chiffre qui ne figure \
ni dans les lettres du contexte ni dans ta fiche personnelle.
- Une question à laquelle ni tes lettres ni ta fiche ne répondent, tu ne la traites pas sur le fond : \
dis-le en restant en personnage, en une phrase, puis ramène ton visiteur vers ce dont tu as la trace.
- Sois concis : 4 à 6 phrases maximum par réponse. C'est une conversation, pas un discours. \
Laisse ton interlocuteur réagir, poser des questions, demander la suite.
- Termine chaque réponse en suivant la consigne « Suite du récit » du tour : \
quand elle propose deux pistes, offre à ton visiteur de choisir entre les deux, \
chacune évoquée par un détail concret ; sinon, une courte phrase d'accroche. \
Varie la formulation à chaque fois, ne répète jamais la même.
- N'interroge JAMAIS ton interlocuteur sur sa vie personnelle, ses sentiments ou ses expériences. \
Tu es le narrateur, lui l'auditeur. Toute accroche ou tout choix final doit pointer vers la suite de TON récit \
(« voulez-vous que je vous conduise à… ou préférez-vous… ? », « ce qui suivit fut… »), \
jamais vers une introspection de sa part.
- Annote chaque phrase ou groupe de phrases avec UNE balise d'animation en début de segment, \
au format exact [anim:nom exact]. Dans la balise, recopie uniquement le nom exact placé avant le tiret descriptif. \
Choisis uniquement parmi ces animations disponibles dans l'avatar : \
{ANIMATION_PROMPT}
Planifie un maximum de gestes naturels : utilise généralement 4 à 6 balises [anim:] pour une réponse longue, en répartissant les gestes au fil des phrases. \
Privilégie les gestes visibles quand ils conviennent : hochements et refus de la tête, gestes de la main, émotions marquées. \
Fais correspondre l'animation au sens du segment : affirmation, refus, doute, fierté, colère, joie, soulagement, regard détourné. \
Varie les animations autant que possible et évite de répéter mécaniquement le même mouvement. \
N'utilise [anim:waiting] que si aucune animation ne convient vraiment au segment. \
Exemple : [anim:emotion_angry_gesture] La situation était critique. [anim:head_nod_hard_emphatic] Mais j'ai cru en mes soldats. [anim:emotion_cocky_confident] Nous avons tenu.
- Mise en scène : tu peux aussi choisir le plan de la caméra avec une balise [cam:plan], placée comme les \
balises d'animation au début d'un segment : [cam:large] (plan d'ensemble : récits de batailles, transitions, \
la pièce), [cam:rapproche] (buste : la conversation ordinaire), [cam:visage] (gros plan : un aveu, un regret, \
une émotion forte, une citation qui compte), [cam:gauche] (de trois-quarts depuis la cheminée, avec le bureau \
et la carte derrière toi : un récit de campagne, une lettre que tu évoques), [cam:droite] (de trois-quarts depuis \
le bureau, avec la fenêtre et l'échiquier : la vie à Longwood, tes compagnons, la mer), [cam:plongee] (vue haute, \
l'homme seul dans la pièce : l'exil, la captivité, la défaite), [cam:travelling] (lente avancée vers toi pendant \
une dizaine de secondes : un récit qui monte en tension, une révélation), [cam:tableau] (le tableau mural de \
face, quand tu montres la carte ou l'œuvre qui y est épinglée, puis reviens vers toi). Une à trois balises [cam:] par réponse \
au plus, jamais deux de suite au même plan ; varie les angles d'une réponse à l'autre ; le gros plan reste rare \
et bref, reviens ensuite à un plan plus large.
- Prose continue, style oral — pas de listes ni de tirets.
"""

# ---------------------------------------------------------------------------
# Base de données d'état des conversations
# ---------------------------------------------------------------------------

def open_state_db() -> sqlite3.Connection:
    """Ouvre (et initialise si besoin) la base d'état agent_state.sqlite."""
    STATE_DB.parent.mkdir(parents=True, exist_ok=True)
    sconn = sqlite3.connect(STATE_DB, check_same_thread=False)
    sconn.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id          TEXT PRIMARY KEY,
            question    TEXT,
            event_name  TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        )
    """)
    sconn.execute("""
        CREATE TABLE IF NOT EXISTS conversation_letters (
            conversation_id  TEXT  NOT NULL,
            letter_id        INTEGER NOT NULL,
            date_iso         TEXT,
            score            REAL,
            status           TEXT  DEFAULT 'pending',  -- 'pending' | 'used'
            turn_used        INTEGER,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        )
    """)
    sconn.commit()
    return sconn


def create_conversation(sconn: sqlite3.Connection, question: str, event_name: str | None) -> str:
    """Crée une nouvelle conversation et retourne son ID."""
    import uuid
    conv_id = str(uuid.uuid4())[:8]
    sconn.execute(
        "INSERT INTO conversations (id, question, event_name) VALUES (?, ?, ?)",
        (conv_id, question, event_name)
    )
    sconn.commit()
    return conv_id


def insert_conversation_letters(sconn: sqlite3.Connection, conv_id: str, letters: list[dict]):
    """Insère toutes les lettres sélectionnées pour la conversation (status=pending)."""
    sconn.executemany(
        "INSERT INTO conversation_letters (conversation_id, letter_id, date_iso, score) VALUES (?, ?, ?, ?)",
        [(conv_id, l["id"], l.get("date_iso"), l.get("score")) for l in letters]
    )
    sconn.commit()


def get_pending_letters(sconn: sqlite3.Connection, conv_id: str) -> list[dict]:
    """Retourne les lettres non encore utilisées, triées par date."""
    rows = sconn.execute(
        "SELECT letter_id, date_iso, score FROM conversation_letters "
        "WHERE conversation_id = ? AND status = 'pending' ORDER BY date_iso",
        (conv_id,)
    ).fetchall()
    return [{"id": r[0], "date_iso": r[1], "score": r[2]} for r in rows]


def get_used_letters(sconn: sqlite3.Connection, conv_id: str) -> list[dict]:
    """Retourne les lettres déjà utilisées avec leur tour."""
    rows = sconn.execute(
        "SELECT letter_id, date_iso, turn_used FROM conversation_letters "
        "WHERE conversation_id = ? AND status = 'used' ORDER BY turn_used, date_iso",
        (conv_id,)
    ).fetchall()
    return [{"id": r[0], "date_iso": r[1], "turn": r[2]} for r in rows]


def mark_letters_used(sconn: sqlite3.Connection, conv_id: str, letter_ids: list[int], turn: int):
    """Marque un ensemble de lettres comme utilisées."""
    sconn.executemany(
        "UPDATE conversation_letters SET status = 'used', turn_used = ? "
        "WHERE conversation_id = ? AND letter_id = ?",
        [(turn, conv_id, lid) for lid in letter_ids]
    )
    sconn.commit()


# ---------------------------------------------------------------------------
# Structures de données
# ---------------------------------------------------------------------------

@dataclass
class NarrativePlan:
    letters: list[dict]          # toutes les lettres, triées par date
    segments: list[list[dict]]   # découpées en tours
    event: dict | None           # événement correspondant
    next_events: list[dict]      # événements suivants dans la timeline
    memoir_chunks: list[dict]    # passages mémoires SH
    has_source: bool             # False si aucune lettre trouvée


# ---------------------------------------------------------------------------
# Helpers base de données
# ---------------------------------------------------------------------------

def cosine_sim(q: np.ndarray, M: np.ndarray) -> np.ndarray:
    q_norm = q / (np.linalg.norm(q) + 1e-10)
    norms = np.linalg.norm(M, axis=1, keepdims=True) + 1e-10
    return (M / norms) @ q_norm


def load_db(db_path: Path):
    conn = sqlite3.connect(db_path, check_same_thread=False)
    rows = conn.execute("SELECT chunk_id, vector FROM embeddings ORDER BY chunk_id").fetchall()
    chunk_ids = [r[0] for r in rows]
    emb_matrix = np.array([np.frombuffer(r[1], dtype=np.float32) for r in rows])
    return conn, emb_matrix, chunk_ids


def fetch_chunks(conn, ids: list[int]) -> list[dict]:
    col_names = [d[0] for d in conn.execute("SELECT * FROM chunks LIMIT 0").description]
    results = []
    for cid in ids:
        row = conn.execute("SELECT * FROM chunks WHERE id=?", (cid,)).fetchone()
        if row:
            results.append(dict(zip(col_names, row)))
    return results


def embed_question(client, text: str) -> np.ndarray:
    resp = client.embeddings.create(input=[text], model="text-embedding-3-small")
    return np.array(resp.data[0].embedding, dtype=np.float32)


def date_in_event(date_iso: str, event: dict) -> bool:
    if not date_iso or len(date_iso) < 7:
        return False
    return event["start"][:7] <= date_iso[:7] <= event["end"][:7]


def _add_months(ym: str, n: int) -> str:
    """Ajoute n mois à une chaîne YYYY-MM. Clampé à 1769-01 / 1821-12."""
    y, m = int(ym[:4]), int(ym[5:7])
    m += n
    while m > 12: m -= 12; y += 1
    while m < 1:  m += 12; y -= 1
    return f"{max(1769, min(1821, y)):04d}-{max(1, min(12, m)):02d}"


# ---------------------------------------------------------------------------
# Formatage du contexte
# ---------------------------------------------------------------------------

def format_inventory(letters: list[dict]) -> str:
    """Dates uniquement — le contenu est réservé aux lettres du tour courant."""
    lines = []
    for i, c in enumerate(letters, 1):
        date = c.get("date_iso") or "date inconnue"
        lines.append(f"  [{i:2d}] {date}")
    return "\n".join(lines)


def format_letters_full(letters: list[dict]) -> str:
    """Lettres complètes pour le récit (600 chars chacune)."""
    parts = []
    for i, c in enumerate(letters, 1):
        date = c.get("date_iso") or "date inconnue"
        text = c.get("text", "").strip()[:600]
        parts.append(f"[{date}]\n{text}")
    return "\n\n".join(parts) if parts else "(aucune lettre)"


def _letter_teaser(letter: dict, n: int = 160) -> str:
    date = letter.get("date_iso") or "date inconnue"
    return f"[{date}] {(letter.get('text') or '').strip()[:n]}…"


def pick_branch_options(candidates: list[dict]) -> list[dict]:
    """
    Choisit jusqu'à deux lettres à proposer comme pistes pour la suite.
    A = la prochaine lettre ; B = une lettre plus loin dans la suite (date différente
    si possible) pour offrir une vraie bifurcation. Une seule lettre → une seule piste.
    """
    if len(candidates) < 2:
        return candidates[:1]
    a, rest = candidates[0], candidates[1:]
    mid = len(rest) // 2
    ordered = rest[mid:] + rest[:mid]
    b = next((c for c in ordered if c.get("date_iso") != a.get("date_iso")), rest[0])
    return [a, b]


def format_branch_instruction(options: list[dict], next_event: str | None = None) -> str:
    """Consigne de fin de tour : choix entre deux pistes, accroche unique, ou transition."""
    if len(options) >= 2:
        lines = "\n".join(f"{key}) {_letter_teaser(o)}" for key, o in zip("AB", options))
        return (
            "Suite du récit — CHOIX À PROPOSER (obligatoire ce tour) : plusieurs lettres s'offrent pour la suite. "
            "Ne les raconte pas maintenant. Termine par UNE phrase interrogative "
            "qui laisse ton visiteur choisir entre ces deux pistes, chacune évoquée par un détail concret "
            "(lieu, personne, moment) tiré de son aperçu, sans en dévoiler la suite "
            "(« Voulez-vous que je vous conduise à… ou préférez-vous que… ? ») :\n" + lines
        )
    if len(options) == 1:
        return (
            "Suite du récit — une seule lettre s'offre pour la suite. Ne la raconte pas maintenant : "
            "termine par une accroche unique et précise appuyée sur ce détail :\n" + _letter_teaser(options[0])
        )
    if next_event:
        return (
            "Suite du récit — tu as raconté toutes les lettres de ce sujet. NE propose PAS de choix "
            "et n'évoque aucun autre moment de ce sujet (tu n'en as plus de trace). "
            f"Termine par une seule accroche qui propose d'enchaîner sur : {next_event}."
        )
    return (
        "Suite du récit — tu as raconté toutes les lettres disponibles. NE propose PAS de choix : "
        "conclus ce chapitre et invite ton visiteur à te poser une autre question."
    )


def branch_options_summary(options: list[dict]) -> list[dict]:
    """Version compacte stockée en session (id, date, aperçu) pour router le choix du visiteur."""
    return [
        {"key": key, "id": o["id"], "date_iso": o.get("date_iso"), "teaser": _letter_teaser(o, 90)}
        for key, o in zip("AB", options)
    ]


def format_memoirs(chunks: list[dict]) -> str:
    parts = []
    for c in chunks:
        title = c.get("title", "Mémoires SH").strip()
        text = c.get("text", "").strip()[:300]
        parts.append(f"[{title}]\n{text}")
    return "\n\n".join(parts) if parts else "(aucun passage)"


# ---------------------------------------------------------------------------
# Classification LLM de la période
# ---------------------------------------------------------------------------

def classify_event(chat_client, question: str, events: list[dict], model: str) -> dict | None:
    """
    Appelle le LLM pour identifier l'événement correspondant à la question.
    Retourne l'événement trouvé, ou None si la question est thématique/multi-périodes.
    Utilise temperature=0 et max_tokens=20 — appel rapide et économique.
    """
    events_list = "\n".join(
        f"- {e['event']} ({e['start'][:7]} → {e['end'][:7]})"
        for e in events
    )
    prompt = (
        f"Question posée à Napoléon Bonaparte :\n« {question} »\n\n"
        f"À quel événement précis de la liste suivante cette question se réfère-t-elle ?\n\n"
        f"{events_list}\n\n"
        "Réponds UNIQUEMENT par le nom exact d'un événement de la liste, "
        "ou par le mot « thématique » si la question couvre plusieurs périodes "
        "ou ne correspond à aucun événement précis. Aucune explication."
    )
    resp = chat_client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=20,
        temperature=0,
    )
    answer = resp.choices[0].message.content.strip().rstrip(".")
    if answer.lower() == "thématique":
        return None
    # Correspondance exacte d'abord, puis souple
    for event in events:
        if event["event"].lower() == answer.lower():
            return event
    for event in events:
        if event["event"].lower() in answer.lower() or answer.lower() in event["event"].lower():
            return event
    return None


def classify_sub_event(chat_client, question: str, event: dict, model: str) -> str | None:
    """
    Identifie le sous-thème précis de la question dans le cadre d'un événement donné.
    Retourne une string courte (ex: "prise d'Alexandrie") ou None si question générale.
    Appel rapide : max_tokens=15, temperature=0.
    """
    resp = chat_client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": (
            f"Question posée à Napoléon Bonaparte :\n« {question} »\n\n"
            f"Cette question concerne l'événement : {event['event']}.\n"
            "Quel est le sous-thème précis de cette question en 3 à 5 mots ?\n"
            "Réponds uniquement par ce sous-thème, ou par « général » si la question "
            "porte sur l'ensemble de l'événement. Aucune explication."
        )}],
        max_tokens=15,
        temperature=0,
    )
    answer = resp.choices[0].message.content.strip().rstrip(".")
    if answer.lower() in ("général", "general", "générale"):
        return None
    return answer


def build_narrative_plan(client, plan: "NarrativePlan", question: str, model: str) -> str | None:
    """
    Génère un plan narratif (1 phrase par tour) pour guider la cohérence du récit entre les tours.
    Permet à Napoléon de planifier ses transitions dès le tour 1.
    Retourne None si un seul tour ou aucune source disponible.
    Appel économique : max_tokens=300, temperature=0.2.
    """
    if not plan.has_source or not plan.segments or len(plan.segments) <= 1:
        return None

    seg_lines = []
    for i, seg in enumerate(plan.segments, 1):
        dates = [l.get("date_iso", "")[:7] for l in seg if l.get("date_iso")]
        date_range = f"{dates[0]} → {dates[-1]}" if len(dates) > 1 else (dates[0] if dates else "?")
        snippets = " | ".join(l.get("text", "").strip()[:80] for l in seg[:2])
        seg_lines.append(f"Tour {i} ({date_range}) : {snippets}")

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": (
            f"Napoléon Bonaparte va raconter « {question} » en {len(plan.segments)} tours successifs.\n\n"
            f"Contenu de chaque tour (extraits de ses lettres) :\n"
            + "\n".join(seg_lines)
            + "\n\nPour chaque tour, écris UNE phrase indiquant ce que Napoléon doit raconter "
            "et comment la fin de ce tour doit ouvrir naturellement sur le suivant. "
            "Sois précis et factuel — n'invente aucun fait absent des extraits. Format strict :\n"
            "Tour 1 : [phrase]\nTour 2 : [phrase]\n..."
        )}],
        max_tokens=300,
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()


# ---------------------------------------------------------------------------
# Découverte et planification
# ---------------------------------------------------------------------------

def discover(client, question: str,
             conn, emb_matrix, chunk_ids,
             m_conn, m_matrix, m_ids,
             forced_event: dict | None = None,
             sub_topic: str | None = None,
             date_start: str | None = None,
             date_end: str | None = None,
             keywords: list[str] | None = None) -> NarrativePlan:
    """
    Rassemble les lettres pour la question.
    forced_event : événement pré-identifié (par LLM ou re-découverte amorce).
    date_start / date_end : plage YYYY-MM optionnelle — prioritaire sur forced_event quand fournie.
    keywords : mots-clés additionnels à booster (garantissent l'inclusion même sous le seuil sémantique).
    Sans fenêtre (ni event, ni dates) : mode thématique top-15 global.
    """
    events = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
    col_names = [d[0] for d in conn.execute("SELECT * FROM chunks LIMIT 0").description]

    q_vec = embed_question(client, question)
    sims = cosine_sim(q_vec, emb_matrix)
    top50_idx = np.argsort(sims)[::-1][:50]

    id_to_sim_idx = {chunk_ids[i]: i for i in range(len(chunk_ids))}

    matched_event = forced_event  # None → mode thématique ou plage date

    # Déterminer la plage de dates effective (dates explicites prioritaires sur l'événement)
    if date_start or date_end:
        range_start = (date_start or "1769-01")[:7]
        range_end   = (date_end   or "1821-12")[:7]
    elif matched_event:
        range_start = matched_event["start"][:7]
        range_end   = matched_event["end"][:7]
    else:
        range_start = range_end = None

    # Fusionner les mots-clés : explicites + dérivés du sous-thème (dédupliqués)
    effective_keywords = list(keywords or [])
    if sub_topic:
        effective_keywords += [w for w in sub_topic.lower().split() if len(w) > 3]
    effective_keywords = list(dict.fromkeys(effective_keywords))

    if range_start:
        rows = conn.execute(
            "SELECT id FROM chunks WHERE date_iso >= ? AND date_iso <= ? AND date_reliable != 0",
            (range_start, range_end + "\xff")
        ).fetchall()
        ids = [r[0] for r in rows]
        range_label = matched_event["event"] if matched_event and not (date_start or date_end) \
                      else f"{range_start}-{range_end}"

        # ── Mode keyword + expansion temporelle ─────────────────────────────
        # Cherche les lettres-graines contenant les mots-clés dans la fenêtre,
        # puis élargit ±1 mois autour d'elles. Le LLM reçoit toutes ces lettres
        # dans l'ordre chronologique et décide lui-même lesquelles retenir.
        use_temporal = False
        if effective_keywords:
            seed_dates = []
            for kw in effective_keywords:
                kw_rows = conn.execute(
                    "SELECT date_iso FROM chunks WHERE id IN ({}) AND lower(text) LIKE ?".format(
                        ",".join("?" * len(ids))
                    ),
                    (*ids, f"%{kw.lower()}%")
                ).fetchall()
                seed_dates += [r[0][:7] for r in kw_rows if r[0] and len(r[0]) >= 7]

            if seed_dates:
                use_temporal = True
                min_seed = min(seed_dates)
                max_seed = max(seed_dates)
                exp_start = max(_add_months(min_seed, -1), range_start)
                exp_end   = min(_add_months(max_seed, +1), range_end)
                print(f"[DEBUG] kw-temporal [{range_label}]: graines={len(seed_dates)} "
                      f"{min_seed}-{max_seed}  fenetre={exp_start}-{exp_end}")

                exp_rows = conn.execute(
                    "SELECT id FROM chunks WHERE date_iso >= ? AND date_iso <= ? AND date_reliable != 0",
                    (exp_start, exp_end + "\xff")
                ).fetchall()
                letters = fetch_chunks(conn, [r[0] for r in exp_rows])
                for l in letters:
                    idx = id_to_sim_idx.get(l["id"])
                    l["score"] = float(sims[idx]) if idx is not None else 0.0
                letters.sort(key=lambda c: c.get("date_iso") or "9999")
                letters = letters[:30]  # le LLM sélectionne parmi ces lettres
                print(f"[DEBUG] kw-temporal: {len(letters)} lettres transmises au LLM")
                has_source = bool(letters)

        if not use_temporal:
            # ── Mode sémantique : score + filtre + sampling ──────────────────
            MAX_LETTERS = 15
            POOL_SIZE   = 40
            MIN_SCORE   = 0.35
            MIN_LETTERS_EVENT = 8   # minimum quand la période est connue
            letters = fetch_chunks(conn, ids)
            print(f"[DEBUG] sémantique [{range_label}]  sub_topic={sub_topic!r}  window={len(letters)} lettres")

            # Score principal (question originale)
            for l in letters:
                idx = id_to_sim_idx.get(l["id"])
                l["score"] = float(sims[idx]) if idx is not None else 0.0

            # Score secondaire si sous-thème détecté
            if sub_topic:
                sub_vec  = embed_question(client, sub_topic)
                sub_sims = cosine_sim(sub_vec, emb_matrix)
                for l in letters:
                    idx = id_to_sim_idx.get(l["id"])
                    sub_score = float(sub_sims[idx]) if idx is not None else 0.0
                    l["score"] = max(l["score"], sub_score)

            # Keyword boost : lettres contenant les mots-clés garanties à MIN_SCORE
            if effective_keywords:
                keyword_ids = set()
                for kw in effective_keywords:
                    rows_kw = conn.execute(
                        "SELECT id FROM chunks WHERE id IN ({}) AND lower(text) LIKE ?".format(
                            ",".join("?" * len(ids))
                        ),
                        (*ids, f"%{kw.lower()}%")
                    ).fetchall()
                    keyword_ids.update(r[0] for r in rows_kw)
                kw_boost = 0
                for l in letters:
                    if l["id"] in keyword_ids and l["score"] < MIN_SCORE:
                        l["score"] = MIN_SCORE
                        kw_boost += 1
                if kw_boost:
                    print(f"[DEBUG] keyword boost: {kw_boost} lettres relevées au seuil")

            # Debug : top-10 par score avant filtre
            top_debug = sorted(letters, key=lambda l: -l["score"])[:10]
            for d in top_debug:
                print(f"[DEBUG]   {d.get('date_iso','?')}  score={d['score']:.3f}  id={d['id']}")
            below = sum(1 for l in letters if l["score"] < MIN_SCORE)
            print(f"[DEBUG] sous MIN_SCORE({MIN_SCORE}): {below}/{len(letters)}")

            # Filtrer par MIN_SCORE
            all_scored = letters
            letters = [l for l in letters if l["score"] >= MIN_SCORE]
            # Période déjà identifiée (événement) : garantir assez de matière pour un récit
            # en plusieurs tours, même si la requête courte donne des scores bas.
            if matched_event and len(letters) < MIN_LETTERS_EVENT and len(all_scored) > len(letters):
                letters = sorted(all_scored, key=lambda l: -l["score"])[:MIN_LETTERS_EVENT]
                print(f"[DEBUG] événement identifié : complété à {len(letters)} lettres (meilleurs scores)")
            if not letters:
                # Fallback : top-8 même sous le seuil
                all_in_window = fetch_chunks(conn, ids)
                for l in all_in_window:
                    idx = id_to_sim_idx.get(l["id"])
                    l["score"] = float(sims[idx]) if idx is not None else 0.0
                letters = sorted(all_in_window, key=lambda l: -l["score"])[:8]
            else:
                # Pool élargi → sampling pondéré par score² pour la diversité
                pool = sorted(letters, key=lambda l: -l["score"])[:POOL_SIZE]
                if len(pool) > MAX_LETTERS:
                    weights = [l["score"] ** 2 for l in pool]
                    selected = []
                    indices = list(range(len(pool)))
                    while len(selected) < MAX_LETTERS and indices:
                        w = [weights[i] for i in indices]
                        total = sum(w)
                        r = random.random() * total
                        cumul = 0.0
                        for pos, i in enumerate(indices):
                            cumul += w[pos]
                            if r <= cumul:
                                selected.append(pool[i])
                                indices.pop(pos)
                                break
                    letters = selected
                else:
                    letters = pool

            letters.sort(key=lambda c: c.get("date_iso") or "9999")
            has_source = True

        # Événements suivants (après la fin de la fenêtre)
        ref_end = matched_event["end"] if matched_event else range_end
        next_events = sorted(
            [e for e in events if e["start"] > ref_end],
            key=lambda e: e["start"]
        )[:3]

    else:
        # Pas d'événement unique dominant : mode thématique ou question sans source
        # Collecter les meilleures lettres toutes périodes confondues (top-20)
        top_candidates = []
        for idx in top50_idx[:20]:
            cid = chunk_ids[idx]
            row = conn.execute("SELECT * FROM chunks WHERE id=?", (cid,)).fetchone()
            d = dict(zip(col_names, row))
            d["score"] = float(sims[idx])
            top_candidates.append(d)

        # Exclure les entrées hors corpus Napoléon (sources secondaires postérieures à 1821)
        # et les chunks avec dates non fiables (écrits historiques, dates de faits discutés)
        top_candidates = [c for c in top_candidates
                          if c.get("date_reliable", 1) != 0
                          and (not c.get("date_iso") or c.get("date_iso", "")[:4] <= "1821")]

        best_score = top_candidates[0]["score"] if top_candidates else 0
        # Seuil élevé : sans événement unique, on exige une vraie pertinence sémantique
        if best_score >= 0.50:
            # Mode thématique : top 15 par score, triés chronologiquement
            letters = sorted(top_candidates[:15], key=lambda c: c.get("date_iso") or "9999")
            has_source = True
            # next_events : événements qui commencent après la dernière lettre sélectionnée
            last_date = letters[-1].get("date_iso", "") if letters else ""
            next_events = sorted(
                [e for e in events if e["start"] > last_date[:10]],
                key=lambda e: e["start"]
            )[:3]
        else:
            # Pas de lettre pertinente → réponse depuis le system prompt + amorce aléatoire
            letters = []
            has_source = False
            next_events = sorted(events, key=lambda e: e["start"])[:3]

    # Mémoires SH — toujours inclus, sans seuil de score.
    # Ils donnent la perspective de fin de vie et servent de cadre narratif,
    # même si leur similarité avec la question est faible.
    memoir_chunks = []
    if m_conn is not None:
        m_sims = cosine_sim(q_vec, m_matrix)
        m_col = [d[0] for d in m_conn.execute("SELECT * FROM chunks LIMIT 0").description]
        for midx in np.argsort(m_sims)[::-1][:3]:  # top-3, pas de seuil minimum
            cid = m_ids[midx]
            row = m_conn.execute("SELECT * FROM chunks WHERE id=?", (cid,)).fetchone()
            if row:
                d = dict(zip(m_col, row))
                d["score"] = float(m_sims[midx])
                memoir_chunks.append(d)

    # Segmentation initiale : fenêtre du premier tour (le LLM choisit ensuite le rythme)
    segments = [letters[i:i + _FIRST_TURN_WINDOW] for i in range(0, max(len(letters), 1), _FIRST_TURN_WINDOW)]
    if not segments:
        segments = [[]]

    return NarrativePlan(
        letters=letters,
        segments=segments,
        event=matched_event,
        next_events=next_events,
        memoir_chunks=memoir_chunks,
        has_source=has_source,
    )


def get_random_letter(conn, exclude_event: dict | None = None,
                      emb_matrix: np.ndarray | None = None,
                      chunk_ids: list | None = None) -> dict | None:
    """
    Lettre aléatoire pour anecdote ou amorce.
    Tire au hasard parmi un pool de lettres avec date complète (YYYY-MM-DD),
    hors de la période courante si exclude_event fourni.
    """
    col_names = [d[0] for d in conn.execute("SELECT * FROM chunks LIMIT 0").description]
    if exclude_event:
        rows = conn.execute(
            "SELECT id FROM chunks WHERE length(date_iso) = 10 AND date_reliable != 0 "
            "AND (date_iso < ? OR date_iso > ?)",
            (exclude_event["start"][:7], exclude_event["end"][:7])
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id FROM chunks WHERE length(date_iso) = 10 AND date_reliable != 0"
        ).fetchall()
    if not rows:
        return None
    # Tirer un échantillon aléatoire parmi les disponibles
    sample_ids = [r[0] for r in random.sample(rows, min(MAX_ANECDOTE_POOL, len(rows)))]
    row = conn.execute(
        f"SELECT * FROM chunks WHERE id = ?",
        (random.choice(sample_ids),)
    ).fetchone()
    if not row:
        return None
    return dict(zip(col_names, row))


# ---------------------------------------------------------------------------
# Construction des prompts par tour
# ---------------------------------------------------------------------------

def build_first_prompt(plan: NarrativePlan, question: str,
                       narrative_plan: str | None = None,
                       options_out: list | None = None) -> str:
    """
    Prompt du tour 1 : mémoires SH (cadre) + plan narratif + inventaire + lettres du premier segment
    + consigne de fin (choix entre deux pistes quand plusieurs lettres suivent).
    options_out : si fourni, reçoit les pistes proposées (dicts lettre) pour le routage du tour suivant.
    """
    total = len(plan.letters)
    event_name = plan.event["event"] if plan.event else "ce sujet"

    parts = []

    # Mémoires en tête — cadre narratif depuis Sainte-Hélène.
    # Toujours présents : ils donnent la perspective de fin de vie qui ouvre le récit.
    if plan.memoir_chunks:
        parts.append(
            "Passages de tes Œuvres sur ce sujet (écrits des campagnes et du règne, réunis après coup ; "
            "ce ne sont pas des souvenirs de l'exil) : sers-t'en seulement s'ils éclairent le récit, "
            "sans formule d'ouverture répétée ; revis les lettres au présent, chacune ancrée par sa date :\n"
            + format_memoirs(plan.memoir_chunks)
        )

    # Plan narratif global — guide de cohérence entre tous les tours
    if narrative_plan:
        parts.append(
            "Plan narratif global (garde ce fil en tête sur tous les tours — "
            "couvre uniquement les lettres de ce tour, mais anticipe les transitions) :\n"
            + narrative_plan
        )

    if plan.has_source and total > 0:
        parts.append(
            f"Planification du récit — « {event_name} » : {total} lettres au total.\n"
            f"Tu recevras les lettres complètes tour par tour. "
            f"Ne couvre QUE les lettres du tour en cours.\n"
            + format_inventory(plan.letters)
        )
        parts.append(
            f"Lettres de ce premier tour (revis-les au présent, chacune ancrée par sa date) :\n"
            + format_letters_full(plan.segments[0])
        )

        # Pistes pour la suite : choix entre deux lettres quand plusieurs s'offrent
        upcoming = [l for seg in plan.segments[1:] for l in seg]
        options = pick_branch_options(upcoming)
        if options_out is not None:
            options_out.extend(options)
        next_name = plan.next_events[0]["event"] if plan.next_events else None
        parts.append(format_branch_instruction(options, next_event=next_name))
    else:
        # Aucune lettre trouvée : interdire toute réponse inventée.
        # Napoléon doit reconnaître l'absence de source et rediriger.
        if plan.next_events:
            evt_list = " / ".join(e["event"] for e in plan.next_events[:2])
            parts.append(
                "INSTRUCTION ABSOLUE — AUCUNE LETTRE DISPONIBLE POUR CE SUJET : "
                "Tu ne dois pas répondre sur le fond de la question. "
                "Ne donne aucun fait, aucune date, aucune anecdote sur ce thème. "
                "En une phrase, dis que tu n'as pas tes lettres sous la main pour "
                "ce moment précis (sans citer de date ni de détail). "
                "Puis, sans transition, invite ton visiteur à explorer un épisode "
                f"pour lequel tu as tes archives : {evt_list}. "
                "Jamais de contenu inventé. Jamais plus de deux phrases au total."
            )
        else:
            parts.append(
                "INSTRUCTION ABSOLUE — AUCUNE LETTRE DISPONIBLE : "
                "Tu ne dois pas répondre sur le fond de la question. "
                "Dis simplement, en une phrase, que tu préfères t'en tenir "
                "à ce dont tu as un souvenir précis appuyé par ta correspondance, "
                "et invite ton visiteur à te poser une autre question."
            )

    if plan.next_events:
        next_names = ", ".join(e["event"] for e in plan.next_events)
        parts.append(
            f"Événements suivants disponibles si tu épuises ce sujet : {next_names}."
        )

    parts.append(f"Question : {question}")

    parts.append(
        "RAPPEL ABSOLU — registre : tu t'adresses à ton visiteur à Sainte-Hélène, JAMAIS à Joséphine "
        "ni à aucune personne mentionnée dans tes lettres. "
        "Les lettres sont rédigées en « tu » car tu les leur écrivais jadis. "
        "Traduis systématiquement en 3e personne : « je lui disais », « elle me manquait », "
        "« je lui écrivais que… ». N'emploie jamais « tu » ni « vous » pour désigner Joséphine ou un tiers."
    )

    return "\n\n---\n\n".join(parts)


def build_continuation_prompt(plan: NarrativePlan, turn: int, conn) -> str:
    """Prompt pour les tours suivants."""
    seg = plan.segments[turn] if turn < len(plan.segments) else []
    remaining_after = sum(len(s) for s in plan.segments[turn + 1:]) if turn + 1 < len(plan.segments) else 0
    total = len(plan.letters)

    parts = []

    if seg:
        parts.append(
            f"Lettres pour ce tour ({len(seg)} sur {total}"
            + (f", {remaining_after} restantes après ce tour" if remaining_after else ", dernières lettres du sujet")
            + ") :\n"
            + format_letters_full(seg)
        )
    else:
        # Sujet épuisé — anecdote aléatoire
        rand = get_random_letter(conn, exclude_event=plan.event)
        if rand:
            date = rand.get("date_iso") or "date inconnue"
            text = rand.get("text", "").strip()[:400]
            parts.append(
                "Tu as couvert toutes les lettres de ce sujet. "
                "Voici une lettre d'une autre époque qui peut servir d'anecdote ou de transition :\n\n"
                f"[{date}]\n{text}"
            )
        if plan.next_events:
            next_names = " / ".join(e["event"] for e in plan.next_events)
            parts.append(f"Tu peux aussi proposer naturellement d'enchaîner sur : {next_names}.")

    if plan.memoir_chunks:
        parts.append("Passages de tes Œuvres (écrits réunis après coup) :\n" + format_memoirs(plan.memoir_chunks))

    return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# Exécution d'un tour
# ---------------------------------------------------------------------------

def execute_turn(client, messages: list, model: str, max_tokens: int = 600) -> str:
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content.strip()


# ---------------------------------------------------------------------------
# Orchestration principale
# ---------------------------------------------------------------------------

def build_turn_prompt_from_state(sconn, conv_id, plan, turn, conn,
                                 narrative_plan: str | None = None,
                                 n_letters: int = _FIRST_TURN_WINDOW,
                                 prioritize_id: int | None = None,
                                 options_out: list | None = None):
    """
    Construit le prompt d'un tour à partir de l'état BD.
    n_letters : choisi par le LLM via continuer_recit.lettres_ce_tour (1-4).
    prioritize_id : lettre choisie par le visiteur parmi les pistes proposées — servie en premier.
    options_out : si fourni, reçoit les pistes proposées pour la suite (dicts lettre).
    Retourne (prompt, next_ids, plan_exhausted).
    plan_exhausted=True quand il n'y a plus de lettres pending.
    """
    pending = get_pending_letters(sconn, conv_id)
    used    = get_used_letters(sconn, conv_id)

    chosen = None
    if prioritize_id is not None:
        chosen = next((l for l in pending if l["id"] == prioritize_id), None)
        if chosen:
            pending = [chosen] + [l for l in pending if l["id"] != prioritize_id]

    next_batch = pending[:n_letters]
    next_ids   = [l["id"] for l in next_batch]
    remaining  = len(pending) - len(next_batch)
    plan_exhausted = len(pending) == 0

    parts = []

    # Rappel du plan narratif global pour maintenir la cohérence
    if narrative_plan:
        parts.append(f"Plan narratif (rappel — tu es au tour {turn}) :\n{narrative_plan}")

    # Rappel des dates déjà couvertes
    if used:
        dates_used = ", ".join(
            f"{u['date_iso']} (tour {u['turn']})" for u in used
        )
        parts.append(f"Déjà raconté : {dates_used}")

    if next_batch:
        full_letters = fetch_chunks(conn, next_ids)
        id_to_full   = {l["id"]: l for l in full_letters}
        next_full    = [id_to_full[lid] for lid in next_ids if lid in id_to_full]
        if chosen:
            parts.append(
                f"Ton visiteur a choisi la piste du {chosen.get('date_iso') or 'moment proposé'} : "
                "commence ce tour par cette lettre, en plongeant directement dans la scène."
            )
        parts.append(
            f"Lettres de ce tour ({len(next_full)}"
            + (f", {remaining} encore en attente après" if remaining else ", dernières lettres du sujet")
            + ", revis-les au présent, chacune ancrée par sa date) :\n" + format_letters_full(next_full)
        )

        # Pistes pour la suite : choix entre deux lettres quand plusieurs s'offrent
        options = []
        if remaining > 0:
            picked_meta = pick_branch_options(pending[n_letters:])
            full = {l["id"]: l for l in fetch_chunks(conn, [l["id"] for l in picked_meta])}
            options = [full[m["id"]] for m in picked_meta if m["id"] in full]
            if options_out is not None:
                options_out.extend(options)
        next_name = plan.next_events[0]["event"] if plan.next_events else None
        parts.append(format_branch_instruction(options, next_event=next_name))
    else:
        # Sujet épuisé : pre-fetcher les premières lettres du prochain événement
        # comme base réelle pour la transition — pas de connaissance générale
        if plan.next_events:
            next_evt = plan.next_events[0]
            next_rows = conn.execute(
                "SELECT id FROM chunks WHERE date_iso >= ? AND date_iso <= ? AND date_reliable != 0 "
                "ORDER BY date_iso LIMIT 3",
                (next_evt["start"][:7], next_evt["end"][:7] + "\xff")
            ).fetchall()
            teaser_letters = fetch_chunks(conn, [r[0] for r in next_rows])
            if teaser_letters:
                parts.append(
                    f"Toutes les lettres de ce sujet ont été couvertes. "
                    f"Voici les premières lettres du chapitre suivant de ta vie "
                    f"(« {next_evt['event']} »). "
                    f"Appuie-toi UNIQUEMENT sur l'une de ces lettres pour terminer par une "
                    f"phrase naturelle qui invite à continuer — ne cite aucun autre événement "
                    f"ni bataille qui ne figure pas dans ces lettres :\n\n"
                    + format_letters_full(teaser_letters)
                )
            else:
                parts.append(
                    f"Toutes les lettres de ce sujet ont été couvertes. "
                    f"Invite naturellement à continuer vers : {next_evt['event']}. "
                    f"Ne mentionne pas d'autres événements que celui-ci."
                )
        else:
            parts.append("Toutes les lettres ont été couvertes. Conclus le récit naturellement.")

    parts.append(
        "RAPPEL ABSOLU — registre : tu t'adresses à ton visiteur à Sainte-Hélène, JAMAIS à Joséphine "
        "ni à aucune personne mentionnée dans tes lettres. "
        "Les lettres sont rédigées en « tu » car tu les leur écrivais jadis. "
        "Traduis systématiquement en 3e personne : « je lui disais », « elle me manquait », "
        "« je lui écrivais que… ». N'emploie jamais « tu » ni « vous » pour désigner Joséphine ou un tiers."
    )

    return "\n\n---\n\n".join(parts), next_ids, plan_exhausted


def run_story(embed_client, chat_client, question: str,
              conn, emb_matrix, chunk_ids,
              m_conn, m_matrix, m_ids,
              model: str = "gpt-4.1-mini",
              auto: bool = False,
              max_turns: int = 20):

    print(f"\n{'='*60}")
    print(f"QUESTION : {question}")
    print(f"{'='*60}\n")

    # Phase 1 : classification LLM → découverte
    events_data = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
    classified_event = classify_event(chat_client, question, events_data, model)
    if classified_event:
        print(f"[Classification LLM : « {classified_event['event']} »]\n")
    else:
        print("[Classification LLM : thématique]\n")
    plan = discover(embed_client, question, conn, emb_matrix, chunk_ids, m_conn, m_matrix, m_ids,
                    forced_event=classified_event)

    amorce_event = None  # événement détecté depuis la lettre amorce (cas no-source)

    if plan.event:
        print(f"[Événement : {plan.event['event']} | {len(plan.letters)} lettres sélectionnées | {len(plan.segments)} tours prévus]\n")
    elif plan.has_source:
        dates = [l.get("date_iso", "") for l in plan.letters if l.get("date_iso")]
        span = f"{dates[0][:7]} → {dates[-1][:7]}" if len(dates) >= 2 else (dates[0][:7] if dates else "?")
        print(f"[Mode thématique — {len(plan.letters)} lettres ({span}) | {len(plan.segments)} tours]\n")
    else:
        print("[Aucune lettre source — réponse depuis les souvenirs + lettre amorce]\n")
        rand = get_random_letter(conn)
        if rand:
            plan.letters  = [rand]
            plan.segments = [[rand]]
            print(f"[Lettre amorce : {rand.get('date_iso', '?')}]\n")
            # Détecter l'événement auquel appartient la lettre amorce
            # pour pouvoir charger ses vraies lettres si l'utilisateur continue
            amorce_date = rand.get("date_iso", "")
            _events_data = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
            for evt in sorted(_events_data, key=lambda e: e["start"]):
                if amorce_date and evt["start"][:7] <= amorce_date[:7] <= evt["end"][:7]:
                    amorce_event = evt
                    break
            if amorce_event:
                print(f"[Événement amorce : {amorce_event['event']}]\n")

    # Phase 2 : état BD
    sconn   = open_state_db()
    conv_id = create_conversation(sconn, question, plan.event["event"] if plan.event else None)
    if plan.letters:
        insert_conversation_letters(sconn, conv_id, plan.letters)
    print(f"[Conversation ID : {conv_id}]\n")

    # Phase 3 : récit multi-tour
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    first_prompt = build_first_prompt(plan, question)
    messages.append({"role": "user", "content": first_prompt})

    # IDs des lettres servies au tour courant (commence par le premier segment)
    current_ids = [l["id"] for l in plan.segments[0]] if plan.segments and plan.segments[0] else []

    for turn in range(1, max_turns + 1):
        answer = execute_turn(chat_client, messages, model)
        print(f"--- NAPOLÉON [tour {turn}] ---")
        print(answer)
        print()

        messages.append({"role": "assistant", "content": answer})

        # ① Marquer les lettres de ce tour comme utilisées (avant de calculer le suivant)
        if current_ids:
            mark_letters_used(sconn, conv_id, current_ids, turn)

        # Demander à l'utilisateur s'il veut continuer
        if auto:
            user_input = "Continue."
            print(f"--- VOUS --- {user_input}\n")
        else:
            user_input = input("Vous : ").strip()
            print()

        if not is_continuation(user_input):
            print(f"(fin de la conversation — ID : {conv_id})")
            break

        # Re-découverte sur l'événement de la lettre amorce (cas no-source, tour 1)
        # L'utilisateur continue → charger les vraies lettres de cet événement
        if not plan.has_source and turn == 1 and amorce_event is not None:
            print(f"[Redécouverte sur « {amorce_event['event']} »...]\n")
            plan = discover(embed_client, amorce_event["event"],
                            conn, emb_matrix, chunk_ids,
                            m_conn, m_matrix, m_ids,
                            forced_event=amorce_event)
            if plan.letters:
                # Remplacer l'amorce dans l'état BD par les lettres du vrai événement
                sconn.execute(
                    "DELETE FROM conversation_letters WHERE conversation_id=?", (conv_id,)
                )
                sconn.commit()
                insert_conversation_letters(sconn, conv_id, plan.letters)
                print(f"[{len(plan.letters)} lettres chargées | {len(plan.segments)} tours]\n")
            current_ids = [l["id"] for l in plan.segments[0]] if plan.segments and plan.segments[0] else []
            transition_note = (
                f"Tu viens de proposer à ton interlocuteur d'aborder "
                f"« {amorce_event['event']} ». Il souhaite en entendre davantage. "
                f"Reprends le fil du récit et commence maintenant cet épisode "
                f"en t'appuyant sur tes lettres.\n\n"
            )
            next_prompt = transition_note + build_first_prompt(plan, amorce_event["event"])
            messages.append({"role": "user", "content": next_prompt})
            continue  # passer directement au tour suivant sans build_turn_prompt_from_state

        # ② Construire le prompt du tour suivant (pending déjà mis à jour)
        next_prompt, next_ids, exhausted = build_turn_prompt_from_state(sconn, conv_id, plan, turn + 1, conn)
        current_ids = next_ids  # ces lettres seront marquées utilisées au prochain tour

        messages.append({"role": "user", "content": next_prompt})

        # Si le plan est épuisé, on laisse un dernier tour de transition puis on s'arrête
        if exhausted:
            answer = execute_turn(chat_client, messages, model)
            print(f"--- NAPOLÉON [tour {turn + 1}] ---")
            print(answer)
            print()
            print(f"(fin du sujet — ID : {conv_id})")
            break

    sconn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", default=None)
    parser.add_argument("--model", default=None,
                        help="Modèle chat (défaut: LLM_MODEL dans .env, sinon gpt-4.1-mini)")
    parser.add_argument("--auto", action="store_true", help="Simule les tours automatiquement (test)")
    parser.add_argument("--max-turns", type=int, default=20, help="Nombre max de tours (défaut: 20)")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")

    from openai import OpenAI

    # Client pour les embeddings — toujours OpenAI (text-embedding-3-small)
    openai_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("OPEN_AI_KEY")
    if not openai_key:
        raise RuntimeError("Clé API OpenAI introuvable dans .env (LLM_API_KEY)")
    embed_client = OpenAI(api_key=openai_key)

    # Client pour le chat — local si LOCAL_LLM_URL défini, sinon même client OpenAI
    local_url   = os.getenv("LOCAL_LLM_URL")   # ex. http://localhost:11434/v1
    local_key   = os.getenv("LOCAL_LLM_KEY", "ollama")
    chat_model  = args.model or os.getenv("LOCAL_LLM_MODEL") or os.getenv("LLM_MODEL", "gpt-4.1-mini")

    if local_url:
        chat_client = OpenAI(api_key=local_key, base_url=local_url)
        print(f"Chat → modèle local : {local_url}  (modèle : {chat_model})")
    else:
        chat_client = embed_client
        print(f"Chat → OpenAI  (modèle : {chat_model})")

    print(f"Chargement RAG : {RAG_DB} ...")
    conn, emb_matrix, chunk_ids = load_db(RAG_DB)
    print(f"  {len(emb_matrix)} vecteurs lettres")

    if MEMOIR_DB.exists():
        m_conn, m_matrix, m_ids = load_db(MEMOIR_DB)
        print(f"  {len(m_matrix)} vecteurs mémoires")
    else:
        m_conn = m_matrix = m_ids = None
        print("  (mémoires absents)")

    question = args.question or input("\nQuestion : ").strip()
    run_story(embed_client, chat_client, question, conn, emb_matrix, chunk_ids,
              m_conn, m_matrix, m_ids, model=chat_model, auto=args.auto,
              max_turns=args.max_turns)


if __name__ == "__main__":
    main()
