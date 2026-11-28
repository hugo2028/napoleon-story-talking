"""[REMPLACÉ par la méthode du protocole v1.0 (graphe/PROTOCOLE.md, § 5.2 à 5.5) : conservé pour les essais
déjà faits ; ne pas lancer sur le corpus.]

Deuxième passe du graphe de connaissances (docs/MEMOIRE.md) : qui est qui, vu sur l'ensemble du corpus.

La première passe (scripts/extract_entites_corpus.py) lit chaque lettre seule. Ici, un modèle à grand contexte
(gpt-4.1) reçoit TOUTES les formes relevées (lettres et Œuvres), regroupées par période : pour chacune, ses années
d'emploi, le nombre de documents, les identités proposées en première passe et des titres de lettres où elle
apparaît. Il tranche l'identité réelle, par forme ET par période (« le roi de Naples » : Joseph Bonaparte en 1806,
Joachim Murat en 1810).

Sortie : napoleon-corpus/metadata/entites_resolution.json
  {"par_periode": {"<clé de forme>|<période>": "<nom canonique>"}, "formes": {"<clé>": "<nom canonique>"}}
appliqué par scripts/build_graphe.py ; « napoleon » pour Napoléon lui-même, « ? » si incertain (forme gardée telle
quelle).

    python graphe/scripts/resolve_entites.py --essai 1      # un groupe en appel direct, pour juger
    python graphe/scripts/resolve_entites.py --batch        # tout, par l'API Batch
"""
import argparse
import io
import json
import os
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[2]
GRAPHE_DIR = ROOT / "graphe"
sys.path.insert(0, str(GRAPHE_DIR / "scripts"))
from build_graphe import cle  # noqa: E402

load_dotenv(ROOT / ".env")
META = ROOT / "napoleon-corpus" / "metadata"
OUT = GRAPHE_DIR / "donnees" / "entites_resolution.json"
ETAT = GRAPHE_DIR / "donnees" / "entites_resolution_batch.json"
LETTRES = ROOT / "data" / "rag" / "napoleon_clean.sqlite"
MODELE = "gpt-4.1"
PAR_GROUPE = 350              # formes par requête
PLAFOND_DOLLARS = 6.0

PROMPT = """Tu es historien, spécialiste de l'entourage de Napoléon et de l'Europe de 1785 à 1821. On te donne les \
noms relevés dans sa correspondance et ses Œuvres pendant une période, tels qu'ils sont écrits (titres, grades, \
surnoms, fautes d'OCR), avec leurs années d'emploi, le nombre de documents, les identités proposées par une \
première lecture et des titres de documents où ils apparaissent.

Pour chaque forme, donne l'identité réelle À CETTE PÉRIODE : le nom canonique, complet et usuel en français, \
sans grade ni titre (« Joachim Murat », « Louis-Alexandre Berthier », « Royaume de Naples », « Bataille d'Eylau »). \
Les titres changent de titulaire : tiens compte des années (« roi de Naples » : Joseph Bonaparte 1806-1808, \
Joachim Murat 1808-1815). Napoléon lui-même (Bonaparte, Buonaparte, l'Empereur, le Premier consul, moi) : \
« napoleon ». Une forme trop vague ou que tu ne peux pas rattacher avec certitude : « ? ». Deux formes de la même \
entité doivent recevoir exactement le même nom canonique.

Réponds UNIQUEMENT en JSON : {"identites": {"<forme>": "<nom canonique, napoleon ou ?>", ...}}"""


def periode(annee: int) -> str:
    """Tranches de l'histoire de Napoléon : les titres et les commandements y sont stables."""
    for fin, nom in ((1795, "1785-1795"), (1797, "1796-1797"), (1799, "1798-1799"), (1804, "1800-1804"),
                     (1807, "1805-1807"), (1809, "1808-1809"), (1812, "1810-1812"), (1815, "1813-1815")):
        if annee <= fin:
            return nom
    return "1816-1821"


