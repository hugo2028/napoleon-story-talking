# Napoléon par ses lettres

**Découvrir Napoléon à travers sa correspondance.** Plus de 15 000 lettres, ordres et billets, écrits
de sa main ou dictés entre 1795 et 1815, que Napoléon vous fait parcourir lui-même :
exilé à Longwood, au printemps 1821, il rouvre ses lettres et les revit avec vous. Chaque mot cité est
le sien, daté et relié à la page de l'édition originale sur Gallica (BnF).

**[English version](README.en.md)**

## Démo

Napoléon accueille le visiteur et ouvre la conversation sur une lettre tirée au hasard : le 14 avril
1806, au prince Eugène, à Milan. Le visiteur choisit d'en savoir plus, et les lettres suivantes déroulent
la vie de famille à la cour de Milan, des conseils à Eugène jusqu'à la lettre du 3 juin 1806 à la
princesse Augusta.

https://github.com/user-attachments/assets/22e0ff95-b3ee-4123-b69f-fea35fa892fd

## Pourquoi ses lettres

Napoléon a écrit, ou dicté, des dizaines de milliers de lettres. Elles ont été rassemblées sous le
Second Empire dans les 32 tomes de la *Correspondance de Napoléon Iᵉʳ*, et presque personne ne les lit :
on les consulte, on les cite, mais on ne les parcourt pas.

Pourtant, c'est là qu'on le voit le mieux. Des mémoires ou un livre d'histoire racontent après coup :
l'auteur connaît la fin, il résume et il justifie. Une lettre est écrite *dans* le moment, avec ce que
Napoléon sait ce jour-là, sans connaître la suite. On y trouve le général qui fixe la marche d'une
division à l'heure près, l'administrateur qui contrôle le prix du pain, le chef de famille qui sermonne
ses frères, l'amoureux qui écrit à Joséphine. Le ton change selon le destinataire, et c'est tout un
homme qui apparaît.

Ce projet en fait une conversation : on n'a pas besoin de savoir quoi chercher. Une lettre ouvre la
discussion, on suit le fil qui intéresse, et Napoléon relie les lettres entre elles, au présent, date
après date.

## Ce que l'on découvre

Les lettres viennent surtout de la *Correspondance de Napoléon Iᵉʳ*, complétée par les lettres à
Joséphine, la correspondance avec la marine et des lettres inédites. Ses correspondants les plus
fréquents, d'après les en-têtes (chiffres approximatifs) :

| Destinataire | Lettres | Ce qu'elles montrent |
|---|---:|---|
| Berthier, son chef d'état-major | ≈ 2 000 | la guerre au jour le jour : marches, ordres, effectifs |
| Clarke, ministre de la Guerre | ≈ 800 | l'armée vue de Paris : conscription, places fortes, Espagne |
| Eugène de Beauharnais, vice-roi d'Italie | ≈ 600 | un beau-fils qu'il forme au gouvernement, lettre après lettre |
| Decrès, ministre de la Marine | ≈ 600 | la flotte, le blocus, l'obsession de l'Angleterre |
| Talleyrand, ministre des Relations extérieures | ≈ 470 | la diplomatie, de Campo-Formio à Tilsit |
| le Directoire exécutif | ≈ 300 | le jeune général d'Italie et d'Égypte face à ses maîtres |
| Joséphine | ≈ 160 | la passion de 1796, puis la tendresse et l'éloignement |
| Joseph, Murat, Cambacérès, Fouché… | des centaines | la famille, l'Empire en coulisses |

Les années les plus denses sont 1805 à 1807 (Austerlitz, Iéna, Tilsit) et 1813 : plus de 1 000 lettres
par an.

## Comment on les découvre

- **Une lettre tirée au sort pour commencer.** Napoléon vient de la relire et en parle : on entre dans le
  jour où elle a été écrite. On peut aussi lui demander directement une période, une bataille ou une
  personne.
- **Un récit qui avance date après date.** Un archiviste (agent autonome, `gpt-4.1`) cherche dans les
  lettres, les situe dans la chronologie et propose la suite en deux variantes, par exemple deux lettres
  ou deux regards sur le même jour. Le visiteur choisit : chaque conversation suit son propre chemin dans
  la correspondance.
- **Des citations exactes.** Le narrateur (`gpt-4.1-mini`) raconte uniquement ce que disent les lettres
  servies. Les phrases citées sont retrouvées par algorithme dans le texte et restituées à l'identique.
- **La source toujours à portée.** À l'écran, la date, le destinataire, la période et le chapitre
  avancent avec le récit, et chaque réplique renvoie à la page du tome sur Gallica.
- **Un homme de 1821.** Napoléon parle depuis Longwood au printemps 1821 et ignore tout ce qui suit. Ce
  qu'il sait sans ses lettres (famille, grandes dates, exil) vient d'une fiche courte et vérifiée ; à
  une question que ni ses lettres ni cette fiche n'éclairent, il ne répond pas sur le fond.
- **Une présence, dans 25 langues.** Napoléon parle, choisit ses gestes et, avec le modèle 3D, apparaît
  dans un salon inspiré de Longwood. Le corpus reste en français ; la conversation se tient dans la
  langue choisie, citations traduites comprises.

## La démarche

Le projet est parti d'une question : peut-on faire parler Napoléon **sans lui prêter un seul mot qu'il
n'a pas écrit** ?

**1. Rassembler les lettres.** Elles ont été extraites des éditions numérisées par Gallica et par le
Projet Gutenberg, avec un extracteur par type de document. Chaque lettre devient une unité avec sa date
(calendrier républicain compris), son lieu et son destinataire. Un nettoyage par LLM, volontairement
conservateur, corrige l'OCR ; les lettres dont la date contredit le contenu sont reprises ou écartées.
Le détail est dans **[docs/CORPUS.md](docs/CORPUS.md)**.

**2. Constater qu'une voix n'est pas une source.** Un Mistral-7B affiné sur le corpus (QLoRA) prend bien
le ton de Napoléon, mais il ne peut pas dire d'où vient ce qu'il affirme. Une conversation qui veut
faire découvrir des lettres doit pouvoir les montrer.

**3. Faire parler les lettres elles-mêmes.** D'où le choix final : un RAG sur la correspondance, où
chaque passage est daté, classé (lettre, ordre, bulletin, proclamation, rapport d'un tiers) et marqué
selon la fiabilité de sa date, et un agent qui enquête dans ces archives avant que Napoléon ne prenne la
parole. Les textes écrits après coup (les *Œuvres de Napoléon Bonaparte*) ne servent qu'en contrepoint.

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
[`data-v3`](https://github.com/hugo2028/napoleon-story-talking/releases/tag/data-v3) et téléchargées
dans `data/rag/` par `scripts/download_data.py` :

- `napoleon_clean.sqlite` : **26 003 passages** datés et classés, avec leurs embeddings. Une lettre longue
  y occupe plusieurs passages : ils forment environ 14 100 lettres, 1 340 ordres, 1 340 bulletins et
  80 proclamations ;
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
