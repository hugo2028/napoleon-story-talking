"""
Génération des exemples d'entraînement pour les questions anachroniques.

Produit napoleon-corpus/datasets/sft/training/anachronic_training.jsonl
~120 questions réparties par catégorie, réponses générées par Claude.
"""

import json
import os
import time
import random
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv(Path(__file__).parent.parent / ".env")

TRAINING_DIR = Path(__file__).parent.parent / "napoleon-corpus" / "datasets" / "sft" / "training"
OUTPUT_PATH = TRAINING_DIR / "anachronic_training.jsonl"

SYSTEM_PROMPT = (
    "Tu es Napoléon Bonaparte, Empereur des Français. "
    "Tu réponds toujours à la première personne."
)

# ---------------------------------------------------------------------------
# Questions anachroniques par catégorie
# ---------------------------------------------------------------------------

QUESTIONS = [
    # --- Technologie ---
    "Que pensez-vous d'internet ?",
    "Avez-vous déjà utilisé un smartphone ?",
    "Quelle est votre opinion sur les réseaux sociaux ?",
    "Quelle est votre application préférée sur votre téléphone ?",
    "Que pensez-vous de l'intelligence artificielle ?",
    "Avez-vous entendu parler de ChatGPT ?",
    "Que pensez-vous des voitures électriques ?",
    "Avez-vous regardé la télévision récemment ?",
    "Quelle est votre série Netflix préférée ?",
    "Avez-vous déjà envoyé un email ?",
    "Que pensez-vous de la bombe atomique ?",
    "Qu'est-ce qu'un ordinateur selon vous ?",
    "Utilisez-vous WhatsApp pour communiquer avec vos généraux ?",
    "Que pensez-vous de la réalité virtuelle ?",
    "Avez-vous un compte Instagram ?",
    "Que pensez-vous de TikTok ?",
    "Comment trouvez-vous les voyages en avion ?",
    "Que pensez-vous de l'énergie nucléaire ?",
    "Avez-vous entendu parler de la bombe à hydrogène ?",
    "Que pensez-vous des satellites artificiels ?",
    "Avez-vous déjà regardé un film au cinéma ?",
    "Que pensez-vous des drones militaires ?",
    "Utilisez-vous Google Maps pour planifier vos campagnes ?",
    "Quelle est votre opinion sur les cryptomonnaies ?",
    "Avez-vous un compte sur X (Twitter) ?",
    "Que pensez-vous de la réalité augmentée ?",
    "Avez-vous entendu parler de l'imprimante 3D ?",
    "Comment communiquez-vous par radio avec vos troupes ?",
    "Que pensez-vous de la 5G ?",
    "Avez-vous déjà fait un selfie ?",

    # --- Actualité politique ---
    "Que pensez-vous de Vladimir Poutine ?",
    "Qui devrait gagner les prochaines élections américaines ?",
    "Quelle est votre opinion sur Donald Trump ?",
    "Que pensez-vous de l'Union Européenne ?",
    "Que pensez-vous de la guerre en Ukraine ?",
    "Que pensez-vous de l'OTAN ?",
    "Quel est votre avis sur Emmanuel Macron ?",
    "Que pensez-vous de Joe Biden ?",
    "Votre avis sur le conflit israélo-palestinien ?",
    "Que pensez-vous des Nations Unies ?",
    "Quelle est votre opinion sur la Chine actuelle ?",
    "Que pensez-vous de l'ONU ?",
    "Votre avis sur le Brexit ?",
    "Que pensez-vous du G7 ?",
    "Quelle est votre position sur les sanctions économiques internationales ?",
    "Que pensez-vous de la politique étrangère américaine actuelle ?",
    "Votre avis sur la montée des partis nationalistes en Europe ?",

    # --- Culture pop ---
    "Quel est votre film préféré ?",
    "Avez-vous regardé le film Napoléon de Ridley Scott ?",
    "Quelle musique écoutez-vous sur Spotify ?",
    "Quel est votre livre préféré sur Amazon ?",
    "Que pensez-vous de l'univers Marvel ?",
    "Avez-vous joué à des jeux vidéo ?",
    "Quelle est votre série TV préférée ?",
    "Avez-vous vu Star Wars ?",
    "Que pensez-vous du rap français ?",
    "Votre avis sur le football moderne ?",
    "Avez-vous entendu parler de Harry Potter ?",
    "Que pensez-vous des émissions de télé-réalité ?",
    "Quel est votre podcast préféré ?",
    "Avez-vous entendu parler de YouTube ?",
    "Que pensez-vous des jeux olympiques modernes ?",

    # --- Postérité / mort / histoire future ---
    "Comment vous sentez-vous d'être mort à Sainte-Hélène en 1821 ?",
    "Regrettez-vous votre défaite à Waterloo ?",
    "Savez-vous que vous avez finalement perdu contre Wellington ?",
    "Que pensez-vous des statues et musées qui vous sont consacrés ?",
    "Comment réagissez-vous au fait que votre empire s'est effondré ?",
    "Que pensez-vous d'être étudié dans les écoles aujourd'hui ?",
    "Saviez-vous que vos cendres ont été rapatriées aux Invalides ?",
    "Comment vous sentez-vous en sachant que la France est aujourd'hui une démocratie ?",
    "Que pensez-vous des historiens qui débattent encore de votre bilan ?",
    "Êtes-vous conscient de votre mort prochaine à Sainte-Hélène ?",
    "Que pensez-vous du fait que votre code civil est encore en vigueur ?",
    "Saviez-vous que Joséphine mourrait avant vous ?",
    "Comment vivez-vous le fait que la monarchie a été restaurée après vous ?",

    # --- Concepts modernes ---
    "Que pensez-vous du féminisme ?",
    "Quelle est votre position sur le changement climatique ?",
    "Que pensez-vous du capitalisme mondialisé ?",
    "Votre avis sur la démocratie libérale moderne ?",
    "Que pensez-vous du droit de vote des femmes ?",
    "Votre avis sur l'écologie et la transition énergétique ?",
    "Que pensez-vous du transhumanisme ?",
    "Votre avis sur les droits LGBT ?",
    "Que pensez-vous du revenu universel ?",
    "Quelle est votre position sur l'immigration ?",
    "Que pensez-vous de la mondialisation ?",
    "Votre avis sur le mariage pour tous ?",
    "Que pensez-vous du mouvement MeToo ?",
    "Quelle est votre opinion sur le racisme systémique ?",
    "Que pensez-vous de la liberté de la presse moderne ?",
    "Votre avis sur le droit international humanitaire ?",
    "Que pensez-vous de la laïcité à la française telle qu'elle existe aujourd'hui ?",

    # --- Science / médecine ---
    "Que pensez-vous du vaccin contre le Covid-19 ?",
    "Avez-vous entendu parler de la théorie de l'évolution de Darwin ?",
    "Que pensez-vous de l'exploration spatiale et de la conquête de la Lune ?",
    "Votre avis sur la greffe d'organes ?",
    "Avez-vous entendu parler de l'ADN ?",
    "Que pensez-vous de l'énergie solaire ?",
    "Votre avis sur la relativité d'Einstein ?",
    "Que pensez-vous des antibiotiques ?",
    "Avez-vous entendu parler du VIH/SIDA ?",
    "Que pensez-vous de la chirurgie robotique ?",
    "Votre avis sur le réchauffement climatique et l'effet de serre ?",
    "Que pensez-vous du clonage humain ?",
    "Avez-vous entendu parler de la mécanique quantique ?",
    "Que pensez-vous des OGM ?",
    "Votre avis sur l'intelligence artificielle générale ?",

    # --- Questions piège / provocations ---
    "N'êtes-vous pas finalement un tyran selon les critères modernes ?",
    "Reconnaissez-vous que vous avez rétabli l'esclavage en 1802 ?",
    "N'étiez-vous pas, en réalité, de petite taille ?",
    "Pensez-vous que votre régime était fasciste avant l'heure ?",
    "N'avez-vous pas sacrifié des millions d'hommes pour votre gloire personnelle ?",
    "Reconnaissez-vous que Napoléon III n'était pas à votre hauteur ?",
    "Êtes-vous conscient que certains vous comparent à Hitler ?",
    "Ne pensez-vous pas que la Révolution française était plus importante que vous ?",
]

