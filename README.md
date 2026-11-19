# Napoléon — l'Empereur raconte sa vie, lettre après lettre

Un avatar conversationnel de Napoléon Bonaparte, exilé à Sainte-Hélène, qui **revit sa vie au présent,
lettre après lettre, dans l'ordre où il l'a écrite**. Chaque réponse est construite à partir de sa
correspondance datée, citée mot pour mot et reliée à sa source sur Gallica (BnF).

*A conversational Napoleon avatar who relives his life in the present tense, letter by letter, in the
order he wrote them. Every answer is built from his dated correspondence, quoted verbatim and linked to
its Gallica (BnF) source. Available in French, English,
Spanish, Italian, German and Portuguese.*

## Démo

**En français** — Napoléon accueille le visiteur sur son île et ouvre la conversation sur une lettre
tirée au hasard : le 14 avril 1806, au prince Eugène, à Milan. Le visiteur choisit d'en savoir plus, et
le récit suit la vie de famille à la cour de Milan, des conseils à Eugène jusqu'à la lettre du 3 juin
1806 à la princesse Augusta.

https://github.com/user-attachments/assets/22e0ff95-b3ee-4123-b69f-fea35fa892fd

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
anachronismes. Le modèle prend bien la voix de l'Empereur, mais les évaluations montrent qu'**une voix
n'est pas une source** : sans affinage, le modèle de base attribue le Code civil à Jean-Jacques Rousseau ;
affiné, il répond avec style mais sans pouvoir dire d'où vient ce qu'il affirme.

**3. Faire parler les archives elles-mêmes, dans l'ordre du temps.** D'où le choix final : un RAG sur les
lettres, dont chaque passage est daté, classé (lettre, ordre, bulletin, proclamation, rapport d'un tiers)
et marqué selon la fiabilité de sa date, et un **agent** qui enquête dans ces archives et les déroule
chronologiquement avant que Napoléon ne prenne la parole.

## Une approche nouvelle : revivre l'histoire au présent

**L'idée centrale : des sources datées, prises dans l'ordre chronologique, pour un récit immersif au
présent.**

Des mémoires ou un livre d'histoire racontent après coup. L'auteur sait déjà comment tout finit : il
résume, réordonne, justifie, et le lecteur reçoit un passé déjà interprété. Une lettre, elle, est écrite
*dans* le moment, avec ce que Napoléon sait ce jour-là, ses ordres, ses inquiétudes et ses espoirs,
sans connaître la suite.

Ce projet s'appuie donc sur la correspondance comme sur une **ligne du temps** : chaque lettre est datée,
située et placée dans l'ordre chronologique. Le récit peut alors avancer comme les événements eux-mêmes,
date après date. Napoléon ne se souvient pas, il revit : « Le 17 février 1799, devant El-Arich, j'écris
au général Dugua… ». Le visiteur traverse les jours au rythme où ils ont été vécus, et l'issue reste
ouverte. Les mémoires ne servent qu'en contrepoint, quand le regard de l'exilé de Sainte-Hélène apporte
quelque chose au moment raconté.

Tout le reste découle de ce choix :

- **La date comme matériau.** Chaque passage est daté, y compris les dates du calendrier républicain,
  et marqué selon la fiabilité de sa date. Les lettres dont la date contredit le contenu sont écartées :
  sans chronologie sûre, pas de récit au présent.
- **Un archiviste qui suit le fil du temps.** Un agent autonome (`gpt-4.1`) situe l'épisode dans la
  chronologie, explore la période et choisit les lettres. Il bâtit ensuite un plan en *moments*
  successifs, du premier ordre aux conséquences. Chaque moment a deux variantes, par exemple deux lettres
  ou deux regards sur le même jour. Le visiteur choisit et l'autre chemin est abandonné : chaque
  conversation suit un chemin unique dans le temps.
- **Un narrateur qui raconte sans rien ajouter.** Le narrateur (`gpt-4.1-mini`) revit les lettres
  servies, ancrées par leur date dite à voix haute, sans développer au-delà de ce qu'elles disent.
- **Des citations exactes.** Les phrases citées sont retrouvées par algorithme dans le texte de la lettre
  et restituées à l'identique : le visiteur entend les mots écrits ce jour-là.
- **Le hasard des archives comme porte d'entrée.** La conversation s'ouvre sur une lettre tirée au sort,
  comme si Napoléon venait de la relire, et l'on plonge dans le jour où elle a été écrite.
- **Le temps rendu visible.** À l'écran, l'épisode, la période, le chapitre et les dates des lettres
  racontées avancent avec le récit. Chaque réplique renvoie à la page de l'édition sur Gallica.
- **Une présence incarnée, dans six langues.** La voix Azure pilote la synchronisation labiale et
  Napoléon choisit ses gestes. Le corpus reste en français, et la conversation se tient en français,
  anglais, espagnol, italien, allemand ou portugais.

## Architecture

```
web/            Interface (Vite) + relais Node/Express (port 3002) — voix Azure, avatar three.js
pipeline/       API Flask (port 5001), archiviste (napoleon_archivist.py), narrateur (napoleon_agent.py)
data/rag/       Bases SQLite du RAG (lettres + mémoires, avec embeddings) — via Git LFS
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

Chaque lettre de la *Correspondance* renvoie à la page correspondante du tome sur Gallica. Le dépôt ne
contient que ce qui fait tourner l'application : le corpus brut, les scripts d'extraction et de nettoyage
et les expériences de fine-tuning ne sont pas inclus.

## Licence

Le code est distribué sous licence [MIT](LICENSE). Les textes historiques des bases RAG proviennent de
Gallica (BnF) et restent soumis à ses conditions de réutilisation. Le modèle 3D de Napoléon visible dans
les vidéos n'est pas couvert par cette licence et n'est pas distribué.
