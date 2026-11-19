# Napoléon — l'Empereur raconte sa vie, lettre après lettre

Un avatar conversationnel de Napoléon Bonaparte, exilé à Sainte-Hélène, qui répond à vos questions
en s'appuyant **uniquement sur sa correspondance réelle** : chaque réponse est construite à partir de
lettres authentiques, citées mot pour mot et reliées à leur source sur Gallica (BnF).

*A conversational Napoleon avatar grounded in his actual letters. Every answer is built from authentic
correspondence, quoted verbatim and linked to its Gallica (BnF) source. Available in French, English,
Spanish, Italian, German and Portuguese.*

## Démo

**Premier échange** — Napoléon accueille le visiteur sur son île et ouvre la conversation sur une lettre
tirée au hasard : celle du 27 janvier 1812 à son frère, roi de Westphalie.

https://github.com/user-attachments/assets/b3e7795e-da2e-4289-b31b-4a6c19584048

**In English** — the conversation opens on a letter drawn at random (20 February 1799, to the commander
of the fort of El-Arish) and follows it into the capture of El-Arish and the march on Jaffa, with the
episode, chapter and letters shown on screen and the Gallica sources attached to each answer.

https://github.com/user-attachments/assets/9c04a932-a738-41c5-9ea5-bf15ac72cdc3

## La démarche

Le projet est parti d'une question simple : peut-on faire parler Napoléon **sans lui prêter un seul mot
qu'il n'a pas écrit** ? Il est passé par trois étapes.

**1. Constituer le corpus.** Les écrits de Napoléon ont été extraits des éditions numérisées par Gallica,
avec un extracteur par type de document : les 32 tomes de la *Correspondance*, les bulletins de la
Grande Armée, les proclamations, les lettres à Joséphine, les écrits de jeunesse, les récits de campagne
et des mémoires. Chaque lettre devient une unité, avec sa date (y compris les dates du calendrier
républicain), son lieu et son destinataire : **52 000 passages, 7,9 millions de mots**. Un nettoyage par
LLM, volontairement conservateur, corrige les erreurs d'OCR et rejette les passages inexploitables ; les
lettres dont la date entre en conflit avec leur contenu sont reprises ou écartées.

**2. Essayer le fine-tuning, et en mesurer les limites.** Un Mistral-7B a été affiné (QLoRA), d'abord par
pré-entraînement continu sur le corpus, puis par instruction, avec des exemples où Napoléon refuse les
anachronismes. Le modèle prend bien la voix de l'Empereur, mais les évaluations
(`eval_results.md`, `eval_base_results.md`, `compare_pretrain_results.md`) montrent qu'**une voix n'est
pas une source** : sans affinage, le modèle de base attribue le Code civil à Jean-Jacques Rousseau ;
affiné, il répond avec style mais sans pouvoir dire d'où vient ce qu'il affirme.