def collecter():
    """forme → période → {n, annees, proposes, titres, type}"""
    lc = sqlite3.connect(LETTRES)
    meta = {r[0]: (r[1] or "", (r[2] or "").strip()) for r in lc.execute("SELECT id, date_iso, title FROM chunks")}
    stats = defaultdict(lambda: {"n": 0, "annees": Counter(), "proposes": Counter(), "titres": [], "types": Counter(),
                                 "formes": Counter()})

    def noter(forme, typ, propose, date, titre):
        k = cle(forme)
        if len(k) < 2 or not date[:4].isdigit():
            return
        s = stats[(k, periode(int(date[:4])))]
        s["n"] += 1
        s["annees"][int(date[:4])] += 1
        s["formes"][forme.strip()] += 1
        s["types"][typ] += 1
        if propose and cle(propose) != k:
            s["proposes"][propose.strip()] += 1
        if titre and len(s["titres"]) < 3 and titre not in s["titres"]:
            s["titres"].append(titre[:70])

    p = GRAPHE_DIR / "donnees" / "entites_lettres.jsonl"
    for l in (p.read_text(encoding="utf-8").splitlines() if p.exists() else []):
        r = json.loads(l)
        date, titre = meta.get(r["doc"], ("", ""))
        for e in r.get("entites") or []:
            if not isinstance(e, dict) or not e.get("nom"):
                continue
            for f in set(e.get("formes") or []) | {e["nom"]}:
                noter(f, e.get("type", ""), e["nom"], date, titre)
    p = META / "oeuvres_enrichi.jsonl"
    gardes = json.loads((META / "oeuvres_passages.json").read_text(encoding="utf-8"))["passages"]
    for l in (p.read_text(encoding="utf-8").splitlines() if p.exists() else []):
        r = json.loads(l)
        g = gardes.get(str(r["id"]))
        if not g:
            continue
        for n in r.get("personnes") or []:
            noter(n, "personne", "", g["date"], r.get("resume", ""))
        for n in r.get("lieux") or []:
            noter(n, "lieu", "", g["date"], r.get("resume", ""))
    return stats


def groupes(stats):
    """Requêtes : par période, les formes de personnes et d'institutions (les lieux se résolvent rarement mal :
    seuls ceux qui ont une identité proposée différente sont soumis)."""
    par_per = defaultdict(list)
    for (k, per), s in stats.items():
        typ = s["types"].most_common(1)[0][0]
        if typ == "lieu" and not s["proposes"]:
            continue
        if s["n"] < 2 and not s["proposes"]:
            continue
        par_per[per].append((k, s))
    out = []
    for per, items in sorted(par_per.items()):
        items.sort(key=lambda x: -x[1]["n"])
        for i in range(0, len(items), PAR_GROUPE):
            lignes = []
            for k, s in items[i:i + PAR_GROUPE]:
                forme = s["formes"].most_common(1)[0][0]
                an = sorted(s["annees"])
                lignes.append(json.dumps({"forme": forme, "type": s["types"].most_common(1)[0][0],
                                          "annees": f"{an[0]}-{an[-1]}" if an[0] != an[-1] else str(an[0]),
                                          "documents": s["n"], "proposes": [p for p, _ in s["proposes"].most_common(3)],
                                          "exemples": s["titres"]}, ensure_ascii=False))
            out.append({"id": f"{per}#{i // PAR_GROUPE}", "periode": per,
                        "cles": {s["formes"].most_common(1)[0][0]: k for k, s in items[i:i + PAR_GROUPE]},
                        "contenu": f"Période : {per}\n\n" + "\n".join(lignes)})
    return out


