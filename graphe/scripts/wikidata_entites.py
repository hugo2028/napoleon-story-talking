"""Rattache les entités du graphe (data/rag/napoleon_graphe.sqlite) à Wikidata et recense leurs images d'époque
(docs/MEMOIRE.md).

1. Pour chaque entité citée dans au moins --min documents : recherche Wikidata en français (wbsearchentities), puis
   choix du candidat cohérent avec l'époque (personne née entre 1700 et 1810 ; lieu avec coordonnées ; événement
   entre 1785 et 1821). Garde : identifiant, nom, description, coordonnées, naissance, mort, image (P18).
2. Images d'époque : les œuvres qui représentent l'entité (P180 « dépeint ») et datées (P571) d'avant 1840, avec
   leur image ; le portrait (P18) d'une personne n'est gardé que s'il vient lui-même d'une œuvre datée d'avant 1840
   ou si sa date est inconnue (le cartel le dira).
Écrit napoleon-corpus/metadata/entites_wikidata.json (rien n'est téléchargé : seulement les noms de fichiers
Commons et leur poids). Le téléchargement des vignettes est une étape à part (--telecharger), après accord.

    python graphe/scripts/wikidata_entites.py [--min 3] [--limite 1500]
    python graphe/scripts/wikidata_entites.py --telecharger          # vignettes 400 px → web/decor/memoire/
"""
import argparse
import json
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
OUT = GRAPHE_DIR / "donnees" / "entites_wikidata.json"
IMAGES = ROOT / "web" / "decor" / "memoire"
API = "https://www.wikidata.org/w/api.php"
SPARQL = "https://query.wikidata.org/sparql"
UA = {"User-Agent": "napoleon-archives-research/1.0 (educational project; contact via repository)"}
ANNEE_MAX_OEUVRE = 1840


def get(url, params, pause=1.0):
    """Une requête par seconde au plus ; sur « 429 Too Many Requests », on attend le délai demandé."""
    err = None
    for essai in range(6):
        try:
            req = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}", headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                time.sleep(pause)
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err = e
            attente = int(e.headers.get("Retry-After") or 0) if e.code == 429 else 0
            time.sleep(max(attente, 5 * (essai + 1)))
        except Exception as e:    # réseau : on attend et on réessaie
            err = e
            time.sleep(3 * (essai + 1))
    raise err


def annee(claim_val) -> int | None:
    m = re.match(r"[+-](\d{4})", (claim_val or {}).get("time", ""))
    return int(m.group(1)) if m else None


def valeur(claims, prop):
    for c in claims.get(prop, []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if v is not None:
            return v
    return None


def recherche_nom(nom: str) -> str:
    """Le nom tel qu'on le cherche : sans grade ni article (« général Augereau » → « Augereau »)."""
    s = re.sub(r"^(?:le |la |les |l'|général |maréchal |amiral |colonel |citoyen |m\. |prince |roi |duc )+", "",
               nom.strip(), flags=re.I)
    return s


def coherent(genre, claims) -> int:
    """Score de cohérence avec l'époque (0 : à écarter)."""
    if genre == "personne":
        if valeur(claims, "P31") and valeur(claims, "P31").get("id") != "Q5":
            return 0
        n = annee(valeur(claims, "P569"))
        return 3 if n and 1700 <= n <= 1810 else 0
    if genre == "lieu":
        return 2 if valeur(claims, "P625") else 0
    if genre == "evenement":
        a = annee(valeur(claims, "P585")) or annee(valeur(claims, "P580"))
        return 3 if a and 1785 <= a <= 1821 else 0
    return 1


def relier(conn, min_docs, limite):
    deja = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"entites": {}}
    ents = conn.execute("SELECT id, type, nom FROM entites WHERE poids >= ? ORDER BY poids DESC LIMIT ?",
                        (min_docs, limite)).fetchall()
    for k, (eid, genre, nom) in enumerate(ents, 1):
        if eid in deja["entites"]:
            continue
        cherche = recherche_nom(nom)
        try:
            cands = get(API, {"action": "wbsearchentities", "search": cherche, "language": "fr", "uselang": "fr",
                              "limit": 6, "format": "json"}).get("search", [])
            if not cands:
                deja["entites"][eid] = {}
                continue
            details = get(API, {"action": "wbgetentities", "ids": "|".join(c["id"] for c in cands),
                                "props": "claims|labels|descriptions", "languages": "fr|en", "format": "json"})
        except Exception as e:
            print(f"[{k}] {nom} : {e}")
            continue
        meilleur, score = None, 0
        for rang, c in enumerate(cands):
            d = details["entities"].get(c["id"], {})
            s = coherent(genre, d.get("claims", {}))
            if s and s - rang * 0.3 > score:
                meilleur, score = d, s - rang * 0.3
        if not meilleur:
            deja["entites"][eid] = {}
            continue
        cl = meilleur.get("claims", {})
        coord = valeur(cl, "P625") or {}
        lab = meilleur.get("labels", {})
        desc = meilleur.get("descriptions", {})
        deja["entites"][eid] = {
            "qid": meilleur["id"], "nom": (lab.get("fr") or lab.get("en") or {}).get("value"),
            "notice": (desc.get("fr") or desc.get("en") or {}).get("value", ""),
            "lat": coord.get("latitude"), "lon": coord.get("longitude"),
            "naissance": str(annee(valeur(cl, "P569")) or "") or None, "mort": str(annee(valeur(cl, "P570")) or "") or None,
            "portrait": valeur(cl, "P18")}
        if k % 10 == 0:
            OUT.write_text(json.dumps(deja, ensure_ascii=False, indent=0), encoding="utf-8")
        if k % 50 == 0:
            print(f"[{k}/{len(ents)}] {nom} → {deja['entites'][eid].get('qid')} {deja['entites'][eid].get('notice', '')[:50]}",
                  flush=True)
            OUT.write_text(json.dumps(deja, ensure_ascii=False, indent=0), encoding="utf-8")
    OUT.write_text(json.dumps(deja, ensure_ascii=False, indent=0), encoding="utf-8")
    return deja


