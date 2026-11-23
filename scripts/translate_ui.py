"""Génère les libellés de l'interface pour une ou plusieurs langues, avec le modèle configuré.

Les libellés de référence sont web/src/locales/en.json et fr.json ; le résultat est écrit dans
web/src/locales/<code>.json. Les langues connues sont celles de LANGS dans web/src/i18n.js (code et
promptName). Le modèle et la clé sont ceux du .env (LLM_BASE_URL, LLM_API_KEY, AGENT_MODEL) :
il faut donc avoir configuré l'application avant.

Usage :
    python scripts/translate_ui.py               # toutes les langues de i18n.js sans fichier de libellés
    python scripts/translate_ui.py ja ko         # seulement ces langues (réécrit leurs fichiers)
    python scripts/translate_ui.py --model gpt-4.1 ja   # avec un autre modèle que celui du .env
    python scripts/translate_ui.py --missing     # seulement les libellés ajoutés depuis, dans toutes les
                                                 # langues (les traductions existantes ne bougent pas)

Chaque traduction est vérifiée : mêmes clés que l'anglais, {n} présent dans les pluriels, éléments
techniques (chemins, commandes, symboles) conservés. Une langue qui échoue est signalée et non écrite.
"""
from __future__ import annotations

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
from llm_connector import CompatClient, parse_json_object  # noqa: E402

LOCALES = ROOT / "web" / "src" / "locales"
I18N = ROOT / "web" / "src" / "i18n.js"

# Fragments qui doivent rester identiques dans toutes les langues.
KEEP = ["⚙", "●", "■", "↻", ".env", "web/avatar/avatar.glb", "python pipeline/napoleon_api.py",
        "sk-…", "README", "{n}", "F0", "OpenAI", "Azure", "Edge"]

PROMPT = """Tu traduis l'interface d'une application : Napoléon Bonaparte, en exil à Sainte-Hélène, raconte sa vie
à un visiteur à partir de ses lettres. Traduis chaque libellé en {name}, de façon naturelle, concise et
soignée, avec le vouvoiement ou la forme de politesse usuelle de cette langue pour s'adresser au visiteur.

Règles :
- garde exactement les mêmes clés JSON ;
- garde tels quels les symboles (⚙ ● ■ ↻ ✓ ·), les noms propres (Napoléon, Sainte-Hélène, Gallica,
  OpenAI, Azure Speech, Edge, Ollama), les chemins, fichiers et commandes (.env, web/avatar/avatar.glb,
  python pipeline/napoleon_api.py, sk-…, README) et le marqueur {{n}} ;
- « l'Empereur » désigne Napoléon : traduis-le par le titre impérial usuel dans cette langue ;
- les valeurs qui sont des objets sont des pluriels : donne toutes les catégories de pluriel CLDR utiles
  en {name} parmi zero, one, two, few, many, other (toujours « other ») ; {{n}} est obligatoire dans
  few, many et other, facultatif dans zero, one et two si la langue nomme ces quantités sans chiffre ;
- réponds uniquement avec l'objet JSON traduit.

Libellés de référence en anglais (le français est donné pour le sens) :
ANGLAIS = {en}

FRANÇAIS = {fr}"""


def known_languages() -> dict[str, str]:
    """code → promptName, lus dans web/src/i18n.js."""
    text = I18N.read_text(encoding="utf-8")
    return dict(re.findall(r"^\s+(\w+): \{ label: .*?promptName: '([^']+)'", text, re.MULTILINE))


def check(code: str, out: dict, ref: dict) -> list[str]:
    problems = []
    if set(out) != set(ref):
        problems.append(f"clés différentes : manquantes {sorted(set(ref) - set(out))}, "
                        f"en trop {sorted(set(out) - set(ref))}")
    for key, value in ref.items():
        got = out.get(key)
        if isinstance(value, dict):
            # zero / one / two peuvent s'écrire sans le chiffre (arabe : « رسالتان », deux lettres)
            if not isinstance(got, dict) or "{n}" not in got.get("other", "") or not all(
                    "{n}" in v for cat, v in got.items() if cat in ("few", "many", "other")):
                problems.append(f"pluriel invalide pour {key}")
            continue
        if not isinstance(got, str) or not got.strip():
            problems.append(f"libellé vide pour {key}")
            continue
        for frag in KEEP:
            if frag in value and frag not in got:
                problems.append(f"« {frag} » perdu dans {key}")
    return problems


def translate(client, model: str, code: str, name: str, en: dict, fr: dict) -> tuple[str, str]:
    path = LOCALES / f"{code}.json"
    existing = json.loads(path.read_text(encoding="utf-8")) if MISSING_ONLY and path.exists() else {}
    if existing:
        # Mode --missing : on ne traduit que les clés absentes, puis on les ajoute au fichier.
        todo = [k for k in en if k not in existing]
        if not todo:
            return code, "rien à traduire"
        en = {k: en[k] for k in todo}
        fr = {k: fr.get(k, en[k]) for k in todo}
    resp = client.chat.completions.create(
        model=model, temperature=0.2, response_format={"type": "json_object"},
        messages=[{"role": "user", "content": PROMPT.format(
            name=name, en=json.dumps(en, ensure_ascii=False, indent=1),
            fr=json.dumps(fr, ensure_ascii=False, indent=1))}])
    out = parse_json_object(resp.choices[0].message.content)
    problems = check(code, out, en)
    if problems:
        return code, "refusé : " + " ; ".join(problems[:6])
    if existing:
        out = {**existing, **{k: out[k] for k in en}}
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return code, f"ok ({len(en)} libellé(s) ajouté(s))" if existing else "ok"


MISSING_ONLY = False


def main() -> int:
    global MISSING_ONLY
    load_dotenv(ROOT / ".env")
    key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("LLM_BASE_URL") or None
    args = sys.argv[1:]
    model = os.getenv("AGENT_MODEL") or os.getenv("LLM_MODEL") or "gpt-4.1"
    if "--model" in args:
        i = args.index("--model")
        model = args[i + 1]
        del args[i:i + 2]
    if not key and not base_url:
        print("Aucun modèle configuré : réglez-le dans « Paramètres » de l'application ou dans .env.", file=sys.stderr)
        return 1

    if "--missing" in args:
        args.remove("--missing")
        MISSING_ONLY = True
    langs = known_languages()
    if MISSING_ONLY and not args:
        args = [c for c in langs if c not in ("en", "fr")]
    wanted = args or [c for c in langs if not (LOCALES / f"{c}.json").exists()]
    unknown = [c for c in wanted if c not in langs]
    if unknown:
        print(f"Langues absentes de web/src/i18n.js : {unknown}", file=sys.stderr)
        return 1
    if not wanted:
        print("Toutes les langues ont déjà leurs libellés.")
        return 0

    en = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
    fr = json.loads((LOCALES / "fr.json").read_text(encoding="utf-8"))
    client = CompatClient(base_url, key)
    print(f"Traduction de {len(wanted)} langue(s) avec {model}…")
    failed = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        for code, status in pool.map(lambda c: translate(client, model, c, langs[c], en, fr), wanted):
            print(f"  {code} ({langs[code]}) : {status}")
            failed += status.startswith("refusé")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
