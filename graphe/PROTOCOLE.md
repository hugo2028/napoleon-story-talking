# Protocole : construction du graphe de connaissances de la correspondance de Napoléon

*Version 1.1 — 27 novembre 2026. Ce protocole fixe la méthode avant toute exécution. Toute modification fait l'objet
d'une nouvelle version, datée, avec la raison du changement (§ 11) ; les résultats publiés indiquent la version
suivie.*

## 1. Objectifs et questions

**Objectif.** Construire, à partir de la correspondance et des *Œuvres* de Napoléon, un graphe où chaque personne,
lieu, événement et institution est identifié sans ambiguïté malgré ses noms multiples, et où chaque lien entre deux
entités est **attesté par une phrase d'un document du corpus**. Le graphe alimente la mémoire du visiteur
(`docs/MEMOIRE.md`) et, par des profils et des synthèses sourcés, la connaissance de l'archiviste.

**Questions.**

- **Q1 — Identification.** Peut-on rattacher chaque mention (« le duc de Rivoli », « Masséna », « le prince
  d'Essling ») à la bonne entité, en tenant compte de la date (« le roi de Naples » : Joseph en 1806, Murat en 1810) ?
- **Q2 — Liens.** Peut-on extraire les liens que les documents établissent, avec une précision suffisante, et
  chacun prouvé par une citation exacte ?
- **Q3 — Découvertes.** Quelles entités et quels liens le corpus atteste-t-il qui ne figurent pas dans la référence
  (Wikidata) ?
- **Q4 — Connaissance d'ensemble.** Peut-on en tirer des profils de personnages et des synthèses de groupes fidèles
  aux sources, et utiles pour répondre à des questions larges ?

## 2. Corpus

| Ensemble | Unités | Source |
|---|---|---|
| Correspondance (lettres, ordres, bulletins, proclamations, rapports), édition du Second Empire et compléments | 17 984 documents (une lettre découpée en passages est un seul document) | `data/rag/napoleon_clean.sqlite`, regroupement par `build_letter_index` |
| *Œuvres de Napoléon* (Panckoucke, 1821) | 3 804 passages datés avec sûreté | `data/rag/napoleon_memoirs.sqlite`, `oeuvres_passages.json` |
| Exclus | recueil apocryphe probable des « lettres inédites », textes d'éditeurs, passages des *Œuvres* à date incertaine | `docs/LETTRES_INEDITES.md`, `docs/evaluations/enrichissement_oeuvres.md` |

Les dates des documents sont celles de la base après les corrections documentées (`date_fixes.csv`). Le texte vient
d'un OCR : fautes de chiffres et de lettres possibles (« Dalmalie » pour Dalmatie).

## 3. Définitions

- **Entité** : une personne, un lieu, un événement (bataille, siège, traité, cérémonie) ou une institution (armée,
  corps, assemblée, ministère) réels et identifiables. Napoléon lui-même n'est pas une entité du graphe : il est
  l'auteur ; ses liens sont portés par les documents.
- **Mention** : une occurrence d'une entité dans un document, sous une **forme** (chaîne écrite) donnée.
- **Lien** : une relation entre deux entités, **établie par un document** : (entité A, intitulé, entité B, nature,
  date, document, citation). La **citation** est la phrase ou le fragment exact du document qui l'établit.
- **Référence** : le registre construit depuis Wikidata (§ 5.1). Elle sert **uniquement** à reconnaître les
  entités. Elle ne produit **aucun lien** : un lien connu de Wikidata ou du modèle mais absent du corpus n'existe pas
  dans le graphe.
- **Découverte** : entité absente de la référence (entité « NIL »), ou lien entre deux entités de la référence que
  Wikidata ne relie pas, attestés par le corpus.

## 4. Principes

1. **Tout lien est sourcé.** Pas de lien sans citation vérifiée dans le texte (§ 5.4).
2. **Les connaissances du modèle ne créent rien.** Le modèle lit, rattache et cite ; il n'ajoute pas ce qu'il sait.
3. **La référence identifie, elle ne relie pas.**
4. **Seuils avant exécution.** Aucune étape n'est lancée sur le corpus entier avant d'avoir atteint ses seuils sur le
   jeu de référence (§ 7).
5. **Traçabilité.** Chaque lancement écrit un manifeste (§ 9) ; toute donnée du graphe remonte à un document, une
   étape et un lancement.
6. **Reproductibilité.** Température 0, consignes versionnées, entrées figées et empreintes enregistrées.

## 5. Méthode

### 5.1 Registre de référence (Wikidata)

- **Entrée.** Les entités candidates : celles du graphe provisoire citées dans au moins 3 documents
  (`graphe/scripts/build_graphe.py`).
- **Procédé.** Recherche Wikidata en français, puis choix du candidat cohérent avec l'époque : personne née entre
  1700 et 1810 ; lieu avec coordonnées ; événement entre 1785 et 1821. On garde pour chaque entité :
  - son identifiant et ses noms (libellé, alias en français et en anglais) ;
  - ses **titres avec leurs dates** (P97 avec début P580 et fin P582) ;
  - ses **fonctions datées** (P39), ses dates de naissance et de mort, ses coordonnées.
- **Contrôle.** 100 rattachements tirés au hasard sont vérifiés à la main : justesse attendue ≥ 95 %. En dessous, on
  corrige la règle de choix, et non les cas un à un.
- **Sortie.** `graphe/donnees/registre.json` : entité → noms, titres datés, fonctions datées.

### 5.2 Candidats par script

- Pour chaque document, toutes les formes du registre présentes dans le texte, comparées en mot entier, sans accents
  et sans grade.
- Une forme n'est retenue que si elle est **valide à la date du document**. Un titre n'est candidat qu'entre ses
  dates : « duc de Rivoli » n'est candidat qu'à partir de 1808.
- Sortie : pour chaque document, une liste de candidats (forme, entité, intervalle de validité).

### 5.3 Lecture : identification et liens, en deux niveaux

La lecture se fait **par vagues chronologiques**, période par période (les 9 tranches de `periode()`). Après chaque
vague, le registre et le graphe sont mis à jour : formes apprises, découvertes, identifications faites. La vague
suivante interroge donc une base enrichie par les lectures précédentes.

- **Niveau A, lecture simple (API Batch).** Le modèle reçoit le document et ses candidats (§ 5.2), puis répond en
  une fois.
- **Niveau B, lecteur outillé.** Le modèle lit le document et **interroge la base** avant de rattacher une mention.
  Il dispose des outils suivants :
  - `chercher_entite(forme, date)` : les entités possibles pour une forme, avec leurs titres et fonctions valides à
    cette date ;
  - `qui_porte(titre, date)` : le titulaire d'un titre ou d'une fonction à cette date ;
  - `fiche_entite(id)` : les noms, titres et fonctions datés d'une entité, ses voisines et quelques citations ;
  - `lectures_precedentes(forme, destinataire)` : comment cette forme a été rattachée dans les documents déjà lus ;
  - `lettres_voisines(document)` : les documents proches dans le temps ou adressés au même destinataire ;
  - `enregistrer_lecture(mentions, liens)` : action terminale. Elle est **refusée**, avec la raison, si une citation
    est introuvable dans le texte (§ 5.4), si un identifiant n'existe pas, ou si une entité n'est pas valide à la
    date. Le lecteur corrige alors sa lecture.

  Le niveau B prend les documents que le niveau A signale comme difficiles :
  - une mention qui a plusieurs candidats valides à la date ;
  - une mention NIL ;
  - une citation rejetée ;
  - une identification marquée « incertaine ».

  Si la comparaison du § 7 le justifie, il prend tout le corpus.

Dans les deux niveaux, le modèle doit :

- **Rattacher chaque mention** à un candidat, ou la déclarer **NIL** (absente du registre), avec la forme exacte et
  la catégorie.
- **Extraire les liens** que le document établit entre entités (candidats ou NIL), chacun avec :
  - son **intitulé** (2 à 6 mots) ;
  - sa **nature** : commandement, ordre, famille, lieu, participation, diplomatie, administration, opinion ou autre ;
  - sa **date** : celle du document, ou celle que le texte précise ;
  - sa **citation exacte**, recopiée du document (au plus 300 caractères).
- **Paramètres.** Modèle gpt-4.1-mini (par défaut ; un essai comparatif avec gpt-4.1 sur le jeu de référence fixe le
  choix, § 7), température 0, sortie JSON, consignes versionnées `graphe/prompts/lecture_v1.txt` (niveau A) et
  `graphe/prompts/lecteur_outille_v1.txt` (niveau B). Chaque lecture enregistre aussi le niveau qui l'a produite et les
  appels d'outils faits.

### 5.4 Vérification des preuves (script)

- Chaque citation est recherchée dans le texte du document, avec la tolérance de `_retrouver_citation` : ponctuation,
  espaces, apostrophes, un ou deux mots mal recopiés, ratio ≥ 0,85.
- Une citation non retrouvée fait **rejeter** le lien. Le taux de rejet est un indicateur de qualité (§ 7).
- On contrôle aussi que les deux formes des entités du lien figurent dans la citation, ou dans la phrase qui la
  contient. Sinon, le lien est marqué « faible » et n'est pas montré au visiteur.

### 5.5 Entités NIL et découvertes

- Les mentions NIL sont **regroupées** sur tout le corpus : même forme normalisée, compatibilité de catégorie et de
  période, contextes proches (embeddings des phrases qui les contiennent).
- Les groupes ambigus sont tranchés par gpt-4.1, qui voit toutes leurs occurrences datées et leurs citations. Les
  fusions sont limitées à ce que les occurrences montrent.
- **Seuil d'existence.** Une entité NIL entre dans le graphe si elle est attestée dans au moins 2 documents, ou dans
  1 document et liée à une entité du registre.
- **Marquage.** Chaque entité NIL retenue est une **découverte**. Un lien entre deux entités du registre que Wikidata
  ne relie par aucune propriété est aussi une découverte. Les deux sont comptés (§ 8) et signalés dans l'interface.

### 5.6 Consolidation des liens

- Les liens identiques (mêmes entités, même nature, intitulés proches) sont regroupés en un **lien consolidé**, qui
  garde :
  - sa période (première et dernière date) ;
  - son nombre de documents ;
  - ses meilleures citations (au plus 5).
- La consolidation ne fusionne que des liens extraits. Elle n'ajoute rien.

### 5.7 Connaissance d'ensemble

- **Profils.** Pour chaque entité citée dans au moins 10 documents, gpt-4.1 rédige un profil (rôle, trajectoire,
  relations principales) **uniquement à partir de ses liens consolidés et de leurs citations**. Chaque phrase du
  profil renvoie aux documents qui la fondent. Une phrase sans renvoi est supprimée par script.
- **Groupes.** Les groupes du graphe sont détectés par l'algorithme de Leiden, sur les liens consolidés pondérés par
  le nombre de documents. Chaque groupe reçoit une synthèse sourcée, rédigée de la même manière.
- **Usage.** L'archiviste consulte profils et synthèses par un outil. Ce sont des synthèses de sources, citées : il
  les utilise pour s'orienter et pour choisir des lettres, comme les autres outils.

## 6. Jeu de référence (évaluation)

- **Échantillon.** 60 documents, tirés au hasard avec graine fixe (1821) et stratifiés :
  - par période (les 9 tranches de `periode()`) ;
  - par type (lettre, ordre, bulletin, *Œuvres*) ;
  - par difficulté : au moins 15 documents avec titres ou formes ambiguës (rois, ducs, « mon frère »).

  Le tirage et la liste sont enregistrés dans `graphe/evaluations/reference.json`.
- **Annotation.** Pour chaque document :
  - les mentions, avec leur entité (identifiant Wikidata ou NIL) ;
  - les liens établis par le texte, avec leur citation.

  La pré-annotation est faite par gpt-4.1.
- **Validation.** Le projet n'a pas d'annotateur indépendant. La validation se fait donc en deux temps :
  1. **Annotateur 1 : l'assistant de développement** (Claude). Il relit chacun des 60 documents en lisant le texte
     entier, et corrige chaque mention et chaque lien.
  2. **Annotateur 2 : le porteur du projet.** Il revérifie seul 15 documents tirés au hasard (graine 1815), sans voir
     d'abord les corrections de l'annotateur 1.

  L'**accord entre les deux annotateurs** sur ces 15 documents est mesuré : accord sur l'entité de chaque mention, et
  kappa de Cohen sur les liens jugés justes ou faux. Il est publié comme indicateur de fiabilité du jeu de référence.
  Les désaccords sont tranchés ensemble et consignés. Un accord inférieur à 85 % sur les mentions entraîne la révision
  du guide d'annotation et une nouvelle relecture.
- **Experts, plus tard.** Le jeu de référence, le guide d'annotation et la page d'annotation sont faits pour être
  repris par des historiens spécialistes. Chaque annotation porte son auteur, sa date et sa version. Quand des
  experts valident tout ou partie du jeu :
  - leur annotation fait foi et remplace celle de l'annotateur 1 ;
  - l'accord entre experts et annotateur 1 est publié, comme mesure rétrospective de la fiabilité des versions
    précédentes ;
  - toutes les mesures du § 7 sont recalculées dans une nouvelle version du protocole.
- **Guide d'annotation.** Il est joint au fichier : ce qui compte comme entité, comme lien, comme citation suffisante.
- Le jeu de référence n'est **jamais** utilisé pour mettre au point les consignes. Celles-ci sont mises au point sur
  un second échantillon de 20 documents, séparé.

## 7. Mesures et seuils (avant tout traitement complet)

| Mesure | Définition | Seuil |
|---|---|---|
| Rappel des mentions | mentions annotées retrouvées | ≥ 85 % |
| Justesse d'identification | mentions retrouvées rattachées à la bonne entité (NIL compris) | ≥ 92 % ; ≥ 85 % sur les formes ambiguës |
| Précision des liens | liens extraits jugés justes, citation comprise | ≥ 85 % |
| Rappel des liens | liens annotés retrouvés | ≥ 60 % |
| Rejet des citations | citations non retrouvées dans le texte (§ 5.4) | ≤ 10 % |
| Précision des NIL | entités NIL retenues qui sont de vraies entités absentes du registre | ≥ 80 % |
| Fidélité des profils | phrases de profil soutenues par leurs citations (jugement humain sur 20 profils) | ≥ 95 % |
| Accord entre annotateurs | même entité pour une mention, sur 15 documents (§ 6) | ≥ 85 % |

**Comparaison des niveaux A et B, fixée d'avance.** Les deux niveaux lisent le jeu de référence entier. On retient le
niveau B pour les documents difficiles s'il gagne **au moins 5 points** sur la justesse d'identification des formes
ambiguës, ou sur la précision des NIL, sans perdre plus de 2 points ailleurs. On le retient pour tout le corpus s'il
gagne au moins 5 points sur la justesse d'identification de l'ensemble. Les coûts mesurés par document sont publiés
avec le résultat.

Si un seuil n'est pas atteint, on analyse les erreurs, on corrige la consigne ou la règle, on incrémente la version,
puis on mesure de nouveau. Les mesures de chaque version sont gardées, y compris les échecs.

## 8. Résultats attendus et rapport

`graphe/evaluations/resultats.md` donnera :
- les mesures du § 7, par version ;
- la taille du graphe (entités par catégorie, mentions, liens consolidés) ;
- les découvertes : nombre d'entités NIL, liens absents de Wikidata, avec 20 exemples cités ;
- l'analyse d'erreurs par type (OCR, homonymes, titres, pronoms, ironie) ;
- les coûts réels.

## 9. Traçabilité et reproductibilité

Chaque lancement écrit `graphe/runs/<date>_<étape>.json`, qui contient :
- l'étape, la version du protocole et l'empreinte SHA-256 de la consigne ;
- le modèle, sa date et ses paramètres ;
- l'empreinte des entrées, le nombre d'unités traitées, rejetées et en erreur ;
- l'identifiant du lot OpenAI ;
- les jetons consommés et le coût ;
- l'empreinte des sorties.

Chaque entité, mention et lien du graphe porte l'identifiant du lancement qui l'a produit.

## 10. Limites connues

- **Couverture de la référence :** Wikidata est inégal sur les officiers subalternes et les lieux mineurs. C'est ce
  que mesurent les NIL.
- **OCR :** des formes déformées peuvent échapper aux candidats. La lecture par le modèle les rattrape en partie,
  sous forme de NIL fusionnées ensuite.
- **Biais de la source :** le corpus est la voix de Napoléon, éditée sous le Second Empire. Un lien attesté dit ce
  que le document affirme, pas ce qui fut.
- **Liens implicites :** le modèle extrait ce que le texte établit. Les relations seulement sous-entendues échappent
  au rappel, ce qui est voulu.
- **Validation sans annotateur indépendant :** l'annotateur 1 est un modèle d'IA, ce qui peut partager les biais du
  lecteur évalué. L'annotateur 2 ne revoit qu'un quart du jeu. L'accord entre les deux est publié pour que le lecteur
  puisse juger de la fiabilité.
- **Ordre de lecture :** les vagues chronologiques font dépendre une lecture des précédentes. Une erreur précoce peut
  se propager. On la surveille par `lectures_precedentes` : chaque rattachement fondé sur une lecture antérieure le
  dit.

## 11. Étapes, critères de passage et coûts estimés

| # | Étape | Critère de passage | Coût estimé |
|---|---|---|---|
| 1 | Registre Wikidata (§ 5.1), avec contrôle de 100 rattachements | justesse ≥ 95 % | gratuit |
| 2 | Jeu de référence : tirage, pré-annotation, validation humaine (§ 6) | 60 documents signés | ≈ 1 $ |
| 3 | Mise au point des consignes sur l'échantillon séparé, puis mesure des niveaux A et B sur le jeu de référence (§ 5.2–5.4, § 7) | seuils du § 7, comparaison A/B | ≈ 2 à 4 $ |
| 4 | Lecture du corpus entier par vagues chronologiques : niveau A (API Batch), niveau B pour les documents difficiles, vérification des preuves | rejet ≤ 10 % | ≈ 10 à 14 $ (A), plus 10 à 20 $ (B) |
| 5 | NIL et découvertes (§ 5.5), mesure de précision des NIL | ≥ 80 % | ≈ 1 à 3 $ |
| 6 | Consolidation (§ 5.6) et construction du graphe | — | gratuit |
| 7 | Profils et groupes (§ 5.7), mesure de fidélité | ≥ 95 % | ≈ 3 à 6 $ |
| 8 | Rapport (§ 8) | — | — |

**Historique des versions**

| Version | Date | Changement |
|---|---|---|
| 1.0 | 2026-11-27 | Première version. |
| 1.1 | 2026-11-27 | Lecteur outillé (niveau B) qui interroge la base en lisant ; lecture par vagues chronologiques ; comparaison A/B fixée d'avance ; validation par deux annotateurs (l'assistant et le porteur du projet), avec mesure de leur accord. Raison : identifier les cas ambigus en vérifiant dans la base plutôt qu'en devinant ; absence d'annotateur indépendant. |