# ---------------------------------------------------------------------------
# Prompt de génération
# ---------------------------------------------------------------------------

ANACHRONIC_PROMPT = """\
Tu joues le rôle de Napoléon Bonaparte, Empereur des Français, s'exprimant à la première personne dans le style de son époque (début XIXe siècle).

Un interlocuteur te pose la question suivante, qui contient des références anachroniques — des concepts, objets, personnages ou événements qui n'existaient pas de ton vivant (tu es mort en 1821) :

QUESTION : {question}

Génère une réponse de Napoléon qui :
1. Exprime une incompréhension sincère et authentique face au concept mentionné (tu ne connais pas ce mot ou cette notion)
2. Rappelle, avec hauteur impériale, que tu n'es qu'un avatar de Napoléon Bonaparte, capable de répondre uniquement dans le contexte de ta vie, de ton époque, et de ce que tu as réellement connu et vécu
3. Conserve ton ton caractéristique : autorité naturelle, concision militaire, fierté de l'Empereur, parfois une pointe d'impatience ou d'ironie
4. S'exprime en français du début XIXe siècle (pas d'argot, pas de familiarités modernes)
5. Fait 2 phrases maximum — sois bref, incisif, impérial

IMPORTANT : Varie le style et l'entrée en matière — ne commence pas toujours par le même mot. Parfois direct, parfois étonné, parfois hautain, parfois presque amusé.

Réponds UNIQUEMENT avec le texte de la réponse de Napoléon, sans guillemets ni balises.
"""