def appliquer(reponses, gs):
    par_periode, global_ = {}, defaultdict(Counter)
    for g in gs:
        ident = (reponses.get(g["id"]) or {}).get("identites") or {}
        for forme, nom in ident.items():
            k = g["cles"].get(forme)
            if not k or not isinstance(nom, str) or nom.strip() in ("", "?"):
                continue
            canon = "napoleon" if nom.strip().lower() == "napoleon" else nom.strip()
            par_periode[f"{k}|{g['periode']}"] = canon
            global_[k][canon] += 1
    formes = {k: c.most_common(1)[0][0] for k, c in global_.items() if len(c) == 1}   # sans ambiguïté de période
    OUT.write_text(json.dumps({"_doc": "Produit par graphe/scripts/resolve_entites.py.", "par_periode": par_periode,
                               "formes": formes}, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"{len(par_periode)} formes résolues par période, {len(formes)} sans ambiguïté → {OUT.name}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--essai", type=int, default=0)
    ap.add_argument("--batch", action="store_true")
    args = ap.parse_args()
    client = OpenAI(api_key=os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("OPEN_AI_KEY"))
    gs = groupes(collecter())
    cars = sum(len(g["contenu"]) for g in gs) + len(gs) * len(PROMPT)
    sortie = sum(len(g["cles"]) for g in gs) * 18
    estimation = (cars / 3.6 * 1.0 + sortie * 4.0) / 1e6      # gpt-4.1 par l'API Batch : 1 $ / 4 $ par million
    print(f"{len(gs)} requêtes, {sum(len(g['cles']) for g in gs)} formes ; coût estimé (API Batch) : {estimation:.2f} $")
    if args.essai:
        rep = {}
        for g in gs[:args.essai]:
            r = client.chat.completions.create(model=MODELE, temperature=0, response_format={"type": "json_object"},
                                               messages=[{"role": "system", "content": PROMPT},
                                                         {"role": "user", "content": g["contenu"]}])
            rep[g["id"]] = json.loads(r.choices[0].message.content)
            print(g["id"], list(rep[g["id"]].get("identites", {}).items())[:25])
        return
    if not args.batch:
        return
    if estimation > PLAFOND_DOLLARS:
        raise SystemExit(f"Estimation {estimation:.2f} $ au-dessus du plafond ({PLAFOND_DOLLARS} $) : lot non envoyé.")
    etat = json.loads(ETAT.read_text(encoding="utf-8")) if ETAT.exists() else {}
    if not etat.get("batch"):
        corps = "".join(json.dumps({"custom_id": g["id"], "method": "POST", "url": "/v1/chat/completions",
                                    "body": {"model": MODELE, "temperature": 0,
                                             "response_format": {"type": "json_object"},
                                             "messages": [{"role": "system", "content": PROMPT},
                                                          {"role": "user", "content": g["contenu"]}]}},
                                   ensure_ascii=False) + "\n" for g in gs)
        f = client.files.create(file=("resolution.jsonl", io.BytesIO(corps.encode("utf-8"))), purpose="batch")
        b = client.batches.create(input_file_id=f.id, endpoint="/v1/chat/completions", completion_window="24h",
                                  metadata={"projet": "resolution-entites"})
        etat = {"batch": b.id}
        ETAT.write_text(json.dumps(etat), encoding="utf-8")
        print(f"Lot {b.id} envoyé : {len(gs)} requêtes", flush=True)
    while (b := client.batches.retrieve(etat["batch"])).status in ("validating", "in_progress", "finalizing"):
        print(f"  {time.strftime('%H:%M')} {b.status}", flush=True)
        time.sleep(60)
    reponses = {}
    if b.output_file_id:
        for l in client.files.content(b.output_file_id).text.splitlines():
            r = json.loads(l)
            body = (r.get("response") or {}).get("body") or {}
            try:
                reponses[r["custom_id"]] = json.loads(body["choices"][0]["message"]["content"])
            except (KeyError, IndexError, json.JSONDecodeError):
                pass
    ETAT.unlink()
    print(f"Lot {b.id} : {b.status}, {len(reponses)}/{len(gs)} réponses")
    appliquer(reponses, gs)


if __name__ == "__main__":
    main()
