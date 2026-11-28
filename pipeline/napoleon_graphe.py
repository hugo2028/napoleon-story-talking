"""Graphe de connaissances (data/rag/napoleon_graphe.sqlite, construit par graphe/scripts/build_graphe.py) : moteur de
recherche de la mémoire du visiteur et voisinage de chaque nœud (docs/MEMOIRE.md).

Références de nœuds : un identifiant d'entité (« massena », « znaim »), ou « lettre:123 », « oeuvre:456 »,
« tableau:wagram », « episode:wagram ».
"""
import re
import sqlite3
import unicodedata
from collections import defaultdict
from pathlib import Path

CHEMIN = Path(__file__).resolve().parent.parent / "data" / "rag" / "napoleon_graphe.sqlite"
GENRES_DOC = ("lettre", "oeuvre", "tableau", "episode")
MIN_COLLECTION = 3      # une entité « à collectionner » est citée dans au moins 3 documents
GRADES = re.compile(r"^(?:(?:le|la|les|l'|du|de|des|m\.|mme|monsieur|madame|citoyen|citoyenne|general|generale|"
                    r"marechal|amiral|colonel|capitaine|lieutenant|commandant|general de division|"
                    r"general de brigade|sa majeste)\s+)+")


def _plier(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower().replace("’", "'"))
    return "".join(c for c in s if not unicodedata.combining(c)).strip()


