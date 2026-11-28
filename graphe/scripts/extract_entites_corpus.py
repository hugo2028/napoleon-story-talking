"""[REMPLACÉ par la méthode du protocole v1.0 (graphe/PROTOCOLE.md, § 5.2 à 5.5) : conservé pour les essais
déjà faits ; ne pas lancer sur le corpus.]

Relève les personnes, lieux, événements et institutions de chaque document de la Correspondance (lettre,
ordre, bulletin, mémoire…), pour le graphe de connaissances (docs/MEMOIRE.md) : une lettre découpée en plusieurs
passages est lue en entier. Les Œuvres ont déjà leurs personnes et lieux (scripts/enrich_oeuvres.py).

Sortie : napoleon-corpus/metadata/entites_lettres.jsonl, une ligne par document (entités et liens) :
  {"doc": id du premier passage, "entites": [{"nom", "type", "formes": [...]}, ...]}
« nom » : le nom complet de la personne réelle (« André Masséna » pour « le duc de Rivoli ») ; « formes » : comme
elles sont écrites dans le texte. La fusion des doublons et le rattachement à Wikidata viennent ensuite
(graphe/scripts/build_graphe.py).

    python graphe/scripts/extract_entites_corpus.py --essai 20      # appels directs, pour juger
    python graphe/scripts/extract_entites_corpus.py --batch         # tout, par l'API Batch (moitié prix)
"""
import argparse
import io
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[2]
GRAPHE_DIR = ROOT / "graphe"
sys.path.insert(0, str(ROOT / "pipeline"))
from napoleon_archivist import build_letter_index  # noqa: E402

load_dotenv(ROOT / ".env")
DB = ROOT / "data" / "rag" / "napoleon_clean.sqlite"
META = ROOT / "napoleon-corpus" / "metadata"
OUT = GRAPHE_DIR / "donnees" / "entites_lettres.jsonl"
ETAT = GRAPHE_DIR / "donnees" / "entites_lettres_batch.json"
MODELE = "gpt-4.1-mini"
MAX_CARS = 7000
PLAFOND_DOLLARS = 12.0    # garde-fou : le lot n'est pas envoyé si l'estimation dépasse ce montant

PROMPT = """Tu es archiviste, spécialiste de Napoléon. On te donne un document de sa correspondance (lettre, \
ordre, bulletin…), sa date et son titre. Relève les personnes, lieux, événements (batailles, sièges, traités, \
cérémonies) et institutions (armées, corps d'armée, assemblées, ministères) qui y sont nommés.

Réponds UNIQUEMENT en JSON : {"entites": [{"nom": "...", "type": "personne"|"lieu"|"evenement"|"institution", \
"formes": ["...", ...]}], "liens": [{"de": "nom", "vers": "nom", "relation": "...", "nature": "..."}]}
- liens : les relations que le document ÉTABLIT entre ces entités (ou avec Napoléon, nom « Napoléon »), pas celles \
que tu connais par ailleurs : qui reçoit un ordre, qui commande quoi, qui se trouve où, qui participe à quel \
événement, liens de famille ou de service. « relation » : 2 à 6 mots, au présent (« reçoit l'ordre de marcher \
sur », « commande l'avant-garde de », « est frère de »). « nature » : commandement | ordre | famille | lieu | \
participation | diplomatie | administration | opinion | autre. Au plus 12 liens, les plus importants.
- nom : le nom complet et usuel de l'entité réelle, en français, SANS grade ni titre : « André Masséna » pour \
« le duc de Rivoli », « le prince d'Essling » ou « le maréchal Masséna » ; « Jean-de-Dieu Soult » pour « le duc de \
Dalmatie » ; « Louis Bonaparte » pour « le roi de Hollande » (1806-1810) ; « Joseph Bonaparte » pour « le roi \
d'Espagne » (1808-1813) ou « mon frère » s'il s'agit de lui. Sers-toi de la date pour savoir qui porte un titre à \
ce moment. Corrige les fautes d'OCR évidentes (« Dalmalie » → Dalmatie). Événements : « Bataille d'Austerlitz », \
« Traité de Tilsit ».
- formes : les façons EXACTES dont le document la nomme (1 à 4).
- Pas Napoléon lui-même, ni les noms communs (« l'ennemi », « mes troupes »), ni les destinataires anonymes.
- Un titre que tu ne sais pas rattacher à une personne avec certitude : garde le titre comme nom."""


def documents(conn):
    _, passages = build_letter_index(conn)
    for doc, ids in passages.items():
        rows = [conn.execute("SELECT title, text, date_iso, source_kind FROM chunks WHERE id=?", (i,)).fetchone()
                for i in ids]
        if any((r[3] or "").startswith("apocryphe") for r in rows):
            continue
        texte = "\n".join(r[1] or "" for r in rows)[:MAX_CARS]
        yield {"doc": doc, "titre": (rows[0][0] or "").strip(), "date": rows[0][2] or "", "texte": texte}


