"""Niveau B du protocole (graphe/PROTOCOLE.md, § 5.2 à 5.4) : le lecteur outillé.

Un modèle lit UN document de la correspondance et interroge la base avant de rattacher chaque mention : registre
Wikidata (titres et fonctions datés), graphe du corpus, lectures déjà faites. Il termine par enregistrer_lecture,
qui vérifie chaque citation dans le texte (même tolérance que les citations du narrateur) et chaque identifiant, et
refuse la lecture avec la raison tant qu'elle n'est pas conforme. Aucun lien n'est pris des connaissances du
modèle : un lien sans citation retrouvée est rejeté.

    python graphe/scripts/lecteur.py --docs 123,456       # documents précis (identifiant du premier passage)
    python graphe/scripts/lecteur.py --essai-difficiles 6 # tirage de documents à formes ambiguës (titres, rois)
Sortie : graphe/donnees/lectures_essai.jsonl ; manifeste dans graphe/runs/.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[2]
GRAPHE_DIR = ROOT / "graphe"
sys.path.insert(0, str(ROOT / "pipeline"))
from napoleon_archivist import _retrouver_citation, build_letter_index  # noqa: E402

load_dotenv(ROOT / ".env")
LETTRES = ROOT / "data" / "rag" / "napoleon_clean.sqlite"
GRAPHE = ROOT / "data" / "rag" / "napoleon_graphe.sqlite"
REGISTRE = GRAPHE_DIR / "donnees" / "registre.json"
SORTIE = GRAPHE_DIR / "donnees" / "lectures_essai.jsonl"
CONSIGNE = GRAPHE_DIR / "prompts" / "lecteur_outille_v1.txt"
MODELE = "gpt-4.1-mini"
MAX_ETAPES = 12
PRIX = {"gpt-4.1-mini": (0.40, 1.60), "gpt-4.1": (2.00, 8.00)}


def plier(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower().replace("’", "'"))
    return "".join(c for c in s if not unicodedata.combining(c)).strip()


def en_mot(forme: str, texte_plie: str) -> bool:
    f = re.escape(plier(forme)).replace(r"\ ", r"\s+")
    return bool(f) and re.search(rf"(?<![^\W_]){f}(?![^\W_])", texte_plie) is not None


def dans_periode(date: str, debut: str | None, fin: str | None) -> bool:
    """La date (YYYY-MM-DD) tombe-t-elle entre début et fin (YYYY, YYYY-MM ou YYYY-MM-DD, bornes comprises) ?
    Sans date de document, tout titre est possible."""
    d = (date or "")[:10]
    if not d:
        return True
    return (not debut or d >= debut) and (not fin or d[:len(fin)] <= fin)


class Base:
    """Ce que le lecteur peut consulter : registre, graphe du corpus, lettres, lectures déjà faites."""

    def __init__(self):
        self.reg = json.loads(REGISTRE.read_text(encoding="utf-8"))
        self.ent = {k: v for k, v in self.reg["entites"].items() if v.get("qid")}
        self.lib = self.reg.get("libelles_titres", {})
        self.lc = sqlite3.connect(LETTRES)
        self.g = sqlite3.connect(GRAPHE)
        _, self.passages = build_letter_index(self.lc)
        self.lectures = []
        if SORTIE.exists():
            self.lectures = [json.loads(l) for l in SORTIE.read_text(encoding="utf-8").splitlines() if l.strip()]
        # Formes de chaque entité : nom, alias, formes vues dans le corpus (graphe provisoire)
        self.formes = defaultdict(set)
        for k, v in self.ent.items():
            for f in [v.get("nom") or "", *(v.get("alias") or []), v.get("forme") or ""]:
                if len(f) >= 3:
                    self.formes[k].add(f)
        for e, f in self.g.execute("SELECT entite, forme FROM formes"):
            if e in self.ent and len(f) >= 3:
                self.formes[e].add(f)

    def document(self, doc):
        ids = self.passages.get(doc, [doc])
        rows = [self.lc.execute("SELECT title, text, date_iso FROM chunks WHERE id=?", (i,)).fetchone() for i in ids]
        return {"doc": doc, "titre": (rows[0][0] or "").strip(), "date": rows[0][2] or "",
                "texte": "\n".join(r[1] or "" for r in rows)}

    def titulaires(self, date):
        """(libellé de titre ou de fonction, entité, début, fin) valides à la date."""
        for k, v in self.ent.items():
            for t in (v.get("titres") or []) + (v.get("fonctions") or []):
                if dans_periode(date, t.get("debut"), t.get("fin")):
                    for l in self.lib.get(t["qid"], []):
                        yield l, k, t.get("debut"), t.get("fin")

    # § 5.2 : candidats par script
    def candidats(self, texte, date):
        tp = plier(texte)
        out = []
        for k, fs in self.formes.items():
            vues = sorted({f for f in fs if en_mot(f, tp)}, key=len, reverse=True)
            if vues:
                out.append({"id": k, "nom": self.ent[k].get("nom"), "formes_vues": vues[:3]})
        for l, k, d, f in self.titulaires(date):
            if len(l) >= 6 and en_mot(l, tp):
                out.append({"id": k, "nom": self.ent[k].get("nom"), "titre_vu": l, "depuis": d, "jusqu_a": f})
        return out

    # ── Outils ──
    def chercher_entite(self, forme, date=""):
        tp = plier(forme)
        res = []
        for k, fs in self.formes.items():
            if any(plier(f) == tp or (len(tp) >= 4 and tp in plier(f)) for f in fs):
                e = self.ent[k]
                res.append({"id": k, "nom": e.get("nom"), "notice": e.get("notice"), "naissance": e.get("naissance"),
                            "mort": e.get("mort")})
        for l, k, d, f in self.titulaires(date):
            if plier(l) == tp or tp in plier(l):
                res.append({"id": k, "nom": self.ent[k].get("nom"), "porte": l, "depuis": d, "jusqu_a": f})
        return {"resultats": res[:12]} if res else {"resultats": [], "note": "absente du registre : peut être NIL"}

    def qui_porte(self, titre, date):
        tp = plier(titre)
        res = [{"id": k, "nom": self.ent[k].get("nom"), "titre": l, "depuis": d, "jusqu_a": f}
               for l, k, d, f in self.titulaires(date) if tp in plier(l) or plier(l) in tp]
        return {"titulaires": res[:8]} if res else {"titulaires": [], "note": "aucun titulaire connu du registre"}

    def fiche_entite(self, id):
        e = self.ent.get(id)
        if not e:
            return {"_erreur": f"identifiant inconnu du registre : {id}"}
        nommer = lambda ts: [{"titre": (self.lib.get(t["qid"]) or [t["qid"]])[0], "depuis": t.get("debut"),
                              "jusqu_a": t.get("fin")} for t in ts]
        voisins = [r[0] for r in self.g.execute("SELECT CASE WHEN a=? THEN b ELSE a END FROM liens WHERE a=? OR b=? "
                                                "ORDER BY poids DESC LIMIT 8", (id, id, id))]
        return {"id": id, "nom": e.get("nom"), "notice": e.get("notice"), "naissance": e.get("naissance"),
                "mort": e.get("mort"), "autres_noms": (e.get("alias") or [])[:12], "titres": nommer(e.get("titres") or []),
                "fonctions": nommer(e.get("fonctions") or [])[:10], "souvent_cite_avec": voisins}

    def lectures_precedentes(self, forme, destinataire=""):
        tp = plier(forme)
        out = []
        for l in self.lectures:
            for m in l.get("mentions", []):
                if plier(m.get("forme", "")) == tp:
                    out.append({"document": l["titre"][:60], "date": l["date"], "entite": m.get("entite")})
        if destinataire:
            dp = plier(destinataire)
            out = [o for o in out if dp in plier(o["document"])] or out
        return {"rattachements": out[-8:]} if out else {"rattachements": [], "note": "forme jamais rattachée"}

    def lettres_voisines(self, doc):
        rows = self.lc.execute("SELECT id, title, date_iso, substr(text, 1, 220) FROM chunks WHERE id BETWEEN ? AND ? "
                               "AND id != ? ORDER BY id", (doc - 4, doc + 4, doc)).fetchall()
        return {"voisines": [{"id": r[0], "titre": (r[1] or "")[:70], "date": r[2], "debut": (r[3] or "").replace("\n", " ")}
                             for r in rows]}


OUTILS = [
    {"type": "function", "function": {"name": "chercher_entite", "description":
        "Entités du registre qui portent cette forme (nom, alias, ou titre/fonction valide à la date).",
        "parameters": {"type": "object", "properties": {"forme": {"type": "string"}, "date": {"type": "string",
                       "description": "YYYY-MM-DD du document"}}, "required": ["forme"]}}},
    {"type": "function", "function": {"name": "qui_porte", "description":
        "Titulaire(s) d'un titre ou d'une fonction (« roi de Naples », « ministre de la Guerre ») à une date.",
        "parameters": {"type": "object", "properties": {"titre": {"type": "string"}, "date": {"type": "string"}},
                       "required": ["titre", "date"]}}},
    {"type": "function", "function": {"name": "fiche_entite", "description":
        "Fiche d'une entité du registre : autres noms, titres et fonctions datés, entités souvent citées avec elle.",
        "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}}},
    {"type": "function", "function": {"name": "lectures_precedentes", "description":
        "Comment cette forme a été rattachée dans les documents déjà lus (éventuellement au même destinataire).",
        "parameters": {"type": "object", "properties": {"forme": {"type": "string"}, "destinataire": {"type": "string"}},
                       "required": ["forme"]}}},
    {"type": "function", "function": {"name": "lettres_voisines", "description":
        "Documents voisins dans le volume (titre, date, début) : contexte pour un « mon frère », « le roi »…",
        "parameters": {"type": "object", "properties": {"doc": {"type": "integer"}}, "required": ["doc"]}}},
    {"type": "function", "function": {"name": "enregistrer_lecture", "description":
        "Action finale : les mentions rattachées et les liens établis par le document, chacun avec sa citation EXACTE. "
        "Refusée avec la raison si une citation est introuvable dans le texte ou un identifiant inconnu.",
        "parameters": {"type": "object", "properties": {
            "mentions": {"type": "array", "items": {"type": "object", "properties": {
                "forme": {"type": "string", "description": "telle qu'écrite dans le document"},
                "entite": {"type": "string", "description": "identifiant du registre, ou NIL"},
                "type": {"type": "string", "enum": ["personne", "lieu", "evenement", "institution"]},
                "nom_nil": {"type": "string", "description": "pour une NIL : nom complet le plus précis possible"},
                "certitude": {"type": "string", "enum": ["sure", "probable", "incertaine"]},
                "indice": {"type": "string", "description": "ce qui fonde le rattachement (outil, date, contexte)"}},
                "required": ["forme", "entite", "type", "certitude"]}},
            "liens": {"type": "array", "items": {"type": "object", "properties": {
                "de": {"type": "string", "description": "forme de la mention (ou Napoléon)"},
                "vers": {"type": "string"},
                "relation": {"type": "string", "description": "2 à 6 mots, au présent"},
                "nature": {"type": "string", "enum": ["commandement", "ordre", "famille", "lieu", "participation",
                                                      "diplomatie", "administration", "opinion", "autre"]},
                "citation": {"type": "string", "description": "phrase EXACTE du document qui établit le lien"}},
                "required": ["de", "vers", "relation", "nature", "citation"]}}},
            "required": ["mentions", "liens"]}}},
]


def verifier(base, docu, args):
    """§ 5.4 : identifiants connus, citations retrouvées dans le texte, entités présentes dans la citation."""
    erreurs, liens_ok, rejets = [], [], []
    formes = {}
    for m in args.get("mentions") or []:
        e = m.get("entite") or ""
        if e != "NIL" and e not in base.ent:
            erreurs.append(f"mention « {m.get('forme')} » : identifiant inconnu {e} (chercher_entite, ou NIL)")
        formes[m.get("forme", "")] = e
    for l in args.get("liens") or []:
        trouve = _retrouver_citation(l.get("citation") or "", docu["texte"])
        if not trouve:
            rejets.append({**l, "raison": "citation introuvable dans le texte"})
            continue
        presents = [x for x in (l.get("de"), l.get("vers")) if x and x != "Napoléon"]
        faible = not all(en_mot(x, plier(trouve)) or en_mot(x.split()[-1], plier(trouve)) for x in presents)
        liens_ok.append({**l, "citation": trouve, **({"faible": True} if faible else {})})
    if rejets and len(rejets) > len(liens_ok):
        erreurs.append(f"{len(rejets)} citation(s) introuvable(s) dans le texte : recopie la phrase exacte du "
                       f"document, ou retire le lien : {[r['citation'][:60] for r in rejets[:4]]}")
    return erreurs, liens_ok, rejets


def lire(client, base, doc, consigne, modele):
    d = base.document(doc)
    cands = base.candidats(d["texte"], d["date"])
    messages = [{"role": "system", "content": consigne},
                {"role": "user", "content": f"Document {doc} — {d['titre']}\nDate : {d['date']}\n\n"
                 f"Candidats trouvés par script (formes du registre présentes dans le texte) :\n"
                 f"{json.dumps(cands, ensure_ascii=False)}\n\nTexte :\n{d['texte'][:9000]}"}]
    appels, tin, tout, essais_enr = [], 0, 0, 0
    for _ in range(MAX_ETAPES):
        r = client.chat.completions.create(model=modele, temperature=0, messages=messages, tools=OUTILS,
                                           tool_choice="required")
        tin += r.usage.prompt_tokens
        tout += r.usage.completion_tokens
        msg = r.choices[0].message
        messages.append({"role": "assistant", "content": msg.content, "tool_calls": [
            {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}
            for c in msg.tool_calls]})
        fini = None
        for c in msg.tool_calls:
            try:
                a = json.loads(c.function.arguments or "{}")
            except json.JSONDecodeError:
                a = {}
            appels.append({"outil": c.function.name, "args": {k: v for k, v in a.items() if k not in ("mentions", "liens")}})
            if c.function.name == "enregistrer_lecture":
                essais_enr += 1
                erreurs, liens_ok, rejets = verifier(base, d, a)
                if erreurs and essais_enr < 3:
                    res = {"_erreur": erreurs}
                else:
                    fini = {"mentions": a.get("mentions") or [], "liens": liens_ok, "liens_rejetes": rejets,
                            "erreurs_restantes": erreurs}
                    res = {"ok": True}
            else:
                fn = getattr(base, c.function.name, None)
                try:
                    res = fn(**a) if fn else {"_erreur": "outil inconnu"}
                except TypeError as e:
                    res = {"_erreur": str(e)}
            messages.append({"role": "tool", "tool_call_id": c.id, "content": json.dumps(res, ensure_ascii=False)[:6000]})
        if fini:
            pin, pout = PRIX.get(modele, (0, 0))
            return {"doc": doc, "titre": d["titre"], "date": d["date"], "niveau": "B", "modele": modele,
                    "candidats": len(cands), "appels": appels, **fini, "tokens": [tin, tout],
                    "cout": round((tin * pin + tout * pout) / 1e6, 5)}
    return {"doc": doc, "titre": d["titre"], "date": d["date"], "niveau": "B", "echec": "pas de lecture enregistrée",
            "appels": appels, "tokens": [tin, tout]}


def difficiles(base, n):
    """Documents à formes ambiguës, sur des périodes différentes : rois, ducs, princes, « mon frère »."""
    motifs = [("roi de Naples", "1806", "1807"), ("roi de Naples", "1810", "1812"), ("duc de Rivoli", "1808", "1810"),
              ("prince de Neuchâtel", "1806", "1812"), ("mon frère", "1806", "1808"), ("duc de Dalmatie", "1808", "1813"),
              ("prince d'Essling", "1810", "1811"), ("roi de Hollande", "1806", "1810")]
    out = []
    for motif, a, b in motifs[:n]:
        r = base.lc.execute("SELECT id FROM chunks WHERE date_iso BETWEEN ? AND ? AND lower(text) LIKE ? "
                            "AND source_kind = 'napoleon_letter' ORDER BY id LIMIT 1 OFFSET 3",
                            (a, b + "-12-31", f"%{motif.lower()}%")).fetchone()
        if r:
            doc = next((d for d, ids in base.passages.items() if r[0] in ids), r[0])
            out.append(doc)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs")
    ap.add_argument("--essai-difficiles", type=int, default=0)
    ap.add_argument("--model", default=MODELE)
    args = ap.parse_args()
    base = Base()
    docs = [int(x) for x in args.docs.split(",")] if args.docs else difficiles(base, args.essai_difficiles)
    consigne = CONSIGNE.read_text(encoding="utf-8")
    client = OpenAI(api_key=os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("OPEN_AI_KEY"))
    debut, cout, n = time.time(), 0.0, 0
    with SORTIE.open("a", encoding="utf-8") as f:
        for doc in docs:
            l = lire(client, base, doc, consigne, args.model)
            base.lectures.append(l)
            f.write(json.dumps(l, ensure_ascii=False) + "\n")
            f.flush()
            cout += l.get("cout", 0)
            n += 1
            print(f"{doc} {l['date']} {l['titre'][:45]} : {len(l.get('mentions', []))} mentions, "
                  f"{len(l.get('liens', []))} liens ({len(l.get('liens_rejetes', []))} rejetés), "
                  f"{len(l['appels'])} appels, {l.get('cout', 0):.4f} $", flush=True)
    manifeste = {"etape": "3-essai-lecteur-B", "protocole": "1.1", "date": dt.datetime.now().isoformat(timespec="seconds"),
                 "modele": args.model, "consigne_sha256": hashlib.sha256(consigne.encode("utf-8")).hexdigest(),
                 "registre_sha256": hashlib.sha256(REGISTRE.read_bytes()).hexdigest(), "documents": docs,
                 "lus": n, "cout": round(cout, 4), "duree_s": round(time.time() - debut)}
    (GRAPHE_DIR / "runs" / f"{dt.datetime.now():%Y-%m-%d_%H%M}_3-essai-lecteur-B.json").write_text(
        json.dumps(manifeste, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Coût total : {cout:.4f} $")


if __name__ == "__main__":
    main()
