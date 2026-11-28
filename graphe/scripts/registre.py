"""Étape 1 du protocole (graphe/PROTOCOLE.md, § 5.1) : le registre de référence, construit depuis Wikidata.

Pour chaque entité du graphe provisoire citée dans au moins --min documents :
- les formes qui sont des titres ou des fonctions (« roi de Naples », « duc de Rivoli », « ministre de la Guerre »)
  ne sont PAS cherchées comme des noms : elles se résolvent par la date (outil qui_porte du lecteur), grâce aux titres
  datés des personnes du registre ; elles sont listées à part ;
- personnes : recherche restreinte aux humains (haswbstatement:P31=Q5), candidat né entre 1700 et 1810 ;
- lieux : recherche restreinte aux entités qui ont des coordonnées (haswbstatement:P625).
On garde : identifiant, nom, notice, autres noms (fr, en), naissance, mort, coordonnées, titres de noblesse datés
(P97, qualificatifs P580/P582), fonctions datées (P39), et pour une personne son portrait (P18). Aucune image pour un
lieu (ce seraient des photographies modernes). Aucun lien entre entités n'est pris de Wikidata (protocole, § 4).

Reprise possible ; un manifeste de lancement est écrit dans graphe/runs/.

    python graphe/scripts/registre.py [--min 3] [--limite 2000]
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GRAPHE_DIR = ROOT / "graphe"
GRAPHE = ROOT / "data" / "rag" / "napoleon_graphe.sqlite"
OUT = GRAPHE_DIR / "donnees" / "registre.json"
API = "https://www.wikidata.org/w/api.php"
UA = {"User-Agent": "napoleon-archives-research/1.1 (educational research project)"}
TITRE = re.compile(r"^(?:l'|le |la |les |s\. ?m\. |sa majesté )?(?:roi|reine|empereur|impératrice|prince|princesse|"
                   r"duc|duchesse|grand-duc|grande-duchesse|archiduc|archiduchesse|comte|comtesse|marquis|baron|"
                   r"vice-roi|électeur|pape|saint-père|sultan|pacha|bey|consul|premier consul|ministre|"
                   r"directeur|directoire|chef d'état-major|major général|gouverneur|préfet|ambassadeur|"
                   r"prince-primat|cardinal|archevêque|évêque|grand-vizir|tsar|czar|landgrave|margrave)\b", re.I)
GRADES = re.compile(r"^(?:(?:le|la|les|l'|général|maréchal|amiral|colonel|capitaine|lieutenant|commandant|"
                    r"contre-amiral|vice-amiral|chef de brigade|citoyen|citoyenne|m\.|mme|madame|monsieur|"
                    r"adjudant-général|adjudant général|général de division|général de brigade)\s+)+", re.I)


def get(params, pause=0.6):
    err = None
    for essai in range(6):
        try:
            req = urllib.request.Request(f"{API}?{urllib.parse.urlencode(params)}", headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                time.sleep(pause)
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err = e
            time.sleep(max(int(e.headers.get("Retry-After") or 0) if e.code == 429 else 0, 5 * (essai + 1)))
        except Exception as e:
            err = e
            time.sleep(3 * (essai + 1))
    raise err


def annee(v):
    m = re.match(r"[+-](\d{4})", (v or {}).get("time", "")) if isinstance(v, dict) else None
    return int(m.group(1)) if m else None


def val(claims, prop):
    for c in claims.get(prop, []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if v is not None:
            return v
    return None


def qualif(c, prop):
    for q in (c.get("qualifiers") or {}).get(prop, []):
        v = q.get("datavalue", {}).get("value")
        if v is not None:
            return v
    return None


def date_q(v):
    """Date d'un qualificatif : YYYY-MM-DD, YYYY-MM ou YYYY selon sa précision."""
    if not isinstance(v, dict) or "time" not in v:
        return None
    t, prec = v["time"], v.get("precision", 9)
    return t[1:11] if prec >= 11 else t[1:8] if prec == 10 else t[1:5]


