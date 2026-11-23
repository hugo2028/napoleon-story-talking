# Napoléon — l'Empereur raconte sa vie, lettre après lettre

Un avatar conversationnel de Napoléon Bonaparte, exilé à Sainte-Hélène, qui **revit sa vie au présent,
lettre après lettre, dans l'ordre où il l'a écrite**. Chaque réponse est construite à partir de sa
correspondance datée, citée mot pour mot et reliée à sa source sur Gallica (BnF).

**[English version](README.en.md)**

## Démo

Napoléon accueille le visiteur sur son île et ouvre la conversation sur une lettre tirée au hasard : le
14 avril 1806, au prince Eugène, à Milan. Le visiteur choisit d'en savoir plus, et le récit suit la vie de
famille à la cour de Milan, des conseils à Eugène jusqu'à la lettre du 3 juin 1806 à la princesse
Augusta.

https://github.com/user-attachments/assets/22e0ff95-b3ee-4123-b69f-fea35fa892fd

## La démarche

Le projet est parti d'une question simple : peut-on faire parler Napoléon **sans lui prêter un seul mot
qu'il n'a pas écrit** ? Il est passé par trois étapes.

**1. Constituer le corpus.** Les écrits de Napoléon ont été extraits d'éditions numérisées par Gallica
et par le Projet Gutenberg, avec un extracteur par type de document : les 32 tomes de la
*Correspondance*, les bulletins de la Grande Armée, les proclamations, les lettres à Joséphine, les écrits
de jeunesse, les récits de campagne et les *Œuvres de Napoléon Bonaparte*. Chaque lettre devient une unité, avec sa date (y compris les dates du calendrier
républicain), son lieu et son destinataire : **52 000 passages, 7,9 millions de mots**. Un nettoyage par
LLM, volontairement conservateur, corrige les erreurs d'OCR et rejette les passages inexploitables ; les
lettres dont la date entre en conflit avec leur contenu sont reprises ou écartées. Le détail complet
(sources exactes, choix, nettoyage, dates, limites) est dans **[docs/CORPUS.md](docs/CORPUS.md)**.

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
ouverte. Les textes écrits après coup (les *Œuvres de Napoléon Bonaparte*) ne servent qu'en
contrepoint, quand ils apportent quelque chose au moment raconté.

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
- **Une présence incarnée, dans 25 langues.** Napoléon parle, avec la voix de synthèse du navigateur,
  et choisit ses gestes. Le corpus reste en français ; la conversation se tient dans la langue choisie,
  citations traduites comprises (voir « Langues » plus bas).

## Architecture

```
web/            Interface (Vite) + relais Node/Express (port 3002) — voix, avatar three.js ou médaillon 2D
pipeline/       API Flask (port 5001), archiviste (napoleon_archivist.py), narrateur (napoleon_agent.py),
                connecteur universel compatible OpenAI (llm_connector.py)
scripts/        download_data.py : télécharge les bases RAG depuis la Release GitHub
data/rag/       Bases SQLite du RAG (lettres + Œuvres, avec embeddings), non versionnées
docs/           CORPUS.md : constitution détaillée du corpus
```

## Installation

| | Ce qu'il faut | Sans |
|---|---|---|
| **Requis** | Python 3.11+, Node.js 18+ et **un modèle de langage** accessible par une API compatible OpenAI : OpenAI, Anthropic, Mistral, Google Gemini, OpenRouter, Groq, ou **Ollama**, gratuit et en local | — |
| Optionnel | Une clé **OpenAI** pour la recherche sémantique, si le fournisseur choisi n'est pas OpenAI | l'archiviste cherche par mots-clés |
| Optionnel | Un **avatar 3D** `web/avatar/avatar.glb` (voir plus bas) | un médaillon 2D animé |

```bash
git clone https://github.com/hugo2028/napoleon-story-talking.git
cd napoleon-story-talking

pip install -r requirements.txt
python scripts/download_data.py   # bases RAG (≈285 Mo) depuis la Release GitHub, empreintes vérifiées
cd web && npm install && cd ..
```

Lancement, dans deux terminaux :

```bash
python pipeline/napoleon_api.py
cd web && npm run dev
```

Puis ouvrez <http://localhost:5174>. Au premier lancement, le panneau **⚙ Paramètres** s'ouvre :

1. choisissez la langue ;
2. choisissez le fournisseur et saisissez sa clé : la liste des modèles est lue sur son API, et vous
   choisissez celui de l'archiviste (il doit gérer l'appel d'outils) et celui du narrateur ;
3. si votre fournisseur n'est pas OpenAI, ajoutez si vous le souhaitez une clé OpenAI pour la recherche
   sémantique.

Napoléon parle avec la voix de synthèse du navigateur, gratuite et sans clé : les voix « Natural »
d'Edge sont les plus naturelles.