def messages(d):
    return [{"role": "system", "content": PROMPT},
            {"role": "user", "content": f"Titre : {d['titre']}\nDate : {d['date'] or 'inconnue'}\n\n{d['texte']}"}]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--essai", type=int, default=0)
    ap.add_argument("--batch", action="store_true")
    args = ap.parse_args()
    client = OpenAI(api_key=os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("OPEN_AI_KEY"))
    faits = set()
    if OUT.exists():
        faits = {json.loads(l)["doc"] for l in OUT.read_text(encoding="utf-8").splitlines() if l.strip()}
    docs = [d for d in documents(sqlite3.connect(DB)) if d["doc"] not in faits]
    cars = sum(len(d["texte"]) for d in docs) + len(docs) * len(PROMPT)
    estimation = cars / 3.6 / 1e6 * 0.20 + len(docs) * 520 / 1e6 * 0.80      # Batch : 0,20 $ / 0,80 $ par million
    print(f"{len(docs)} documents à traiter ({len(faits)} déjà faits) ; environ {cars / 3.6 / 1e6:.1f} M tokens "
          f"en entrée, coût estimé par l'API Batch : {estimation:.2f} $")

    if args.essai:
        with OUT.open("a", encoding="utf-8") as f:
            for d in docs[:: max(1, len(docs) // args.essai)][: args.essai]:
                r = client.chat.completions.create(model=MODELE, temperature=0, messages=messages(d),
                                                   response_format={"type": "json_object"})
                rep = json.loads(r.choices[0].message.content)
                f.write(json.dumps({"doc": d["doc"], **rep}, ensure_ascii=False) + "\n")
                print(d["titre"][:50], "→", [e["nom"] for e in rep.get("entites", [])][:8])
        return
    if not args.batch:
        return
    if estimation > PLAFOND_DOLLARS:
        raise SystemExit(f"Estimation {estimation:.2f} $ au-dessus du plafond ({PLAFOND_DOLLARS} $) : lot non envoyé.")

    etat = json.loads(ETAT.read_text(encoding="utf-8")) if ETAT.exists() else {}
    if not etat.get("batch"):
        corps = "".join(json.dumps({"custom_id": str(d["doc"]), "method": "POST", "url": "/v1/chat/completions",
                                    "body": {"model": MODELE, "temperature": 0,
                                             "response_format": {"type": "json_object"},
                                             "messages": messages(d)}}, ensure_ascii=False) + "\n" for d in docs)
        fichier = client.files.create(file=("entites.jsonl", io.BytesIO(corps.encode("utf-8"))), purpose="batch")
        b = client.batches.create(input_file_id=fichier.id, endpoint="/v1/chat/completions", completion_window="24h",
                                  metadata={"projet": "entites-lettres"})
        etat = {"batch": b.id, "n": len(docs)}
        ETAT.write_text(json.dumps(etat), encoding="utf-8")
        print(f"Lot {b.id} envoyé : {len(docs)} documents", flush=True)
    while True:
        b = client.batches.retrieve(etat["batch"])
        if b.status in ("validating", "in_progress", "finalizing"):
            rc = b.request_counts
            print(f"  {time.strftime('%H:%M')} {b.status} {rc.completed if rc else 0}/{rc.total if rc else '?'}",
                  flush=True)
            time.sleep(60)
            continue
        break
    if b.status == "failed":
        ETAT.unlink()
        raise SystemExit(f"Lot refusé : {[e.code for e in (b.errors.data if b.errors else [])]}")
    n, tin, tout = 0, 0, 0
    if b.output_file_id:
        with OUT.open("a", encoding="utf-8") as f:
            for l in client.files.content(b.output_file_id).text.splitlines():
                r = json.loads(l)
                body = (r.get("response") or {}).get("body") or {}
                if (r.get("response") or {}).get("status_code") != 200 or not body.get("choices"):
                    continue
                try:
                    rep = json.loads(body["choices"][0]["message"]["content"])
                except (json.JSONDecodeError, KeyError):
                    continue
                tin += body["usage"]["prompt_tokens"]
                tout += body["usage"]["completion_tokens"]
                f.write(json.dumps({"doc": int(r["custom_id"]), **rep}, ensure_ascii=False) + "\n")
                n += 1
    ETAT.unlink()
    print(f"Lot {b.id} : {b.status}, {n} documents ; {tin:,} tokens en entrée, {tout:,} en sortie, "
          f"soit {(tin * 0.20 + tout * 0.80) / 1e6:.2f} $")


if __name__ == "__main__":
    main()