def datés(claims, prop):
    out = []
    for c in claims.get(prop, []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(v, dict) and v.get("id"):
            out.append({"qid": v["id"], "debut": date_q(qualif(c, "P580")), "fin": date_q(qualif(c, "P582"))})
    return out


SPARQL = "https://query.wikidata.org/sparql"
# Types qui ne sont jamais les lieux de la correspondance : rues, routes, stations, bâtiments, universités…
TYPES_EXCLUS = {"Q79007", "Q34442", "Q928830", "Q55488", "Q3918", "Q875538", "Q41176", "Q1248784", "Q16917",
                "Q13226383", "Q22698", "Q33506", "Q207694", "Q1007870", "Q2977", "Q16970", "Q44539", "Q12280"}


def sparql(requete):
    err = None
    for essai in range(5):
        try:
            req = urllib.request.Request(f"{SPARQL}?{urllib.parse.urlencode({'query': requete, 'format': 'json'})}",
                                         headers=UA)
            with urllib.request.urlopen(req, timeout=90) as r:
                time.sleep(1.0)
                return json.loads(r.read().decode("utf-8"))["results"]["bindings"]
        except urllib.error.HTTPError as e:
            err = e
            time.sleep(max(int(e.headers.get("Retry-After") or 0) if e.code == 429 else 0, 8 * (essai + 1)))
        except Exception as e:
            err = e
            time.sleep(5 * (essai + 1))
    raise err


def candidats_sparql(noms, genre):
    """{nom: [(qid, notoriété, types)]} : entités dont un libellé, un alias ou (personnes) le nom de famille est
    exactement ce nom, en français ou en anglais ; personnes nées entre 1700 et 1810, lieux avec coordonnées."""
    vals = " ".join(f'"{n.replace(chr(34), "")}"@fr "{n.replace(chr(34), "")}"@en' for n in noms)
    if genre == "personne":
        corps = """{ ?item rdfs:label ?n } UNION { ?item skos:altLabel ?n } UNION { ?item wdt:P734 ?fam . ?fam rdfs:label ?n }
          ?item wdt:P31 wd:Q5 ; wdt:P569 ?naiss . FILTER(YEAR(?naiss) >= 1700 && YEAR(?naiss) <= 1810)
          OPTIONAL { ?item wdt:P570 ?mort }
          OPTIONAL { ?item wdt:P410 ?grade }
          OPTIONAL { ?item wdt:P241 ?arme }
          OPTIONAL { ?item wdt:P106 ?metier . VALUES ?metier { wd:Q189290 wd:Q47064 wd:Q82955 wd:Q193391 wd:Q116
                     wd:Q19934 wd:Q1097498 wd:Q372436 wd:Q250867 wd:Q212238 wd:Q16533 } }"""
    else:
        corps = """{ ?item rdfs:label ?n } UNION { ?item skos:altLabel ?n }
          ?item p:P625/psv:P625 ?cv . ?cv wikibase:geoLatitude ?lat ; wikibase:geoLongitude ?lon .
          FILTER NOT EXISTS { ?item wdt:P31/wdt:P279? ?exclu .
            VALUES ?exclu { wd:Q12819564 wd:Q928830 wd:Q55488 wd:Q473972 wd:Q41176 wd:Q79007 wd:Q34442 wd:Q3918
                            wd:Q1248784 wd:Q16917 wd:Q33506 } }"""
    req = f"""SELECT ?n ?item ?liens (GROUP_CONCAT(DISTINCT ?type) AS ?types) (MIN(YEAR(?naiss)) AS ?ne)
      (MIN(YEAR(?mort)) AS ?mo) (COUNT(DISTINCT ?grade) + COUNT(DISTINCT ?arme) + COUNT(DISTINCT ?metier) AS ?domaine)
      (COUNT(DISTINCT ?grade) + COUNT(DISTINCT ?arme) AS ?militaire)
      (SAMPLE(?lat) AS ?la) (SAMPLE(?lon) AS ?lo)
      WHERE {{
      VALUES ?n {{ {vals} }}
      {corps}
      ?item wikibase:sitelinks ?liens .
      OPTIONAL {{ ?item wdt:P31 ?type }}
    }} GROUP BY ?n ?item ?liens"""
    out = {}
    for b in sparql(req):
        n = b["n"]["value"]
        q = b["item"]["value"].rsplit("/", 1)[1]
        types = {t.rsplit("/", 1)[1] for t in b.get("types", {}).get("value", "").split() if t}
        if types & TYPES_EXCLUS:
            continue
        num = lambda k: int(float(b[k]["value"])) if k in b and b[k].get("value") else None
        out.setdefault(n, []).append({"qid": q, "liens": int(b["liens"]["value"]), "types": types,
                                      "ne": num("ne"), "mort": num("mo"), "domaine": num("domaine") or 0,
                                      "militaire": num("militaire") or 0,
                                      "coord": (float(b["la"]["value"]), float(b["lo"]["value"]))
                                      if b.get("la") and b.get("lo") else None})
    return out


def score_personne(c, premiere, derniere):
    """Plausibilité d'une personne pour les mentions du corpus (années de première et dernière mention) : adulte à
    la première mention, vivante (à deux ans près) à la dernière ; carrière militaire, politique ou diplomatique ;
    notoriété. None si impossible."""
    if premiere and c["ne"] and c["ne"] > premiere - 14:
        return None
    if derniere and c["mort"] and c["mort"] < min(premiere or derniere, derniere) - 2:
        return None
    return math.log1p(c["liens"]) + (3.0 if c["domaine"] else 0.0)


CENTRE_CORPUS = (45.0, 12.0)            # Europe et Méditerranée
TYPES_PEU_PROBABLES = {"Q473972", "Q182547"}   # aire protégée, province romaine


def score_lieu(c):
    sc = math.log1p(c["liens"])
    if c.get("coord"):
        if distance_km(c["coord"], CENTRE_CORPUS) > 4000:      # ne joue qu'entre homonymes : Sainte-Hélène reste
            sc -= 3.0
    if c["types"] & TYPES_PEU_PROBABLES:
        sc -= 2.0
    return sc


def nom_cherche(nom):
    return GRADES.sub("", nom.strip()).strip(" .,;")


def distance_km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def choisir(genre, nom, ids, voisins=None):
    """Le candidat cohérent avec l'époque ; pour un lieu, `voisins` : coordonnées des lieux déjà identifiés que le
    corpus cite avec lui (cohérence géographique : Rosette, citée avec Damiette et Alexandrie, est en Égypte)."""
    if not ids:
        return None
    det = get({"action": "wbgetentities", "ids": "|".join(ids), "props": "labels|aliases|descriptions|claims|sitelinks",
               "languages": "fr|en", "format": "json"})["entities"]
    meilleur, score = None, 0.0
    cible = re.sub(r"[^a-z]", "", nom.lower().split()[-1]) if nom.split() else ""
    for rang, q in enumerate(ids):
        d = det.get(q) or {}
        cl = d.get("claims", {})
        if genre == "personne":
            n = annee(val(cl, "P569"))
            if not n or not 1700 <= n <= 1810:
                continue
            s = 3.0
        else:
            if not val(cl, "P625"):
                continue
            s = 2.0
        libelles = [x.get("value", "") for x in (d.get("labels") or {}).values()] + \
                   [a.get("value", "") for al in (d.get("aliases") or {}).values() for a in al]
        if cible and any(cible in re.sub(r"[^a-z]", "", l.lower()) for l in libelles):
            s += 1.0
        # Notoriété (nombre de Wikipédias) : la Vienne d'Autriche avant la Vienne de l'Isère, le Caire d'Égypte
        # avant la commune homonyme ; elle départage les homonymes plus que le rang de la recherche
        s += math.log1p(len(d.get("sitelinks") or {})) * 0.9
        s -= rang * 0.15
        if genre == "lieu" and voisins:
            c = val(cl, "P625") or {}
            if c.get("latitude") is not None:
                dists = sorted(distance_km((c["latitude"], c["longitude"]), v) for v in voisins)
                proche = dists[len(dists) // 2]          # distance médiane aux lieux cités avec lui
                s += 2.5 if proche < 300 else 1.5 if proche < 800 else 0.0 if proche < 2000 else -2.0
        if s > score:
            meilleur, score = d, s
    return meilleur


def fiche(d, genre, nom):
    cl = d.get("claims", {})
    lab, desc = d.get("labels", {}), d.get("descriptions", {})
    alias = sorted({a["value"] for al in (d.get("aliases") or {}).values() for a in al} | {x["value"] for x in lab.values()})
    coord = val(cl, "P625") or {}
    types = {(c.get("mainsnak", {}).get("datavalue", {}).get("value") or {}).get("id") for c in cl.get("P31", [])}
    return {"type": genre, "forme": nom, "qid": d["id"], "nom": (lab.get("fr") or lab.get("en") or {}).get("value"),
            "notice": (desc.get("fr") or desc.get("en") or {}).get("value", ""), "alias": alias,
            "naissance": annee(val(cl, "P569")), "mort": annee(val(cl, "P570")),
            "lat": coord.get("latitude"), "lon": coord.get("longitude"),
            # Un lieu « spécifique » (ville, village, fort…) sert de repère géographique ; un pays ou une région, non
            "specifique": genre == "lieu" and not types & {"Q6256", "Q3624078", "Q7275", "Q82794", "Q10864048",
                                                           "Q107390", "Q35657", "Q1620908", "Q3336843"},
            "portrait": val(cl, "P18") if genre == "personne" else None,
            "titres": datés(cl, "P97"), "fonctions": datés(cl, "P39")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=int, default=3)
    ap.add_argument("--limite", type=int, default=2000)
    args = ap.parse_args()
    debut = time.time()
    reg = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"entites": {}, "titres_a_resoudre": [],
                                                                         "libelles_titres": {}}
    conn = sqlite3.connect(GRAPHE)
    ents = conn.execute("SELECT id, type, nom, poids FROM entites WHERE poids >= ? AND type IN ('personne','lieu') "
                        "ORDER BY poids DESC LIMIT ?", (args.min, args.limite)).fetchall()
    periode_mentions = {}
    for e, mn, mx in conn.execute("SELECT m.entite, MIN(substr(d.date, 1, 4)), MAX(substr(d.date, 1, 4)) "
                                  "FROM mentions m JOIN documents d ON d.id = m.document "
                                  "WHERE d.date GLOB '1[78][0-9][0-9]*' GROUP BY m.entite"):
        periode_mentions[e] = (int(mn), int(mx))
    co_cites = {}
    for a, b, n in conn.execute("SELECT l.a, l.b, l.poids FROM liens l JOIN entites ea ON ea.id=l.a "
                                "JOIN entites eb ON eb.id=l.b WHERE ea.type='lieu' AND eb.type='lieu' "
                                "ORDER BY l.poids DESC"):
        co_cites.setdefault(a, []).append(b)
        co_cites.setdefault(b, []).append(a)
    conn.close()
    titres = set(reg["titres_a_resoudre"])
    n_req = [0]
    a_faire = []
    for eid, genre, nom, poids in ents:
        if eid in reg["entites"] or eid in titres:
            continue
        if genre == "personne" and TITRE.match(nom.strip()):
            titres.add(eid)
            continue
        q = nom_cherche(nom)
        if len(q) >= 2:
            a_faire.append((eid, genre, nom, q))
    for genre in ("personne", "lieu"):
        lot_genre = [x for x in a_faire if x[1] == genre]
        for i in range(0, len(lot_genre), 50):
            lot = lot_genre[i:i + 50]
            try:
                cands = candidats_sparql(sorted({x[3] for x in lot}), genre)
                n_req[0] += 1
            except Exception as e:
                print(f"SPARQL {genre} {i} : {e}", flush=True)
                continue
            # Pour chaque nom, les candidats les plus notoires ; détails (titres, fonctions) en une requête par lot
            choix, homonymes = {}, {}
            for eid, _, nom, q in lot:
                prem, der = periode_mentions.get(eid, (None, None))
                notes = []
                vus_q = set()
                for c in cands.get(q, []):
                    if c["qid"] in vus_q:          # même entité trouvée par son libellé français et anglais
                        continue
                    vus_q.add(c["qid"])
                    sc = score_personne(c, prem, der) if genre == "personne" else score_lieu(c)
                    if sc is not None:
                        notes.append((sc, c["qid"]))
                meilleur_militaire = any(c["militaire"] for c in cands.get(q, []) if notes and c["qid"] == max(notes)[1])
                if genre == "personne" and (not notes or not meilleur_militaire):
                    try:
                        # Recherche floue (variantes d'orthographe et OCR : Davoust → Davout, Serrurier → Sérurier),
                        # parmi les personnes qui ont un grade militaire : le domaine de la correspondance
                        r = get({"action": "query", "list": "search",
                                 "srsearch": f"{q}~ haswbstatement:P31=Q5 haswbstatement:P410",
                                 "srlimit": 5, "srnamespace": 0, "format": "json"})
                        n_req[0] += 1
                        ids_r = [h["title"] for h in r.get("query", {}).get("search", [])]
                        if ids_r:
                            dr = get({"action": "wbgetentities", "ids": "|".join(ids_r), "props": "claims|sitelinks",
                                      "format": "json"}).get("entities", {})
                            n_req[0] += 1
                            for rang, qid in enumerate(ids_r):
                                cl = (dr.get(qid) or {}).get("claims", {})
                                c = {"qid": qid, "liens": len((dr.get(qid) or {}).get("sitelinks") or {}),
                                     "ne": annee(val(cl, "P569")), "mort": annee(val(cl, "P570")),
                                     "domaine": int(bool(cl.get("P410") or cl.get("P241"))), "types": set(),
                                     "militaire": 1}
                                if not c["ne"] or not 1700 <= c["ne"] <= 1810:
                                    continue
                                sc = score_personne(c, prem, der)
                                if sc is not None:
                                    notes.append((sc - 0.3 * rang - 1.0, qid))     # moins sûr qu'un nom exact
                    except Exception as e:
                        print(f"repli {q} : {e}", flush=True)
                if genre == "lieu" and not notes:
                    # Orthographe ancienne (Koenigsberg, Passeriano) : recherche floue parmi les lieux à coordonnées
                    try:
                        r = get({"action": "query", "list": "search", "srsearch": f"{q}~ haswbstatement:P625",
                                 "srlimit": 4, "srnamespace": 0, "format": "json"})
                        n_req[0] += 1
                        ids_r = [h["title"] for h in r.get("query", {}).get("search", [])]
                        if ids_r:
                            dr = get({"action": "wbgetentities", "ids": "|".join(ids_r), "props": "claims|sitelinks",
                                      "format": "json"}).get("entities", {})
                            n_req[0] += 1
                            for rang, qid in enumerate(ids_r):
                                cl = (dr.get(qid) or {}).get("claims", {})
                                co = val(cl, "P625") or {}
                                c = {"qid": qid, "liens": len((dr.get(qid) or {}).get("sitelinks") or {}), "types": set(),
                                     "coord": (co["latitude"], co["longitude"]) if co.get("latitude") is not None else None}
                                notes.append((score_lieu(c) - 0.3 * rang - 1.0, qid))
                    except Exception as e:
                        print(f"repli {q} : {e}", flush=True)
                notes.sort(reverse=True)
                if genre == "lieu" and len(notes) > 1 and notes[0][0] - notes[1][0] < 0.7:
                    choix[eid] = [q_ for _, q_ in notes[:4]]           # la géographie départage
                else:
                    choix[eid] = [q_ for _, q_ in notes[:1]]
                # Homonymes plausibles (écart de note < 1,5) : le lecteur choisira document par document
                homonymes[eid] = list(dict.fromkeys(q_ for sc, q_ in notes[1:5]
                                                    if notes[0][0] - sc < 1.5 and q_ != notes[0][1]))[:3]
            ids = sorted({q for v in choix.values() for q in v} | {q for v in homonymes.values() for q in v})
            det = {}
            for j in range(0, len(ids), 50):
                r = get({"action": "wbgetentities", "ids": "|".join(ids[j:j + 50]),
                         "props": "labels|aliases|descriptions|claims", "languages": "fr|en", "format": "json"})
                n_req[0] += 1
                det.update(r.get("entities", {}))
            for eid, _, nom, q in lot:
                qs = choix.get(eid) or []
                d = det.get(qs[0]) if qs else None
                if genre == "lieu" and len(qs) > 1:
                    voisins = [(reg["entites"][v]["lat"], reg["entites"][v]["lon"]) for v in co_cites.get(eid, [])
                               if reg["entites"].get(v, {}).get("lat") is not None
                               and reg["entites"][v].get("specifique")][:8]
                    if voisins:
                        def proche(qid):
                            c = val((det.get(qid) or {}).get("claims", {}), "P625") or {}
                            if c.get("latitude") is None:
                                return 1e9
                            ds = sorted(distance_km((c["latitude"], c["longitude"]), v) for v in voisins)
                            return ds[len(ds) // 2]
                        d = det.get(min(qs, key=proche))
                reg["entites"][eid] = fiche(d, genre, nom) if d else {"type": genre, "forme": nom, "qid": None}
                autres = [det[h] for h in homonymes.get(eid, []) if h in det and (not d or h != d["id"])]
                if d and autres:
                    reg["entites"][eid]["homonymes"] = [fiche(h, genre, nom) for h in autres]
            OUT.write_text(json.dumps({**reg, "titres_a_resoudre": sorted(titres)}, ensure_ascii=False, indent=0),
                           encoding="utf-8")
            print(f"{genre} {i + len(lot)}/{len(lot_genre)}", flush=True)
    reg["titres_a_resoudre"] = sorted(titres)

    # Libellés des titres et fonctions (« duc de Rivoli », « roi de Naples ») : pour qui_porte
    qids = sorted({t["qid"] for e in reg["entites"].values() for t in (e.get("titres") or []) + (e.get("fonctions") or [])}
                  - set(reg["libelles_titres"]))
    for i in range(0, len(qids), 50):
        r = get({"action": "wbgetentities", "ids": "|".join(qids[i:i + 50]), "props": "labels|aliases",
                 "languages": "fr|en", "format": "json"})
        n_req[0] += 1
        for q, d in r.get("entities", {}).items():
            noms = {x["value"] for x in (d.get("labels") or {}).values()} | \
                   {a["value"] for al in (d.get("aliases") or {}).values() for a in al}
            reg["libelles_titres"][q] = sorted(noms)
    OUT.write_text(json.dumps(reg, ensure_ascii=False, indent=0), encoding="utf-8")

    # Manifeste du lancement (protocole, § 9)
    rattachees = sum(1 for e in reg["entites"].values() if e.get("qid"))
    manifeste = {"etape": "1-registre", "protocole": "1.1", "date": dt.datetime.now().isoformat(timespec="seconds"),
                 "source": "Wikidata (API wbsearch / wbgetentities)", "parametres": vars(args),
                 "entites_candidates": len(ents), "rattachees": rattachees,
                 "sans_correspondance": sum(1 for e in reg["entites"].values() if not e.get("qid")),
                 "titres_a_resoudre": len(reg["titres_a_resoudre"]), "requetes": n_req[0],
                 "duree_s": round(time.time() - debut), "cout": 0,
                 "sortie_sha256": hashlib.sha256(OUT.read_bytes()).hexdigest()}
    (GRAPHE_DIR / "runs" / f"{dt.date.today()}_1-registre.json").write_text(
        json.dumps(manifeste, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(manifeste, ensure_ascii=False))


if __name__ == "__main__":
    main()