Les clés sont vérifiées auprès de chaque service, puis enregistrées dans le fichier `.env` local : elles ne
quittent pas votre ordinateur. Vous pouvez aussi remplir `.env` à la main à partir de `.env.example`.

## Langues

L'interface et le récit sont disponibles en 25 langues :

- **langues d'origine du projet** : français, anglais, espagnol, italien, allemand, portugais ;
- **pays traversés par l'épopée** : russe, polonais, néerlandais, arabe (écrit de droite à gauche) ;
- **grand public mondial** : chinois, japonais, coréen, hindi ;
- **autres langues européennes** : suédois, danois, tchèque, grec, roumain, turc, ukrainien ;
- **langues régionales** : corse, catalan, basque, breton.

Le narrateur écrit directement dans la langue choisie ; la qualité dépend du modèle configuré, et elle est
plus inégale pour les langues régionales. Le corse et le breton n'ont pas de voix de synthèse : Napoléon
y parle avec une voix italienne ou française. Le nombre de voix disponibles dépend du navigateur (Edge en
propose le plus).

**Ajouter une langue** : une entrée dans `LANGS` de `web/src/i18n.js` (nom, locale, nom donné au
narrateur, éventuellement un drapeau), puis `python scripts/translate_ui.py <code>` génère et vérifie ses
libellés dans `web/src/locales/<code>.json` avec le modèle configuré. L'API accepte toute langue proposée
par l'interface.

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

Dès qu'un modèle 3D est présent, **⚙ Paramètres** propose aussi une voix **Azure Speech** (optionnelle,
offre gratuite F0) : une voix neuronale dont les visèmes synchronisent les lèvres de l'avatar. Sans
Azure, l'avatar parle avec la voix du navigateur.

## Sources des données

Tous les textes viennent d'éditions du XIXᵉ et du début du XXᵉ siècle, dans le domaine public :
50 volumes ou opuscules numérisés par la Bibliothèque nationale de France sur
[Gallica](https://gallica.bnf.fr), et 6 livres transcrits et relus par les bénévoles du
[Projet Gutenberg](https://www.gutenberg.org) (*Œuvres de Napoléon Bonaparte* et *Tendresses impériales*).
La liste exacte des éditions, avec leurs identifiants, est dans **[docs/CORPUS.md](docs/CORPUS.md)**.

| Source | Passages du corpus | Mots |
|---|---:|---:|
| *Correspondance de Napoléon Iᵉʳ*, 32 tomes, et correspondances complémentaires (marine, lettres inédites…) | 42 102 | 6,5 M |
| *Œuvres de Napoléon Bonaparte*, éd. Panckoucke, 5 tomes (Gutenberg) | 4 922 | 0,66 M |
| Bulletins de la Grande Armée | 3 080 | 0,56 M |
| *Campagnes d'Italie, d'Égypte et de Syrie*, 3 tomes | 1 543 | 0,19 M |
| Proclamations | 125 | 15 000 |
| Lettres à Joséphine (*Tendresses impériales*, Gutenberg) | 111 | 12 000 |
| Écrits de jeunesse (*Le Souper de Beaucaire*…) | 106 | 14 000 |

Les deux bases utilisées par l'application sont publiées dans la Release
[`data-v1`](https://github.com/hugo2028/napoleon-story-talking/releases/tag/data-v1) et téléchargées
dans `data/rag/` par `scripts/download_data.py` :

- `napoleon_clean.sqlite` : **25 843 passages** datés et classés, dont 21 358 lettres, 1 973 ordres,
  1 356 bulletins et 162 proclamations, avec leurs embeddings ;
- `napoleon_memoirs.sqlite` : **4 238 passages** des *Œuvres de Napoléon Bonaparte*, que l'archiviste
  consulte en contrepoint du récit.

Chaque lettre de la *Correspondance* renvoie à la page correspondante du tome sur Gallica. Les **sources
brutes** (exports texte de Gallica et livres HTML de Gutenberg, environ 60 Mo) sont publiées dans
[`napoleon-corpus/sources/`](napoleon-corpus/sources/README.md). Les scripts d'extraction et de nettoyage
et les expériences de fine-tuning ne sont pas inclus.

## Licence

Le code est distribué sous licence [MIT](LICENSE). Les textes historiques des bases RAG proviennent de
Gallica (BnF) et du Projet Gutenberg : textes du domaine public, dont les fichiers restent soumis aux
conditions de réutilisation de Gallica (usage non commercial libre avec mention de la source) et à la
licence du Projet Gutenberg (voir [`napoleon-corpus/sources/README.md`](napoleon-corpus/sources/README.md)). Le modèle 3D de Napoléon visible dans
les vidéos n'est pas couvert par cette licence et n'est pas distribué.
