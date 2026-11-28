# La mémoire du visiteur et le graphe de connaissances

Le visiteur rencontre, au fil des récits, des personnes, des lieux, des événements, des lettres, des passages des
*Œuvres* et des tableaux. La mémoire les garde et les relie, et un moteur de recherche ouvre tout le corpus à partir
d'eux. Elle s'ouvre par **la liasse des Mémoires dictés à Longwood**, posée sur le bureau : à Sainte-Hélène,
Napoléon dicte ses souvenirs à Las Cases, Gourgaud, Montholon et Bertrand. (*Le Mémorial de Sainte-Hélène* ne paraît
qu'en 1823 : il n'a pas sa place dans la pièce.)

## Deux étages

1. **Le graphe du corpus**, sur le serveur : `data/rag/napoleon_graphe.sqlite`, construit une fois pour toutes.
2. **La mémoire du visiteur**, dans son navigateur (`localStorage`, clé `napoleon.memoire.v1`) : la liste de ce qu'il
   a rencontré. Rien n'est gardé sur le serveur, il n'y a pas de compte ; les conditions d'utilisation restent vraies
   (« la conversation est gardée temporairement en mémoire sur le serveur, sans être archivée »).

La carte de la mémoire montre les nœuds vus, les liens entre eux, et autour de chacun des bulles estompées « à
découvrir » que le graphe propose.

## Le graphe

| Table | Contenu |
|---|---|
| `entites` | personnes, lieux, événements, institutions : nom canonique, notice et identifiant Wikidata, coordonnées, naissance et mort, portrait, nombre de documents |
| `formes` | les façons dont chaque entité est écrite (« le duc de Rivoli », « Masséna », « le prince d'Essling ») |
| `documents` | lettres (entières), passages des *Œuvres* gardés pour la recherche, tableaux du catalogue et œuvres d'époque de Wikidata, épisodes |
| `mentions` | une entité citée dans un document, ou représentée par un tableau |
| `relations` | les liens qu'une lettre établit entre deux entités, lus par l'IA, avec leur intitulé, leur nature et la lettre d'où ils viennent |
| `liens` | deux entités citées ensemble dans au moins deux documents (liens faibles) |
| `recherche` | index plein texte FTS5, sans accents : noms, formes, titres et textes entiers |

### Construction

La méthode rigoureuse, ses étapes et ses critères de validation sont dans [`graphe/PROTOCOLE.md`](../graphe/PROTOCOLE.md), qui fait foi ; le tableau ci-dessous décrit la première version, remplacée pour la lecture et l'identification.


| Étape | Script | Coût |
|---|---|---|
| 1. Noms et liens de chaque lettre, lue en entier | `graphe/scripts/extract_entites_corpus.py --batch` (gpt-4.1-mini, API Batch) | ≈ 10 $ (17 984 documents) |
| 2. Qui est qui, vu sur tout le corpus, par forme et par période (« le roi de Naples » : Joseph en 1806, Murat en 1810) | `graphe/scripts/resolve_entites.py --batch` (gpt-4.1, API Batch) | ≈ 2 à 4 $ |
| 3. Wikidata : identifiant, notice, dates, coordonnées, portrait ; œuvres d'époque (datées d'avant 1840) qui représentent chaque entité | `graphe/scripts/wikidata_entites.py` | gratuit (une requête par seconde) |
| 4. Vignettes des images (400 px), servies par notre serveur : le navigateur du visiteur n'appelle pas Wikimedia | `graphe/scripts/wikidata_entites.py --telecharger` | téléchargement, après accord |
| 5. La base | `graphe/scripts/build_graphe.py` (arrêter l'API avant : elle tient la base ouverte) | gratuit |

Les *Œuvres* ont déjà leurs personnes et lieux (`scripts/enrich_oeuvres.py`) ; seuls leurs passages datés avec
sûreté entrent dans le graphe (`oeuvres_passages.json`).

### Règle : un lien est attesté par le corpus

Un lien n'existe que s'il vient d'une lettre ou d'un passage des *Œuvres* : lu dans le texte (`relations`, avec sa
source) ou entités citées ensemble (`liens`). Aucun lien n'est tiré des connaissances du modèle, ni du récit généré
par le narrateur : tout lien doit pouvoir être découvert, et vérifié, dans les sources. La synthèse des liens (une
troisième passe, après les deux premières) ne fera que consolider et dater ces liens attestés, chacun avec ses
documents justificatifs.

## Le jeu : débloquer la mémoire

Le graphe entier existe sur le serveur ; le visiteur n'en voit que ce qu'il a débloqué en conversant.

| Quoi | Débloqué quand |
|---|---|
| Personne, lieu, événement, institution | Napoléon le nomme dans un récit |
| Lettre, passage des *Œuvres*, tableau | il est servi (ou épinglé) pendant une réponse |
| Épisode | un document servi en fait partie |
| Lien entre deux entités | les deux sont débloquées **et** ont été rencontrées ensemble : dans la même réponse, ou dans un document que le visiteur a vu |

- Autour de ce qui est débloqué, des bulles verrouillées 🔒 indiquent où chercher ; leur fiche ne s'ouvre pas, un bouton
  « Demander à Napoléon » prépare la question dans le chat.
- La progression : un anneau (moyenne des catégories, pour que 17 984 lettres n'écrasent pas tout) et une barre par
  catégorie, en tête de la mémoire ; après chaque réponse, un bandeau annonce les nouveautés (« 🔓 +2 personnes, +1 lieu,
  +3 liens — mémoire explorée : 4,2 % »).
- À collectionner : les entités citées dans au moins 3 documents (`MIN_COLLECTION`), tous les documents, tous les liens.

## Le serveur

- `GET /graphe/recherche?q=…` : moteur de recherche (noms d'abord, puis textes ; les entités très citées remontent).
- `GET /graphe/noeud?ref=…&texte=1` : un nœud, son texte entier, ses voisins (liens lus d'abord).
- `POST /graphe/sous-graphe {vus}` : la carte de la mémoire.
- `GET /graphe/totaux` : ce qu'il y a à débloquer, par catégorie.
- `POST /graphe/debloquer {vus, tour}` : liens et épisodes débloqués par une réponse.
- `POST /entites` : les noms nouveaux d'une réponse (ceux que le graphe connaît y prennent leur identifiant), et `cites` : les noms déjà connus que la réponse cite de nouveau.

Références de nœuds : `massena`, `znaim`, `lettre:123`, `oeuvre:456`, `tableau:wagram`, `tableau:Q…`, `episode:wagram`.

## L'interface

- Pendant un récit : les noms nouveaux sont soulignés à leur première apparition ; prononcés, ils rejoignent le
  bandeau en bas à gauche et les lieux s'éclairent sur la carte murale ; un clic met la voix en pause et ouvre leur
  fiche.
- La liasse des Mémoires (ou, sans décor 3D, le bouton « Mémoire ») ouvre la carte en bulles (`d3-force`) : une
  image remplit la bulle quand le nœud en a une ; le panneau de droite donne la fiche, le texte entier d'une lettre
  ou d'un passage, et les voisins à explorer ; le moteur de recherche couvre tout le corpus.

La liasse est pour l'instant un objet ajouté par l'application (`web/src/avatar.js`, `_makeLiasse`) ; elle est aussi
dans `scripts/build_longwood_scene.py` et rejoindra le décor précalculé au prochain bake.
