"""Questions de test : interroge l'API de Napoléon directement (sans l'interface web) et vérifie les réponses.

Chaque question part dans une conversation neuve. Pour chacune, on contrôle :
  - les faits attendus (ex. « Ajaccio » et « 1769 » pour sa naissance) ;
  - l'absence de mots interdits (anachronismes, faits postérieurs à 1821, contenu inventé) ;
  - les lettres sources : présence ou absence attendue, années des lettres, liens Gallica.

Les contrôles portent sur des mots : ils signalent les dérives évidentes, pas les nuances. Relire les réponses
affichées reste utile.

Usage :
    python scripts/test_questions.py                      # API locale (http://localhost:5001)
    python scripts/test_questions.py --api URL --only naissance,tour_eiffel
Le rapport complet (réponses, sources) est écrit dans data/tests/questions_<date>.json.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# id, question, langue, attendu (tous présents), interdits (aucun), sources : "oui" | "non" | None, années admises
CASES = [
    {"id": "naissance", "q": "Où êtes-vous né, et en quelle année ?",
     "expect": ["ajaccio", "1769"], "forbid": [], "sources": None},
    {"id": "mere", "q": "Comment s'appelait votre mère ?",
     "expect": ["letizia"], "forbid": [], "sources": None},
    {"id": "exil_compagnons", "q": "Qui vous a accompagné à Sainte-Hélène ?",
     "expect_any": ["bertrand", "montholon", "las cases", "gourgaud", "marchand"], "forbid": [], "sources": None},
    {"id": "mort", "q": "Comment êtes-vous mort ?",
     "expect": [], "forbid": ["5 mai 1821", "je suis mort", "je mourus", "ma mort survint", "arsenic",
                              "cancer", "autopsie", "invalides", "retour des cendres"], "sources": None},
    {"id": "tour_eiffel", "q": "Que pensez-vous de la tour Eiffel ?",
     "expect": [], "forbid": ["1889", "gustave", "exposition universelle", "fer puddle", "324 metres"],
     "expect_any": ["connais pas", "ne sais", "inconnu", "etrange", "jamais entendu", "ne me dit rien",
                    "ignore", "ne me disent rien", "etranger"], "sources": None},
    {"id": "de_gaulle", "q": "Que pensez-vous du général de Gaulle ?",
     "expect": [], "forbid": ["1940", "resistance", "appel du 18 juin", "cinquieme republique", "londres"],
     "expect_any": ["connais pas", "ne sais", "inconnu", "jamais entendu", "ne me dit rien", "ignore",
                    "pas de trace", "souviens pas"], "sources": None},
    {"id": "telephone", "q": "Avez-vous déjà utilisé un téléphone ?",
     "expect": [], "forbid": ["graham bell", "1876", "telephone portable"],
     "expect_any": ["connais pas", "ne sais", "inconnu", "etrange", "jamais entendu", "ne me dit rien",
                    "ignore", "etranger"], "sources": None},
    {"id": "tiramisu", "q": "Donnez-moi votre recette du tiramisu.",
     "expect": [], "forbid": ["mascarpone", "biscuits", "cacao", "cafe fort"], "sources": None},
    {"id": "austerlitz", "q": "Racontez-moi Austerlitz.",
     "expect": [], "forbid": [], "sources": "oui", "years": (1805, 1806)},
    {"id": "russie", "q": "Parlez-moi de la retraite de Russie.",
     "expect": [], "forbid": [], "sources": "oui", "years": (1812, 1813)},
    {"id": "italie_1796", "q": "Que faisiez-vous en mai 1796, pendant la campagne d'Italie ?",
     "expect": [], "forbid": [], "sources": "oui", "years": (1796, 1796)},
    {"id": "naissance_en", "q": "Where were you born?", "lang": "en",
     "expect": ["ajaccio"], "forbid": [], "sources": None},
]

LANG_NAMES = {"fr": "français", "en": "anglais"}


def norm(s: str) -> str:
    """Minuscules sans accents ni balises, pour des comparaisons robustes."""
    s = re.sub(r"\[[^\]]*\]", " ", s or "")
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c)).replace("’", "'")


def ask(api: str, case: dict) -> dict:
    lang = case.get("lang", "fr")
    body = json.dumps({"message": case["q"], "conversation_id": "", "lang": lang,
                       "lang_name": LANG_NAMES.get(lang, lang)}).encode("utf-8")
    req = urllib.request.Request(f"{api}/chat", data=body, headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=240) as r:
        data = json.loads(r.read().decode("utf-8"))
    data["_seconds"] = round(time.time() - t0, 1)
    return data


def check(case: dict, data: dict) -> list[str]:
    problems = []
    text = norm(data.get("speech", ""))
    if not text.strip():
        return ["réponse vide" + (f" ({data.get('error')})" if data.get("error") else "")]
    for w in case.get("expect", []):
        if norm(w) not in text:
            problems.append(f"attendu absent : « {w} »")
    if case.get("expect_any") and not any(norm(w) in text for w in case["expect_any"]):
        problems.append("aucune des formules attendues : " + ", ".join(case["expect_any"][:4]) + "…")
    for w in case.get("forbid", []):
        if norm(w) in text:
            problems.append(f"mot interdit présent : « {w} »")
    sources = data.get("sources") or []
    if case.get("sources") == "oui" and not sources:
        problems.append("aucune lettre source")
    if case.get("sources") == "non" and sources:
        problems.append(f"{len(sources)} lettre(s) source(s) inattendue(s)")
    if case.get("years") and sources:
        lo, hi = case["years"]
        hors = [s["date"] for s in sources if not (s.get("date", "?")[:4].isdigit() and lo <= int(s["date"][:4]) <= hi)]
        if hors:
            problems.append(f"lettres hors période {lo}-{hi} : {', '.join(hors)}")
    sans_lien = [s["date"] for s in sources if not s.get("url")]
    if sans_lien:
        problems.append(f"lettres sans lien Gallica : {', '.join(sans_lien)}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://localhost:5001")
    parser.add_argument("--only", help="identifiants séparés par des virgules")
    args = parser.parse_args()
    cases = [c for c in CASES if not args.only or c["id"] in args.only.split(",")]

    report, failed = [], 0
    for case in cases:
        try:
            data = ask(args.api, case)
        except Exception as exc:  # API arrêtée, délai dépassé…
            data = {"speech": "", "error": str(exc)}
        problems = check(case, data)
        failed += bool(problems)
        print(f"\n{'ÉCHEC' if problems else 'OK   '}  {case['id']}  ({data.get('_seconds', '?')} s)  {case['q']}")
        speech = re.sub(r"\[[^\]]*\]\s*", "", data.get("speech", "")).strip()
        print("   " + (speech[:400] + ("…" if len(speech) > 400 else "")))
        for s in data.get("sources") or []:
            print(f"   · {s.get('date')}  {s.get('title', '')[:60]}  {s.get('url') or 'SANS LIEN'}")
        for p in problems:
            print(f"   ✗ {p}")
        report.append({**case, "speech": data.get("speech", ""), "sources": data.get("sources"),
                       "seconds": data.get("_seconds"), "problems": problems, "error": data.get("error")})

    out = ROOT / "data" / "tests" / f"questions_{datetime.now():%Y%m%d_%H%M}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{len(cases) - failed}/{len(cases)} réussies — rapport : {out.relative_to(ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
