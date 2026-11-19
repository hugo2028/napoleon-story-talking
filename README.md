# Napoléon — l'Empereur raconte sa vie, lettre après lettre

Un avatar conversationnel de Napoléon Bonaparte, exilé à Sainte-Hélène, qui répond à vos questions
en s'appuyant **uniquement sur sa correspondance réelle** : chaque réponse est construite à partir de
lettres authentiques, citées mot pour mot et reliées à leur source sur Gallica (BnF).

*A conversational Napoleon avatar grounded in his actual letters. Every answer is built from authentic
correspondence, quoted verbatim and linked to its Gallica (BnF) source. Available in French, English,
Spanish, Italian, German and Portuguese.*

## Démo

**En français** — premier échange : Napoléon ouvre la conversation sur une lettre tirée au hasard.

https://github.com/user-attachments/assets/b3e7795e-da2e-4289-b31b-4a6c19584048

**In English** — a full conversation: the campaign in Egypt and Syria, told from his letters, with the
episode, chapter and letters shown on screen and the Gallica sources attached to each answer.

https://github.com/user-attachments/assets/9c04a932-a738-41c5-9ea5-bf15ac72cdc3

## Ce que fait l'application

- **Un archiviste autonome** (agent à outils, `gpt-4.1`) enquête dans la correspondance : recherche
  sémantique et par mots-clés, exploration d'une période, lecture des lettres. Il bâtit ensuite un plan
  du récit en *moments*, avec deux variantes par moment : le visiteur choisit, l'autre chemin est
  abandonné, et chaque conversation sur un même sujet est unique.
- **Un narrateur** (`gpt-4.1-mini`) fait parler Napoléon à la première personne, au présent, en s'en
  tenant strictement aux lettres servies. Les citations sont choisies par un appel dédié puis vérifiées
  mot pour mot dans le texte de la lettre.
- **Premier échange au hasard** : la conversation s'ouvre sur une lettre tirée au sort, et le hasard peut
  de nouveau ouvrir la voie quand le visiteur veut « autre chose ».
- **Repères à l'écran** : épisode, période, chapitre et lettres racontées, mis à jour à chaque réponse,
  et sources jointes à chaque réplique (liens Gallica).
- **Voix et avatar** : synthèse vocale Azure avec visèmes pour la synchronisation labiale et gestes
  choisis par le modèle. Six langues, un bouton pour enregistrer une vidéo de démo de l'onglet.

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
git clone <url-du-depot>
cd <dossier>

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

## Données

`data/rag/` contient les deux bases utilisées par l'application, construites à partir de la
*Correspondance de Napoléon Iᵉʳ* et de mémoires de Sainte-Hélène, textes du XIXᵉ siècle numérisés par
la Bibliothèque nationale de France (source : [gallica.bnf.fr](https://gallica.bnf.fr) / BnF).
Le corpus brut et les jeux d'entraînement ne sont pas inclus ; les scripts de `pipeline/` montrent
comment ils ont été produits.

## Licence

Le code est distribué sous licence [MIT](LICENSE). Les textes historiques des bases RAG proviennent de
Gallica (BnF) et restent soumis à ses conditions de réutilisation. Le modèle 3D de Napoléon visible dans
les vidéos n'est pas couvert par cette licence et n'est pas distribué.