**3. Faire parler les archives elles-mêmes.** D'où le choix final : un RAG sur les lettres, dont chaque
passage est daté, classé (lettre, ordre, bulletin, proclamation, rapport d'un tiers) et marqué selon la
fiabilité de sa date, et un **agent** qui enquête dans ces archives avant que Napoléon ne prenne la parole.

## Une approche nouvelle

- **L'enquête et la parole sont séparées.** Un *archiviste* autonome (agent à outils, `gpt-4.1`) cherche,
  lit et choisit les lettres : recherche sémantique, recherche par mots exacts, exploration d'une
  période, mémoires. Un *narrateur* (`gpt-4.1-mini`) ne fait que raconter ce qu'on lui sert. Il ne peut
  rien affirmer que les lettres ne disent pas.
- **Aucune citation inventée.** Les phrases citées sont choisies par un appel dédié, puis retrouvées
  par algorithme dans le texte de la lettre et restituées à l'identique. Une citation introuvable est
  rejetée.
- **Un récit à embranchements, unique à chaque fois.** L'archiviste construit un plan en *moments*, chacun
  avec deux variantes, par exemple deux lettres ou deux regards sur le même passage. Le visiteur choisit
  et l'autre chemin est abandonné : deux conversations sur Austerlitz ne se ressemblent pas.
- **Le hasard des archives comme porte d'entrée.** Plutôt qu'un menu de grands épisodes, la conversation
  s'ouvre sur une lettre tirée au sort, comme si Napoléon venait de la relire. Le hasard peut rouvrir la
  voie quand le visiteur veut « autre chose ».
- **Le jugement laissé à l'agent, pas des règles en dur.** Le choix des lettres, des citations et du moment
  où tirer au hasard relève de l'agent, guidé par des consignes plutôt que par des seuils. Le code ne
  vérifie que ce qui est vérifiable : l'exactitude des citations et la cohérence des lettres avec le plan.
- **Une transparence complète.** Chaque réplique est accompagnée de ses lettres et d'un lien vers la page
  de l'édition sur Gallica. À l'écran, l'épisode, la période, le chapitre et les lettres racontées
  suivent le récit.
- **Une présence incarnée, dans six langues.** Napoléon parle depuis Sainte-Hélène, revit ses lettres au
  présent et choisit ses gestes. La voix Azure pilote la synchronisation labiale (visèmes). Le corpus
  reste en français, et la conversation se tient en français, anglais, espagnol, italien, allemand ou
  portugais.

## Architecture

```
web/            Interface (Vite) + relais Node/Express (port 3002) — voix Azure, avatar three.js
pipeline/       API Flask (port 5001), archiviste, narrateur, et scripts de construction du corpus/RAG
data/rag/       Bases SQLite du RAG (lettres + mémoires, avec embeddings) — via Git LFS
finetune/       Expériences de fine-tuning (optionnel)
```

## Installation

Prérequis : Python 3.11+, Node.js 18+, [Git LFS](https://git-lfs.com), une clé OpenAI et une ressource
Azure Speech.

```bash
git lfs install
git clone https://github.com/hugo2028/napoleon-story-talking.git
cd napoleon-story-talking

pip install -r requirements.txt
cd web && npm install && cd ..

cp .env.example .env    # puis renseignez LLM_API_KEY, AZURE_SPEECH_KEY, AZURE_SPEECH_REGION
```

Lancement, dans deux terminaux :

```bash
python pipeline/napoleon_api.py
cd web && npm run dev
```

Puis ouvrez <http://localhost:5174>.

## L'avatar 3D

**Le modèle 3D de Napoléon utilisé dans les vidéos n'est pas distribué** (modèle sous licence, non
redistribuable). Sans modèle, l'application affiche un médaillon 2D animé et tout le reste fonctionne :
voix, récit, sources, langues.

Pour utiliser votre propre avatar, déposez un fichier `web/avatar/avatar.glb` qui contient :

- un squelette aux noms d'os **Mixamo** (`mixamorig:Head`, `mixamorig:Neck`…) ;
- des **shape keys** `viseme_00` à `viseme_21` (un par identifiant de visème Azure) et les shape keys
  ARKit `eyeBlinkLeft`, `eyeBlinkRight`, `eyesClosed`, `eyesLookUp`, `eyesLookDown`, `mouthSmileLeft`, `mouthSmileRight` ;
- des animations nommées : `idle_weight_shift` (repos), `talk_speaking_with_gestures` (parole) et,
  au choix, des gestes (`head_nod_yes`, `head_shake_no`, `gesture_look_away`…). Les noms trouvés dans
  le fichier sont proposés automatiquement au modèle de langage.

## Sources des données

Tous les textes viennent d'éditions du XIXᵉ siècle, dans le domaine public, numérisées par la
Bibliothèque nationale de France et consultées sur [Gallica](https://gallica.bnf.fr) :

| Source | Passages du corpus | Mots |
|---|---:|---:|
| *Correspondance de Napoléon Iᵉʳ*, 32 tomes, et correspondances complémentaires (marine, lettres inédites…) | 42 102 | 6,5 M |
| Mémoires | 4 922 | 0,66 M |
| Bulletins de la Grande Armée | 3 080 | 0,56 M |
| Récits de la campagne d'Italie | 1 543 | 0,19 M |
| Proclamations | 125 | 15 000 |
| Lettres à Joséphine (*Tendresses impériales*) | 111 | 12 000 |
| Écrits de jeunesse (*Le Souper de Beaucaire*…) | 106 | 14 000 |

`data/rag/` contient les deux bases utilisées par l'application :

- `napoleon_clean.sqlite` : **25 843 passages** datés et classés, dont 21 358 lettres, 1 973 ordres,
  1 356 bulletins et 162 proclamations, avec leurs embeddings ;
- `napoleon_memoirs.sqlite` : **4 238 passages** de mémoires, consultés par l'archiviste quand le regard
  de l'exilé éclaire le récit.

Chaque lettre de la *Correspondance* renvoie à la page correspondante du tome sur Gallica. Le corpus brut
et les jeux d'entraînement ne sont pas inclus : les scripts de `pipeline/` montrent comment ils ont été
produits.

## Licence

Le code est distribué sous licence [MIT](LICENSE). Les textes historiques des bases RAG proviennent de
Gallica (BnF) et restent soumis à ses conditions de réutilisation. Le modèle 3D de Napoléon visible dans
les vidéos n'est pas couvert par cette licence et n'est pas distribué.
