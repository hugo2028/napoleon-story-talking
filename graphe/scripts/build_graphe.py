"""Construit la base du graphe de connaissances : data/rag/napoleon_graphe.sqlite (docs/MEMOIRE.md).

Nœuds :
  - entités : personnes, lieux, événements, institutions (relevées dans les lettres par
    graphe/scripts/extract_entites_corpus.py et dans les Œuvres par scripts/enrich_oeuvres.py) ;
  - documents : lettres, passages des Œuvres (ceux gardés pour la recherche), tableaux du catalogue, épisodes.
Liens : une entité citée dans un document, un document rattaché à son épisode, deux entités souvent citées ensemble.
Recherche : un index plein texte FTS5 (sans accents) sur les noms, leurs formes, les titres et les textes.

Fusion des doublons : napoleon-corpus/metadata/entites_resolution.json, s'il existe (« forme écrite » → identifiant
canonique, produit par graphe/scripts/resolve_entites.py), puis l'identifiant Wikidata (entites_wikidata.json).

    python graphe/scripts/build_graphe.py
"""
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GRAPHE_DIR = ROOT / "graphe"
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "scripts"))   # enrich_oeuvres (dates des Œuvres)
from napoleon_archivist import build_letter_index  # noqa: E402
from enrich_oeuvres import episode_de  # noqa: E402


def periode(annee: int) -> str:
    """Tranches de l'histoire de Napoléon (même découpage que scripts/resolve_entites.py)."""
    for fin, nom in ((1795, "1785-1795"), (1797, "1796-1797"), (1799, "1798-1799"), (1804, "1800-1804"),
                     (1807, "1805-1807"), (1809, "1808-1809"), (1812, "1810-1812"), (1815, "1813-1815")):
        if annee <= fin:
            return nom
    return "1816-1821"

META = ROOT / "napoleon-corpus" / "metadata"
LETTRES = ROOT / "data" / "rag" / "napoleon_clean.sqlite"
OEUVRES = ROOT / "data" / "rag" / "napoleon_memoirs.sqlite"
SORTIE = ROOT / "data" / "rag" / "napoleon_graphe.sqlite"
VIGNETTES = ROOT / "web" / "decor" / "memoire"     # images de Wikimedia Commons (scripts/wikidata_entites.py)


def vignette(fichier: str | None) -> str | None:
    """Chemin servi d'une vignette téléchargée, ou None si elle ne l'est pas (rien n'est appelé chez Wikimedia)."""
    if not fichier:
        return None
    nom = re.sub(r"[^\w.-]+", "_", fichier)[:120] + ".jpg"
    return f"/decor/memoire/{nom}" if (VIGNETTES / nom).exists() else None

# Grades et civilités retirés pour comparer les noms (« maréchal Soult » et « Soult » sont la même forme)
GRADES = re.compile(r"^(?:(?:le|la|les|l'|du|de|des|m\.|mme|monsieur|madame|citoyen|citoyenne|general|generale|"
                    r"marechal|amiral|colonel|capitaine|lieutenant|chef de bataillon|chef d'escadron|adjudant|"
                    r"commandant|contre-amiral|vice-amiral|chef de brigade|commissaire|ordonnateur|"
                    r"general de division|general de brigade|sa majeste|s\. m\.)\s+)+")
NAPOLEON = {"napoleon", "bonaparte", "napoleon-bonaparte", "napoleon-ier", "l-empereur", "empereur", "premier-consul"}


def plier(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower().replace("’", "'"))
    return "".join(c for c in s if not unicodedata.combining(c)).strip()


def cle(nom: str) -> str:
    """Identifiant d'une forme : sans accents, sans grade, en tirets."""
    s = GRADES.sub("", plier(nom))
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:70]


MOIS = {m: i for i, m in enumerate(("janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout",
                                     "septembre", "octobre", "novembre", "decembre"), 1)}