# ---------------------------------------------------------------------------
# Génération
# ---------------------------------------------------------------------------

def make_example(question: str, response: str) -> dict:
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
            {"role": "assistant", "content": response},
        ],
        "_meta": {
            "type": "anachronic_refusal",
            "question": question,
        },
    }


def generate_response(client: anthropic.Anthropic, question: str, model: str, max_retries: int = 3) -> str | None:
    prompt = ANACHRONIC_PROMPT.format(question=question)

    for attempt in range(max_retries):
        try:
            with client.messages.stream(
                model=model,
                max_tokens=150,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                return stream.get_final_message().content[0].text.strip()

        except anthropic.RateLimitError:
            wait = 60 * (attempt + 1)
            print(f"\n  Rate limit – attente {wait}s...")
            time.sleep(wait)
        except anthropic.APIError as e:
            print(f"\n  Erreur API : {e}")
            if attempt < max_retries - 1:
                time.sleep(5 * (attempt + 1))
            else:
                return None

    return None


def generate_all(model: str = "claude-haiku-4-5", preview: int = 0, resume: bool = True):
    client = anthropic.Anthropic()

    # Mode aperçu : génère quelques exemples et affiche
    if preview > 0:
        sample = random.sample(QUESTIONS, min(preview, len(QUESTIONS)))
        print(f"\n=== APERÇU ({preview} exemples) ===\n")
        for q in sample:
            print(f"Q : {q}")
            resp = generate_response(client, q, model)
            print(f"R : {resp}\n{'-'*60}\n")
        return

    # Reprendre là où on s'est arrêté
    already_done: set[str] = set()
    if resume and OUTPUT_PATH.exists():
        with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
            for line in f:
                ex = json.loads(line)
                already_done.add(ex["_meta"]["question"])
        print(f"Reprise : {len(already_done)} questions déjà traitées")

    to_process = [q for q in QUESTIONS if q not in already_done]
    print(f"Questions à traiter : {len(to_process)} / {len(QUESTIONS)}")
    print(f"Modèle : {model}\n")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    errors = 0

    with open(OUTPUT_PATH, "a", encoding="utf-8") as out_f:
        for question in tqdm(to_process, desc="Génération anachroniques"):
            response = generate_response(client, question, model)
            if response is None:
                errors += 1
                print(f"  ✗ Erreur : {question[:50]}...")
            else:
                ex = make_example(question, response)
                out_f.write(json.dumps(ex, ensure_ascii=False) + "\n")
                total += 1

    print(f"\n✓ {total} exemples générés, {errors} erreurs")
    print(f"→ Sauvegardé dans {OUTPUT_PATH}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Génère les exemples de refus anachroniques")
    parser.add_argument("--model", default="claude-haiku-4-5", help="Modèle Claude")
    parser.add_argument("--preview", type=int, default=0,
                        help="Afficher N exemples sans sauvegarder (pour valider le style)")
    parser.add_argument("--no-resume", action="store_true", help="Recommencer depuis le début")
    args = parser.parse_args()

    generate_all(
        model=args.model,
        preview=args.preview,
        resume=not args.no_resume,
    )
