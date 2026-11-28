"""Personnes, lieux et événements nommés dans un récit de Napoléon, pour que le visiteur sache de qui et d'où il
parle : chaque nom reçoit une courte notice, les lieux leurs coordonnées (carte murale), et des liens entre eux
(carte mentale de la mémoire du visiteur, gardée dans son navigateur).

Les entités déjà connues du visiteur (`connus`) ne sont pas renvoyées : seuls les liens nouveaux vers elles.
"""
import json
import re
import unicodedata

from llm_connector import parse_json_object

TYPES = ("personne", "lieu", "evenement", "institution")

PROMPT = """Tu aides le visiteur d'un musée à suivre un récit de Napoléon. On te donne le récit, son contexte \
(épisode, période) et la liste des noms que le visiteur connaît déjà. Relève les personnes, lieux, événements \
(batailles, traités, sièges…) et institutions (armées, assemblées…) nommés dans le récit.

Réponds UNIQUEMENT en JSON :
{"entites": [{"id": "identifiant tiré du NOM RÉEL, pas du titre ni du surnom : minuscules, sans accents, tirets (ex. massena pour « le duc de Rivoli », znaim, bataille-de-wagram)",
  "type": "personne" | "lieu" | "evenement" | "institution",
  "mention": "le nom EXACTEMENT comme il est écrit dans le récit, à sa première apparition",
  "nom": "nom complet (ex. « André Masséna, duc de Rivoli » pour « le duc de Rivoli »)",
  "notice": "une ou deux phrases pour situer : qui, quoi, son rôle à ce moment du récit",
  "latitude": 48.86, "longitude": 16.05}],   // lieux seulement, en degrés décimaux (exemple : Znaim)
 "liens": [{"de": "id", "vers": "id", "relation": "quelques mots (ex. « commande l'aile gauche à »)"}]}

Règles :
- Pas Napoléon lui-même, ni le visiteur. Pas de noms communs (« l'ennemi », « nos troupes »).
- Un nom déjà connu (liste fournie) : n'en fais PAS une entité ; utilise son identifiant dans les liens.
- Désigne la personne réelle derrière un titre (« le duc de Rivoli » en 1809 : Masséna ; « le prince Charles » : \
l'archiduc Charles d'Autriche). En cas de doute réel, dis-le dans la notice plutôt que d'inventer.
- Liens : seulement ceux que le récit établit (qui reçoit un ordre, où se passe un événement, qui y prend part).
- Notices et relations en {langue}."""


def _slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:60]


def _en_mot_entier(mention: str, texte: str) -> bool:
    """La mention figure-t-elle dans le texte en mot entier (« Rome » n'est pas dans « compromettre ») ?"""
    mots = [re.sub(r"['’]", "['’]", re.escape(m)) for m in mention.split()]
    if not mots:
        return False
    motif = r"\s+".join(mots)
    # ni lettre ni chiffre juste avant ou juste après (\w sans le « _ »)
    return re.search(rf"(?<![^\W_]){motif}(?![^\W_])", texte, re.IGNORECASE) is not None


def extraire(client, model: str, texte: str, connus: list[dict], contexte: str = "", langue: str = "français"):
    """{entites: [...], liens: [...]} : les noms nouveaux du récit, et les liens (vers des noms nouveaux ou connus)."""
    texte = (texte or "").strip()
    if not texte or client is None:
        return {"entites": [], "liens": []}
    connus = [c for c in connus or [] if isinstance(c, dict) and c.get("id")][:400]
    ids_connus = {c["id"] for c in connus}
    contenu = (f"Contexte : {contexte or '—'}\n\nNoms déjà connus du visiteur :\n"
               + ("\n".join(f"- {c['id']} : {c.get('nom', '')}" for c in connus) or "aucun")
               + f"\n\nRécit :\n{texte}")
    r = client.chat.completions.create(
        model=model, temperature=0, response_format={"type": "json_object"}, max_tokens=1800,
        messages=[{"role": "system", "content": PROMPT.replace("{langue}", langue or "français")},
                  {"role": "user", "content": contenu}])
    rep = parse_json_object(r.choices[0].message.content)

    # Contrôles : la mention doit figurer dans le récit, un nom connu n'est pas renvoyé, lieux bien situés
    entites, vus = [], set()
    for e in rep.get("entites") or []:
        if not isinstance(e, dict):
            continue
        eid = _slug(e.get("id") or e.get("nom") or "")
        mention = (e.get("mention") or "").strip()
        if not eid or eid in ids_connus or eid in vus or e.get("type") not in TYPES:
            continue
        if not mention or not _en_mot_entier(mention, texte):
            continue
        out = {"id": eid, "type": e["type"], "mention": mention, "nom": (e.get("nom") or mention).strip(),
               "notice": (e.get("notice") or "").strip()}
        if e["type"] == "lieu":
            try:
                lat = float(e.get("latitude", e.get("lat")))
                lon = float(e.get("longitude", e.get("lon")))
                if -180 <= lon <= 180 and -90 <= lat <= 90 and (lon, lat) != (0.0, 0.0):
                    out.update(lon=lon, lat=lat)
            except (TypeError, ValueError):
                pass
        entites.append(out)
        vus.add(eid)
    valides = vus | ids_connus
    liens = []
    for l in rep.get("liens") or []:
        if not isinstance(l, dict):
            continue
        de, vers = _slug(l.get("de", "")), _slug(l.get("vers", ""))
        if de in valides and vers in valides and de != vers:
            liens.append({"de": de, "vers": vers, "relation": (l.get("relation") or "").strip()[:80]})
    return {"entites": entites, "liens": liens}


if __name__ == "__main__":   # essai : python pipeline/napoleon_entites.py « texte »
    import os
    import sys
    from pathlib import Path

    from dotenv import load_dotenv
    from openai import OpenAI
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    c = OpenAI(api_key=os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY"))
    print(json.dumps(extraire(c, "gpt-4.1-mini", sys.argv[1], [], "campagne d'Autriche, septembre 1809"),
                     ensure_ascii=False, indent=1))