def cle(nom: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", GRADES.sub("", _plier(nom))).strip("-")[:70]


class Graphe:
    def __init__(self, chemin: Path = CHEMIN):
        self.ok = chemin.exists()
        self.db = sqlite3.connect(chemin, check_same_thread=False) if self.ok else None
        if self.ok:
            self.db.row_factory = sqlite3.Row
            # forme écrite (clé) → entité, pour rattacher les noms d'un récit aux nœuds du graphe
            self._formes = {}
            for e, f, n in self.db.execute("SELECT entite, forme, n FROM formes ORDER BY n"):
                self._formes[cle(f)] = e
            for (e,) in self.db.execute("SELECT id FROM entites"):
                self._formes.setdefault(e, e)

    # ── Nœuds ──────────────────────────────────────────────────────────────────
    def _entite(self, r) -> dict:
        return {"ref": r["id"], "genre": r["type"], "nom": r["nom"], "notice": r["notice"] or "",
                "image": r["image"], "lat": r["lat"], "lon": r["lon"], "poids": r["poids"],
                **({"naissance": r["naissance"], "mort": r["mort"]} if r["naissance"] or r["mort"] else {})}

    def _document(self, r) -> dict:
        return {"ref": r["id"], "genre": r["type"], "nom": r["titre"], "date": r["date"] or "",
                "episode": r["episode"], "resume": r["resume"] or "", "image": r["image"],
                "importance": r["importance"]}

    def noeuds(self, refs: list[str]) -> list[dict]:
        if not self.ok or not refs:
            return []
        refs = list(dict.fromkeys(refs))[:600]
        q = ",".join("?" * len(refs))
        out = {r["id"]: self._entite(r) for r in self.db.execute(f"SELECT * FROM entites WHERE id IN ({q})", refs)}
        out.update({r["id"]: self._document(r)
                    for r in self.db.execute(f"SELECT * FROM documents WHERE id IN ({q})", refs)})
        return [out[r] for r in refs if r in out]

    def resoudre(self, noms: list[str]) -> dict:
        """Nom écrit (« le duc de Rivoli ») → entité du graphe, quand elle est connue."""
        if not self.ok:
            return {}
        out = {}
        for n in noms:
            k = cle(n)
            if k in self._formes:
                out[n] = self._formes[k]
        return out

    def formes_de(self, ids: list[str]) -> dict:
        """Les formes écrites de chaque entité (pour la retrouver dans un texte)."""
        if not self.ok or not ids:
            return {}
        q = ",".join("?" * len(ids))
        out = defaultdict(set)
        for r in self.db.execute(f"SELECT entite, forme FROM formes WHERE entite IN ({q}) AND n >= 1", ids):
            out[r["entite"]].add(r["forme"])
        for r in self.db.execute(f"SELECT id, nom FROM entites WHERE id IN ({q})", ids):
            out[r["id"]].add(r["nom"])
        return out

    # ── Recherche ──────────────────────────────────────────────────────────────
    def rechercher(self, texte: str, limite: int = 30, genres: list[str] | None = None) -> list[dict]:
        """Plein texte sans accents, chaque mot pris aussi comme début de mot ; les noms pèsent plus que les textes,
        puis le nombre de documents d'une entité départage."""
        if not self.ok:
            return []
        mots = re.findall(r"\w+", _plier(texte))[:8]
        if not mots:
            return []
        requete = " ".join(f'"{m}"*' for m in mots)
        rows = self.db.execute(
            "SELECT ref, genre, bm25(recherche, 0, 0, 10.0, 5.0, 1.0) AS s FROM recherche WHERE recherche MATCH ? "
            "ORDER BY s LIMIT ?", (requete, 400)).fetchall()
        if genres:
            rows = [r for r in rows if r["genre"] in genres]
        refs = [r["ref"] for r in rows]
        score = {r["ref"]: r["s"] for r in rows}
        noeuds = self.noeuds(refs)
        # bm25 : plus petit = meilleur ; une entité très citée remonte un peu
        for n in noeuds:
            n["score"] = round(-score[n["ref"]] + (min(n.get("poids") or 0, 300) ** 0.5) * 0.4, 3)
        noeuds.sort(key=lambda n: -n["score"])
        return noeuds[:limite]

    def extrait(self, ref: str, longueur: int = 600) -> str:
        if not self.ok:
            return ""
        r = self.db.execute("SELECT texte FROM recherche WHERE ref=? AND genre IN ('lettre','oeuvre','tableau')",
                            (ref,)).fetchone()
        return (r["texte"] or "").strip()[:longueur] if r else ""

    # ── Voisinage ──────────────────────────────────────────────────────────────
    def voisins(self, ref: str, limite: int = 24) -> list[dict]:
        """Ce qui est relié à un nœud, le plus fort d'abord : entités citées ensemble, documents qui le citent,
        tableaux, épisode."""
        if not self.ok:
            return []
        out = []
        if ref.split(":")[0] in GENRES_DOC:
            if ref.startswith("episode:"):
                ep = ref.split(":", 1)[1]
                docs = self.db.execute("SELECT id FROM documents WHERE episode=? AND type IN ('tableau','oeuvre') "
                                       "ORDER BY type='tableau' DESC, importance DESC LIMIT ?", (ep, limite // 2))
                out += [(r["id"], "document de l'épisode", 3) for r in docs]
                ents = self.db.execute(
                    "SELECT m.entite, COUNT(*) n FROM mentions m JOIN documents d ON d.id=m.document "
                    "WHERE d.episode=? GROUP BY m.entite ORDER BY n DESC LIMIT ?", (ep, limite // 2))
                out += [(r["entite"], "cité dans l'épisode", r["n"]) for r in ents]
            else:
                for r in self.db.execute("SELECT m.entite, e.poids FROM mentions m JOIN entites e ON e.id=m.entite "
                                         "WHERE m.document=? ORDER BY e.poids DESC LIMIT ?", (ref, limite)):
                    out.append((r["entite"], "cité", r["poids"]))
                ep = self.db.execute("SELECT episode FROM documents WHERE id=?", (ref,)).fetchone()
                if ep and ep["episode"]:
                    out.append((f"episode:{ep['episode']}", "épisode", 50))
        else:
            # Liens lus dans les lettres (intitulé, nature, lettre source) d'abord, puis les entités citées ensemble
            lus = set()
            for r in self.db.execute(
                    "SELECT a, b, relation, COUNT(*) n, MIN(document) doc FROM relations WHERE a=? OR b=? "
                    "GROUP BY a, b, relation ORDER BY n DESC LIMIT ?", (ref, ref, limite // 2)):
                v = r["b"] if r["a"] == ref else r["a"]
                if v in lus:
                    continue
                lus.add(v)
                rel = r["relation"] if r["a"] == ref else f"← {r['relation']}"
                out.append((v, rel, 10 + r["n"], r["doc"]))
            for r in self.db.execute(
                    "SELECT CASE WHEN a=? THEN b ELSE a END AS v, poids FROM liens WHERE a=? OR b=? "
                    "ORDER BY poids DESC LIMIT ?", (ref, ref, ref, limite // 2)):
                if r["v"] not in lus:
                    out.append((r["v"], "cités ensemble", r["poids"]))
            for r in self.db.execute(
                    "SELECT d.id, d.type FROM mentions m JOIN documents d ON d.id=m.document WHERE m.entite=? "
                    "ORDER BY d.type='tableau' DESC, d.type='oeuvre' DESC, COALESCE(d.importance, 2) DESC, d.date "
                    "LIMIT ?", (ref, limite // 2)):
                out.append((r["id"], "le cite" if r["type"] != "tableau" else "le représente", 2))
        noeuds = {n["ref"]: n for n in self.noeuds([o[0] for o in out])}
        return [{**noeuds[o[0]], "relation": o[1], "force": o[2], **({"source": o[3]} if len(o) > 3 else {})}
                for o in out if o[0] in noeuds]

    # ── Le jeu : ce qu'il y a à débloquer ─────────────────────────────────────
    def totaux(self) -> dict:
        """Ce qu'il y a à découvrir, par catégorie : les entités citées dans au moins MIN_COLLECTION documents (les
        autres sont des mentions isolées), tous les documents, et les liens (lus dans les lettres et cités ensemble)."""
        if not self.ok:
            return {}
        if getattr(self, "_totaux", None):
            return self._totaux
        out = {r[0]: r[1] for r in self.db.execute(
            "SELECT type, COUNT(*) FROM entites WHERE poids >= ? GROUP BY type", (MIN_COLLECTION,))}
        out.update({r[0]: r[1] for r in self.db.execute("SELECT type, COUNT(*) FROM documents GROUP BY type")})
        paires = self.db.execute(
            "SELECT COUNT(*) FROM (SELECT a, b FROM liens UNION SELECT MIN(a, b), MAX(a, b) FROM relations)").fetchone()[0]
        out["lien"] = paires
        self._totaux = out
        return out

    def episodes_de(self, refs: list[str]) -> list[str]:
        """Épisodes des documents donnés (« episode:wagram ») : débloqués avec eux."""
        refs = [r for r in refs if r.split(":")[0] in ("lettre", "oeuvre", "tableau")]
        if not self.ok or not refs:
            return []
        q = ",".join("?" * len(refs))
        return [f"episode:{r[0]}" for r in self.db.execute(
            f"SELECT DISTINCT episode FROM documents WHERE id IN ({q}) AND episode IS NOT NULL", refs)]

    def debloquer(self, vus: list[str], tour: list[str]) -> list[dict]:
        """Liens débloqués : leurs deux entités sont débloquées, et elles ont été rencontrées ensemble — dans la même
        réponse (`tour`) ou dans un document que le visiteur a vu."""
        if not self.ok:
            return []
        ents = [v for v in dict.fromkeys(vus) if ":" not in v][:800]
        if len(ents) < 2:
            return []
        q = ",".join("?" * len(ents))
        cand = {}
        for r in self.db.execute(f"SELECT a, b, poids FROM liens WHERE a IN ({q}) AND b IN ({q})", ents + ents):
            cand[(r["a"], r["b"])] = {"de": r["a"], "vers": r["b"], "relation": "cités ensemble", "force": r["poids"]}
        for r in self.db.execute(f"SELECT a, b, relation, document FROM relations WHERE a IN ({q}) AND b IN ({q})",
                                 ents + ents):
            k = tuple(sorted((r["a"], r["b"])))
            cand[k] = {"de": r["a"], "vers": r["b"], "relation": r["relation"], "force": 10, "source": r["document"]}
        if not cand:
            return []
        tour_s = set(tour)
        docs_vus = [v for v in vus if v.split(":")[0] in ("lettre", "oeuvre", "tableau")]
        ensemble = set()
        if docs_vus:
            qd = ",".join("?" * len(docs_vus))
            par_doc = defaultdict(set)
            for r in self.db.execute(f"SELECT entite, document FROM mentions WHERE document IN ({qd}) "
                                     f"AND entite IN ({q})", docs_vus + ents):
                par_doc[r["document"]].add(r["entite"])
            for es in par_doc.values():
                for a in es:
                    for b in es:
                        if a < b:
                            ensemble.add((a, b))
        out = []
        for (a, b), l in cand.items():
            k = tuple(sorted((a, b)))
            if (a in tour_s and b in tour_s) or k in ensemble or (l.get("source") in set(docs_vus)):
                out.append(l)
        return out

    def sous_graphe(self, vus: list[str], decouvrir: int = 3) -> dict:
        """Les nœuds vus par le visiteur, les liens entre eux, et pour chacun quelques voisins « à découvrir »."""
        if not self.ok:
            return {"noeuds": [], "liens": []}
        vus = [v for v in dict.fromkeys(vus)][:400]
        connus = set(vus)
        liens, extra = [], {}
        for v in vus:
            for k, n in enumerate(self.voisins(v, limite=16)):
                if n["ref"] in connus:
                    liens.append({"de": v, "vers": n["ref"], "relation": n["relation"], "force": n["force"]})
                elif k < 16 and len([1 for x in extra.values() if x["depuis"] == v]) < decouvrir:
                    extra.setdefault(n["ref"], {**n, "depuis": v, "decouvrir": True})
                    liens.append({"de": v, "vers": n["ref"], "relation": n["relation"], "force": n["force"]})
        vus_l = set()
        dedup = []
        for l in liens:
            k = tuple(sorted((l["de"], l["vers"])))
            if k not in vus_l:
                vus_l.add(k)
                dedup.append(l)
        return {"noeuds": self.noeuds(vus) + list(extra.values()), "liens": dedup}