def date_peinte(sujet: str) -> str:
    """Date du moment peint, lue entre parenthèses dans la description (« (6 juillet 1809) », « (15-17 novembre
    1796) », « (mai 1809) ») : YYYY-MM-DD, YYYY-MM ou YYYY ; vide si aucune."""
    for m in re.finditer(r"\(([^()]*?\b(1[78]\d\d))\)", sujet):
        txt = plier(m.group(1))
        mm = re.search(r"(?:(\d{1,2})(?:er)?(?:\s*-\s*\d{1,2})?\s+)?(" + "|".join(MOIS) + r")\s+(1[78]\d\d)", txt)
        if mm:
            jour = f"-{int(mm.group(1)):02d}" if mm.group(1) else ""
            return f"{mm.group(3)}-{MOIS[mm.group(2)]:02d}{jour}"
        return m.group(2)
    return ""


def charger_donnee(nom, defaut):
    p = GRAPHE_DIR / "donnees" / nom
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else defaut


def charger_json(nom, defaut):
    p = META / nom
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else defaut


def main():
    res = charger_donnee("entites_resolution.json", {})
    par_periode = res.get("par_periode", {})        # « clé|période » → nom canonique (« roi de Naples|1808-1809 »)
    resolution = res.get("formes", {})              # clé → nom canonique, quand la forme ne change pas d'identité
    wd_tout = charger_donnee("entites_wikidata.json", {})
    wikidata = wd_tout.get("entites", {})            # id d'entité → {qid, nom, notice, portrait…}
    episodes = json.loads((META / "episodes.json").read_text(encoding="utf-8"))["episodes"]
    titres_ep = {e["id"]: e["titre"] for e in episodes}

    entites = {}                       # id → {type, nom, formes: Counter}
    mentions = defaultdict(set)        # id d'entité → documents
    docs = {}                          # id de document → {type, titre, date, episode, texte, resume, image}
    relations = []                     # (a, b, relation, nature, document) : liens lus dans les lettres

    def identite(nom, doc):
        """Identifiant et nom canonique d'une forme écrite dans un document, à la date du document ; None pour
        Napoléon lui-même et les formes vides."""
        k = cle(nom)
        if len(k) < 2 or k in NAPOLEON:
            return None, None
        date = docs.get(doc, {}).get("date") or ""
        canon = (par_periode.get(f"{k}|{periode(int(date[:4]))}") if date[:4].isdigit() else None) \
            or resolution.get(k)
        if canon == "napoleon":
            return None, None
        return (cle(canon), canon) if canon else (k, None)

    def entite(nom, typ, doc):
        k, canon = identite(nom, doc)
        if not k or k in NAPOLEON:
            return None
        e = entites.setdefault(k, {"type": typ, "noms": Counter(), "formes": Counter(), "types": Counter()})
        e["noms"][canon or nom.strip()] += 3 if canon else 1
        e["formes"][nom.strip()] += 1
        e["types"][typ] += 1
        mentions[k].add(doc)
        return k

    # Lettres (documents entiers)
    lc = sqlite3.connect(LETTRES)
    _, passages = build_letter_index(lc)
    for doc, ids in passages.items():
        rows = [lc.execute("SELECT title, text, date_iso, source_kind, date_reliable FROM chunks WHERE id=?",
                           (i,)).fetchone() for i in ids]
        if any((r[3] or "").startswith("apocryphe") for r in rows):
            continue
        date = rows[0][2] or ""
        docs[f"lettre:{doc}"] = {"type": "lettre", "titre": (rows[0][0] or "").strip(), "date": date,
                                 "episode": episode_de(date[:10]) if date[:4].isdigit() else None,
                                 "texte": "\n".join(r[1] or "" for r in rows), "resume": ""}
    p = GRAPHE_DIR / "donnees" / "entites_lettres.jsonl"
    if p.exists():
        for l in p.read_text(encoding="utf-8").splitlines():
            r = json.loads(l)
            d = f"lettre:{r['doc']}"
            if d not in docs:
                continue
            ids_doc = {}
            for e in r.get("entites") or []:
                if isinstance(e, dict) and e.get("nom") and e.get("type") in ("personne", "lieu", "evenement",
                                                                             "institution"):
                    k = entite(e["nom"], e["type"], d)
                    if not k:
                        continue
                    ids_doc[e["nom"]] = k
                    for f in e.get("formes") or []:
                        ids_doc[f] = k
                        if cle(f) and cle(f) != k:
                            entites[k]["formes"][f.strip()] += 1
            # Liens que la lettre établit (lus par le modèle), avec la lettre d'où ils viennent
            for l in r.get("liens") or []:
                if not isinstance(l, dict):
                    continue
                a = ids_doc.get(l.get("de")) or identite(l.get("de") or "", d)[0]
                b = ids_doc.get(l.get("vers")) or identite(l.get("vers") or "", d)[0]
                if a and b and a != b and a in entites and b in entites:
                    relations.append((a, b, (l.get("relation") or "")[:80], (l.get("nature") or "autre")[:20], d))

    # Passages des Œuvres gardés pour la recherche
    gardes = charger_json("oeuvres_passages.json", {}).get("passages", {})
    sections = {k: v for k, v in charger_json("oeuvres_sections.json", {}).items() if not k.startswith("_")}
    oc = sqlite3.connect(OEUVRES)
    enrichis = {}
    pe = META / "oeuvres_enrichi.jsonl"
    if pe.exists():
        enrichis = {json.loads(l)["id"]: json.loads(l) for l in pe.read_text(encoding="utf-8").splitlines() if l}
    for cid, title, text in oc.execute("SELECT id, title, text FROM chunks"):
        g = gardes.get(str(cid))
        if not g:
            continue
        sec = sections.get((title or "").strip(), {})
        d = f"oeuvre:{cid}"
        docs[d] = {"type": "oeuvre", "titre": sec.get("titre") or (title or "").strip(), "date": g.get("date", ""),
                   "episode": g.get("episode"), "texte": text or "", "resume": g.get("resume", ""),
                   "importance": g.get("importance", 2)}
        r = enrichis.get(cid, {})
        for n in r.get("personnes") or []:
            entite(n, "personne", d)
        for n in r.get("lieux") or []:
            entite(n, "lieu", d)

    # Épisodes : des nœuds à part entière, auxquels chaque document est rattaché
    for e in episodes:
        docs[f"episode:{e['id']}"] = {"type": "episode", "titre": e["titre"], "date": e["debut"], "episode": e["id"],
                                      "texte": "", "resume": f"{e['debut']} → {e['fin']}"}

    # Identité retenue pour chaque entité : nom le plus fréquent, type majoritaire
    for k, e in entites.items():
        e["nom"] = e["noms"].most_common(1)[0][0]
        e["type"] = e["types"].most_common(1)[0][0]
        wd = wikidata.get(k) or {}
        if wd.get("nom"):
            e["nom"] = wd["nom"]

    # Tableaux : rattachés aux entités nommées dans leur titre ou leur description, et à l'épisode du moment peint
    formes_index = []
    for k, e in entites.items():
        if len(mentions[k]) < 3:
            continue
        for f in set(e["formes"]) | {e["nom"]}:
            fp = plier(f)
            if len(fp) >= 4:
                formes_index.append((re.compile(rf"(?<![^\W_]){re.escape(fp)}(?![^\W_])"), k))
    for t in json.loads((META / "tableaux.json").read_text(encoding="utf-8")):
        d = f"tableau:{t['id']}"
        texte = f"{t['titre']}. {t.get('sujet', '')}"
        annee = date_peinte(t.get("sujet", ""))
        docs[d] = {"type": "tableau", "titre": t["titre"], "date": annee, "episode": episode_de(annee) if annee else None,
                   "texte": texte, "resume": f"{t.get('peintre', '')}, {t.get('date', '')}",
                   "image": f"/decor/tableaux/{t['id']}.jpg"}
        plie = plier(texte)
        for rx, k in formes_index:
            if rx.search(plie):
                mentions[k].add(d)

    for q, o in (wd_tout.get("oeuvres") or {}).items():
        img = vignette(o.get("image"))
        if not img:
            continue                                   # sans vignette téléchargée, pas de nœud image
        d = f"tableau:{q}"
        docs[d] = {"type": "tableau", "titre": o["titre"], "date": "", "episode": None,
                   "texte": f"{o['titre']}. {o.get('auteur', '')}", "resume": f"{o.get('auteur', '')}, {o.get('date', '')}",
                   "image": img}
        for e in o.get("sujets") or []:
            if e in entites:
                mentions[e].add(d)

    # Liens entre entités : citées ensemble dans au moins deux documents
    par_doc = defaultdict(list)
    for k, ds in mentions.items():
        for d in ds:
            par_doc[d].append(k)
    paires = Counter()
    for d, ks in par_doc.items():
        if len(ks) <= 25:
            for a, b in combinations(sorted(ks), 2):
                paires[(a, b)] += 1

    if SORTIE.exists():
        SORTIE.unlink()
    g = sqlite3.connect(SORTIE)
    g.executescript("""
        CREATE TABLE entites (id TEXT PRIMARY KEY, type TEXT, nom TEXT, notice TEXT, qid TEXT, lat REAL, lon REAL,
                              image TEXT, image_legende TEXT, naissance TEXT, mort TEXT, poids INTEGER);
        CREATE TABLE formes (entite TEXT, forme TEXT, n INTEGER);
        CREATE TABLE documents (id TEXT PRIMARY KEY, type TEXT, titre TEXT, date TEXT, episode TEXT, resume TEXT,
                                image TEXT, importance INTEGER);
        CREATE TABLE mentions (entite TEXT, document TEXT);
        CREATE TABLE liens (a TEXT, b TEXT, poids INTEGER);
        CREATE TABLE relations (a TEXT, b TEXT, relation TEXT, nature TEXT, document TEXT);
        CREATE INDEX relations_a ON relations(a);
        CREATE INDEX relations_b ON relations(b);
        CREATE INDEX mentions_e ON mentions(entite);
        CREATE INDEX mentions_d ON mentions(document);
        CREATE INDEX liens_a ON liens(a);
        CREATE INDEX liens_b ON liens(b);
        CREATE INDEX formes_e ON formes(entite);
        CREATE VIRTUAL TABLE recherche USING fts5(ref UNINDEXED, genre UNINDEXED, nom, formes, texte,
                                                  tokenize = 'unicode61 remove_diacritics 2');
    """)
    for k, e in entites.items():
        wd = wikidata.get(k) or {}
        g.execute("INSERT INTO entites VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (k, e["type"], e["nom"], wd.get("notice", ""), wd.get("qid"), wd.get("lat"), wd.get("lon"),
                   vignette(wd.get("portrait")), wd.get("portrait"), wd.get("naissance"), wd.get("mort"),
                   len(mentions[k])))
        g.executemany("INSERT INTO formes VALUES (?,?,?)", [(k, f, n) for f, n in e["formes"].items()])
        g.execute("INSERT INTO recherche VALUES (?,?,?,?,?)",
                  (k, e["type"], e["nom"], " ; ".join(e["formes"]), wd.get("notice", "")))
    for d, x in docs.items():
        g.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?)",
                  (d, x["type"], x["titre"], x["date"], x["episode"], x["resume"], x.get("image"),
                   x.get("importance")))
        g.execute("INSERT INTO recherche VALUES (?,?,?,?,?)",
                  (d, x["type"], x["titre"], titres_ep.get(x["episode"] or "", ""), (x["resume"] + "\n" + x["texte"])))
    g.executemany("INSERT INTO mentions VALUES (?,?)", [(k, d) for k, ds in mentions.items() for d in ds])
    g.executemany("INSERT INTO liens VALUES (?,?,?)", [(a, b, n) for (a, b), n in paires.items() if n >= 2])
    g.executemany("INSERT INTO relations VALUES (?,?,?,?,?)", relations)
    g.commit()
    n = Counter(e["type"] for e in entites.values())
    print(f"{SORTIE.name} : {len(entites)} entités {dict(n)}, {len(docs)} documents "
          f"{dict(Counter(x['type'] for x in docs.values()))}, "
          f"{sum(len(v) for v in mentions.values())} mentions, {sum(1 for v in paires.values() if v >= 2)} liens, "
          f"{len(relations)} relations lues")


if __name__ == "__main__":
    main()