def oeuvres_d_epoque(deja):
    """Pour les entités rattachées : œuvres qui les représentent, datées d'avant ANNEE_MAX_OEUVRE, avec image."""
    qids = {v["qid"]: k for k, v in deja["entites"].items() if v.get("qid")}
    liste = list(qids)
    oeuvres = deja.setdefault("oeuvres", {})
    for i in range(0, len(liste), 60):
        bloc = " ".join(f"wd:{q}" for q in liste[i:i + 60])
        requete = f"""SELECT ?sujet ?oeuvre ?oeuvreLabel ?image ?date ?auteurLabel WHERE {{
          VALUES ?sujet {{ {bloc} }}
          ?oeuvre wdt:P180 ?sujet ; wdt:P18 ?image ; wdt:P571 ?date .
          FILTER(YEAR(?date) <= {ANNEE_MAX_OEUVRE})
          OPTIONAL {{ ?oeuvre wdt:P170 ?auteur }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "fr,en". }}
        }} LIMIT 2000"""
        try:
            r = get(SPARQL, {"query": requete, "format": "json"}, pause=1.0)
        except Exception as e:
            print(f"SPARQL {i} : {e}")
            continue
        for b in r["results"]["bindings"]:
            q = b["oeuvre"]["value"].rsplit("/", 1)[1]
            o = oeuvres.setdefault(q, {"titre": b["oeuvreLabel"]["value"], "date": b["date"]["value"][:4],
                                       "auteur": b.get("auteurLabel", {}).get("value", ""),
                                       "image": urllib.parse.unquote(b["image"]["value"].rsplit("/", 1)[1]),
                                       "sujets": []})
            e = qids[b["sujet"]["value"].rsplit("/", 1)[1]]
            if e not in o["sujets"]:
                o["sujets"].append(e)
        print(f"œuvres d'époque : {len(oeuvres)} (bloc {i // 60 + 1})", flush=True)
    OUT.write_text(json.dumps(deja, ensure_ascii=False, indent=0), encoding="utf-8")


def poids_images(deja):
    """Taille des vignettes à télécharger (400 px de large), demandée à Commons sans rien télécharger."""
    fichiers = sorted({o["image"] for o in deja.get("oeuvres", {}).values()}
                      | {v["portrait"] for v in deja["entites"].values() if v.get("portrait")})
    total, n = 0, 0
    for i in range(0, len(fichiers), 50):
        r = get("https://commons.wikimedia.org/w/api.php",
                {"action": "query", "titles": "|".join(f"File:{f}" for f in fichiers[i:i + 50]), "prop": "imageinfo",
                 "iiprop": "url|size|extmetadata", "iiurlwidth": 400, "format": "json"})
        for p in r.get("query", {}).get("pages", {}).values():
            ii = (p.get("imageinfo") or [{}])[0]
            if ii.get("thumburl"):
                n += 1
                # Une vignette JPEG de 400 px pèse environ 1/12 de l'original redimensionné : estimation prudente
                total += min(ii.get("size", 0), 120_000) * 0.5
                licence = ii.get("extmetadata", {}).get("LicenseShortName", {}).get("value", "")
                deja.setdefault("fichiers", {})[p["title"][5:]] = {"vignette": ii["thumburl"], "licence": licence}
    OUT.write_text(json.dumps(deja, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"{n} images (portraits et œuvres d'avant {ANNEE_MAX_OEUVRE}) ; vignettes 400 px : environ "
          f"{total / 1e6:.0f} Mo au total")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=int, default=3)
    ap.add_argument("--limite", type=int, default=1500)
    ap.add_argument("--telecharger", action="store_true")
    args = ap.parse_args()
    if args.telecharger:
        deja = json.loads(OUT.read_text(encoding="utf-8"))
        IMAGES.mkdir(parents=True, exist_ok=True)
        for f, info in (deja.get("fichiers") or {}).items():
            cible = IMAGES / (re.sub(r"[^\w.-]+", "_", f)[:120] + ".jpg")
            if cible.exists():
                continue
            req = urllib.request.Request(info["vignette"], headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                cible.write_bytes(r.read())
            time.sleep(0.3)
        print(f"{len(list(IMAGES.glob('*.jpg')))} vignettes dans {IMAGES.relative_to(ROOT)}")
        return
    deja = relier(sqlite3.connect(GRAPHE), args.min, args.limite)
    oeuvres_d_epoque(deja)
    poids_images(deja)


if __name__ == "__main__":
    main()
