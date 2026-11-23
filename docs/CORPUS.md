# Constitution du corpus

*[English version](CORPUS.en.md)*

Ce document décrit comment le corpus de ce projet a été constitué : d'où viennent les textes, comment ils
ont été téléchargés, explorés et découpés, quels choix ont été faits, ce que l'intelligence artificielle a
corrigé, et surtout comment les dates ont été traitées. Il se termine par les limites de ce travail et par
ce qu'un travail plus long, rigoureux et humain permettrait d'améliorer.

Tous les chiffres viennent des fichiers produits par le pipeline (manifeste du corpus, décisions de
nettoyage, bases RAG). Les scripts cités se trouvent dans le dépôt privé du projet ; seule l'application
est publiée.

## En bref

| Étape | Résultat |
|---|---|
| Sources téléchargées | 56 fichiers : 50 volumes ou opuscules de Gallica (BnF), 6 livres du Projet Gutenberg |
| Extraction | **52 001 passages**, 7,9 millions de mots, chacun avec titre, date, lieu et destinataire quand ils existent |
| Nettoyage par IA | 51 836 passages examinés : **36 857 gardés**, 14 979 rejetés (motif enregistré pour chacun) |
| Dates | 27 111 passages gardés ont une date ; les passages non datés sont exclus de l'application |
| Base de l'application | **26 003 passages datés**, dont 96,6 % au jour près, et 4 238 passages des *Œuvres* |

## 1. Les sources

Le principe était de ne retenir que des textes **écrits ou dictés par Napoléon** (lettres, ordres,
bulletins, proclamations, récits de campagne), dans des éditions du XIXᵉ et du début du XXᵉ siècle tombées
dans le domaine public.

### Gallica (Bibliothèque nationale de France)

| Ouvrage | Édition | Fichiers | Identifiant Gallica |
|---|---|---|---|
| *Correspondance de Napoléon Iᵉʳ, publiée par ordre de l'Empereur Napoléon III* | Imprimerie impériale, 1858-1869 | 32 tomes | un ark par tome (liste dans `pipeline/napoleon_api.py`, table `_TOME_META`) ; tome 1 : `bpt6k63323895` |
| *Les bulletins de la Grande Armée*, par Adrien Pascal | Prieur et Dumaine, 1841-1844 | 6 | tome 1 : `bpt6k6529553m` |
| *Campagnes d'Italie, d'Égypte et de Syrie*, par Napoléon | 1872 | 3 tomes | tome 1 : `bpt6k6365435q` |
| *Correspondance avec le ministre de la Marine, depuis 1804 jusqu'en avril 1815* | 1837 | 2 tomes | tome 1 : `bpt6k96861814` |
| *Correspondance inédite de l'Empereur Napoléon avec le commandant en chef de l'artillerie de la Grande-Armée* (1809-1812) | 1843 | 1 | `bpt6k63682957` |
| *Quarante lettres inédites* | 1825 | 1 | `bpt6k5797665r` |
| *Les Adieux de Napoléon Bonaparte à l'impératrice Marie-Louise* | opuscule | 1 | `bpt6k5796639z` |
| *Campagnes de Napoléon Bonaparte… actes, proclamations, discours* (Pierre Colau) | 1815 | 1 | `bpt6k6140219b` |
| *Souvenirs de la jeunesse de Napoléon, tirés de ses manuscrits inédits* (G. Libri) | 1842 | 1 | `bpt6k63040910` |
| *Le souper de Beaucaire*, par le capitaine Napoléon Bonaparte (introduction d'Édouard Driault) | 1929 | 1 | `bpt6k56854188` |
| *Histoire sommaire de la vie de l'empereur Napoléon d'après lui-même* | Nantes, 1841 | 1 | `bpt6k6266157b` |

Chaque identifiant se consulte à l'adresse `https://gallica.bnf.fr/ark:/12148/<identifiant>`.

### Projet Gutenberg

| Ouvrage | Fichiers | Numéros Gutenberg |
|---|---|---|
| *Œuvres de Napoléon Bonaparte*, édition C. L. F. Panckoucke | 5 tomes | 12230, 12782, 12893, 13192, 13475 |
| *Tendresses impériales* (lettres à Joséphine) | 1 | 19700 |

Ces deux textes ont été transcrits et **relus par des bénévoles** (Distributed Proofreaders) à partir des
images de Gallica : leur qualité est bien supérieure à l'OCR brut.

## 2. Le téléchargement

- **Gallica** : chaque document a été téléchargé avec la fonction « Télécharger », au format **Texte**, sur
  la totalité des vues (par exemple « vues 1 à 878 sur 878 » pour le tome 1 de la *Correspondance*). Ce
  format est le **mode texte de Gallica, produit automatiquement par reconnaissance optique (OCR)** ;
  Gallica prévient lui-même qu'il « peut comporter un certain nombre d'erreurs ». Le fichier obtenu est une
  page HTML qui contient aussi la notice du document (titre, auteur, éditeur, date, cote, identifiant).
- **Gutenberg** : les livres ont été téléchargés au format HTML.
- Les fichiers bruts ont été rangés par collection dans `napoleon-corpus/sources/`. Ils sont publiés avec le
  dépôt (environ 60 Mo, voir `napoleon-corpus/sources/README.md` pour les conditions de réutilisation) et
  restent téléchargeables à partir des identifiants ci-dessus.
- Le fichier du tome 10 de la *Correspondance* téléchargé à l'origine était en réalité une seconde copie du
  tome 9 (identifiant `bpt6k9634014c`). Il a été remplacé en novembre 2026 par le vrai tome 10
  (`bpt6k9636651b`).

## 3. L'exploration et l'extraction

Chaque collection a une mise en page différente ; un extracteur a donc été écrit pour chacune, avec un
format de sortie commun.

- **Correspondance (32 tomes)** : les lettres sont numérotées et titrées par leur destinataire
  (« 21582. AU GÉNÉRAL COMTE BERTRAND… »), suivies d'une ligne de lieu et de date, en calendrier
  républicain ou grégorien.
- **Bulletins et proclamations** : titre, ligne de date, puis corps du texte ; un extracteur dédié conserve
  le titre et la date que la lecture « texte continu » perdait.
- ***Tendresses impériales*** : structure « LETTRE I / À Joséphine, à Milan / date » ; la lettre est gardée
  comme unité et sa date est propagée à toutes ses parties.
- **Petites collections** (marine, lettres inédites, adieux, artillerie) : chacune a son propre découpage.

L'extraction produit un **manifeste** (`napoleon-corpus/metadata/manifest.jsonl`) de **52 001 passages**
et 7,9 millions de mots. Chaque passage garde son titre, la formulation exacte de la date dans la source
(`date_text`), le lieu, le destinataire, le numéro de la lettre, sa position quand une lettre longue est
coupée en plusieurs parties (autour de 200 mots chacune), le type de source et la mention « domaine
public ».

L'exploration a aussi servi à vérifier le résultat :

- des lettres manquantes ont été repérées dans plusieurs tomes : l'expression qui reconnaissait les lignes
  de date en laissait passer certaines. Elle a été corrigée, puis les lettres manquantes ont été extraites,
  nettoyées et insérées à leur place dans la base ;
- pour chaque tome, un fichier de contrôle donne la première lettre extraite et la page Gallica calculée,
  afin de vérifier que les liens vers Gallica tombent au bon endroit ;
- des requêtes de test ont été lancées sur la base pour voir quelles lettres remontent pour une question
  et à quelles périodes elles appartiennent.

## 4. Les choix

- **La parole de Napoléon, pas celle des autres.** Les biographies et commentaires sont exclus ; un passage
  qui parle de Napoléon à la troisième personne sans contenir de texte de lui est rejeté (601 cas).
- **Le texte d'époque.** L'orthographe historique est conservée quand elle est lisible (15 967 passages
  portent la mention « orthographe ancienne conservée »). Le texte n'est ni modernisé, ni résumé.
- **La date comme condition d'entrée.** Pour l'application, un passage sans date fiable n'entre pas dans la
  base : c'est ce qui permet de raconter la vie de Napoléon dans l'ordre du temps (voir section 6).
- **Le classement des passages** par nature : lettre, ordre, bulletin, proclamation, rapport d'un tiers,
  récit de campagne. L'archiviste s'en sert pour choisir ses sources.
- **Une politique de sources écrite** (`napoleon-corpus/metadata/source_policy.json`) fixe, pour chaque
  usage, les collections retenues, la longueur minimale et l'exigence de date.

## 5. L'amélioration de la source avec l'IA

L'OCR de Gallica contient des erreurs : lettres confondues avec des chiffres, mots coupés, notes de bas de
page mêlées au texte, en-têtes de pages. Chaque passage a été soumis à un modèle de langage chargé d'agir
**en éditeur scientifique prudent**, avec une consigne écrite
(`napoleon-corpus/metadata/llm_cleaning_prompt.md`) : *il vaut mieux rejeter un passage douteux que
corriger ou inventer.*

Pour chaque passage, le modèle décide de le **garder** ou de le **rejeter**, et s'il le garde il produit :

- le texte corrigé : erreurs d'OCR évidentes, ponctuation, notes et marques éditoriales retirées, sans rien
  ajouter ni paraphraser ;
- une version prononçable (abréviations développées) ;
- la date normalisée et la justification de cette date ;
- des marqueurs de qualité et un indice de confiance.

Le texte OCR d'origine est conservé à côté du texte corrigé, ce qui permet de contrôler chaque correction.

Les modèles utilisés sont des modèles d'OpenAI, `gpt-4.1-mini` en traitement direct et `gpt-5-nano` en
traitement par lots (API Batch, moitié moins chère). Le modèle utilisé n'a pas été enregistré passage par
passage.

**Résultats sur les 51 836 passages examinés :**

| Source | Gardés | Rejetés |
|---|---:|---:|
| Correspondance (toutes collections) | 29 829 | 11 984 |
| *Œuvres* (Gutenberg) | 4 238 | 684 |
| Bulletins | 1 479 | 1 620 |
| Récits de campagne | 1 093 | 450 |
| Lettres à Joséphine | 108 | 3 |
| Proclamations | 78 | 47 |
| Écrits de jeunesse | 32 | 74 |
| Sans type (réponse illisible du modèle) | 0 | 117 |
| **Total** | **36 857** | **14 979** |

**Motifs de rejet les plus fréquents :** fragment coupé qu'on ne peut pas reconstituer sans inventer
(11 994), OCR trop corrompu (875), texte à la troisième personne (601), métadonnées de bibliothèque (492),
énumération sans phrase (271), sens trop ambigu (236), texte éditorial (207), réponse illisible du modèle
(117), conflit de date non résolu (59).

**Corrections apportées aux passages gardés :** erreurs d'OCR corrigées (35 312 passages), abréviations
développées (26 232), notes retirées (2 693). 9 060 passages sont marqués comme partiels.

## 6. Les dates : ne garder que celles dont on est sûr

Raconter la vie de Napoléon **au présent, lettre après lettre**, exige des dates sûres. La règle a été :
**dans le doute, pas de date** — et un passage sans date ne sert pas au récit.

Le modèle devait :

- garder la date déjà extraite si le texte ne la contredit pas, ou la préciser si le texte est plus précis ;
- **convertir le calendrier républicain** (vendémiaire à fructidor, an I à an XIV) selon une table de
  correspondance fournie, ou reprendre l'équivalent grégorien quand la source le donne entre parenthèses ;
- conserver la formulation exacte de la source (« Paris, 15 floréal, 10 heures du matin ») à côté de la date
  normalisée ;
- ne **reconstituer une année manquante** que si **plusieurs indices concordants** la rendent certaine
  (institution citée, destinataire, événement identifiable), jamais à partir d'un lieu seul, et en
  justifiant chaque fois les indices utilisés ;
- signaler tout conflit entre la date extraite et le texte.

| Traitement des dates (passages gardés) | Nombre |
|---|---:|
| Date reconstituée à partir d'indices historiques (`date_inferred_from_event`) | 813 |
| Date corrigée d'après le texte, en conflit avec la date extraite (`date_conflict`) | 519 |
| Date d'origine restaurée (`existing_date_restored`) | 465 |
| Rejetés pour conflit de date non résolu | 59 |

Les passages rejetés pour conflit de date ont fait l'objet d'un **sauvetage** : quand une autre partie de
la même lettre avait une date validée, le passage a été retraité avec cette information (88 cas, 76
récupérés).

**Au final**, 27 111 passages gardés sont datés. Seuls ceux-là, d'au moins 20 mots, entrent dans la base
de l'application : **26 003 passages**, datés au jour près pour 25 113 d'entre eux, au mois près pour 384
et à l'année près pour 506. Chacun est rangé dans une période (jeunesse, Révolution et Toulon, campagne
d'Italie, Égypte, Consulat, Empire, Sainte-Hélène).

**Mise à jour de novembre 2026 : le tome 10.** Le tome 10 de la *Correspondance* téléchargé à l'origine était
une copie du tome 9 : la base contenait deux fois les lettres 7130 à 8065 et aucune des lettres 8066 à 8960
(octobre 1804 – juin 1805). Le vrai tome 10 a été extrait et nettoyé par la même méthode (`gpt-5-nano`,
même consigne) : 1 344 passages, 1 086 gardés, 1 035 datés d'au moins 20 mots. L'OCR écrit « an xm » pour
« an XIII », ce qui avait fait dater 131 passages de 1803 ou 1806 ; l'édition étant chronologique, l'année
a été déduite du jour et du mois (octobre-décembre 1804, janvier-juin 1805), puis chaque date comparée à
celles des lettres voisines : 13 passages qui ne suivaient pas leurs voisins ont été écartés. Les 862
passages en double ont été remplacés par **1 022 passages** du vrai tome 10. Les chiffres de nettoyage de
la section 5 sont ceux du traitement initial.

## 7. L'indexation

- `napoleon_clean.sqlite` : les 26 003 passages datés, avec leur vecteur `text-embedding-3-small` (OpenAI)
  pour la recherche sémantique.
- `napoleon_memoirs.sqlite` : les 4 238 passages des *Œuvres de Napoléon Bonaparte* (Gutenberg), sans
  exigence de date, que l'archiviste consulte en contrepoint du récit.

### Les liens vers Gallica

Chaque lettre de la *Correspondance* citée par l'application renvoie à sa page dans l'édition imprimée,
sur Gallica :

```text
https://gallica.bnf.fr/ark:/12148/<identifiant du tome>/f<vue>.image.r=<début du titre>
```

- `f<vue>` est le numéro d'**image** dans le document numérisé, pas le numéro de page imprimée : les
  couvertures et pages liminaires décalent les deux (la page 375 du tome 1 est l'image 405).
- `.r=` fait surligner par Gallica les trois premiers mots du titre, c'est-à-dire le destinataire
  (« AU CITOYEN BARTHÉLÉMY »). Il ne fait que surligner : il ne déplace pas le lecteur vers la lettre.

**Tomes 1 à 15 : page exacte, lue dans les tables de Gallica.** Gallica publie la table des matières de
chaque tome par son API Document (service `Toc`, documenté sur
[api.bnf.fr](https://api.bnf.fr/fr/api-document-de-gallica)). Pour ces tomes, la table des pièces donne,
pour chaque lettre, son numéro et l'image où elle commence. Les tables ont été enregistrées depuis un
navigateur dans `napoleon-corpus/gallica_services/` (Gallica filtre les appels automatisés), puis
`scripts/build_gallica_pages.py` en tire `napoleon-corpus/metadata/gallica_pages.json`
(tome → numéro de lettre → image), que l'application lit au démarrage.

- Les numéros mal lus par l'OCR dans les tables (« 104499 » pour « 10449 ») sont écartés : on ne garde que
  la plus longue suite de lignes où numéros et images augmentent ensemble.
- Quelques lettres manquent dans les tables de Gallica elles-mêmes (tome 1 : n° 438 à 458). Quand le trou
  est petit (40 lettres au plus), elles sont placées entre leurs deux voisines connues ; sinon on n'invente
  rien.
- Résultat : **99,5 %** des passages des tomes 1 à 15 pointent sur la page exacte. Contrôle à la main :
  la lettre 468 (« Au citoyen Barthélemy », 20 mai 1796) tombe bien page 375, image 405.

**Tomes 16 à 32 : page estimée.** Gallica n'y publie pas de table des pièces : seulement un index
analytique par thèmes (tomes 16, 18, 22, 24, 25, 27, 28), les grandes parties du volume (17, 19, 20, 21,
23), une erreur (26), et les tomes 29 à 32 (*Œuvres de Sainte-Hélène*) ne numérotent pas les lettres.
L'image est alors estimée par interpolation dans le tome (table `_TOME_META` de
`pipeline/napoleon_api.py`) ; elle peut être décalée de plusieurs dizaines de pages, et le titre surligné
aide à retrouver la lettre.

**Pourquoi pas une recherche au moment du clic.** Le service `ContentSearch` de la même API trouve la page
exacte d'un titre (`"AU CITOYEN BARTHELEMY"` → image 405), mais Gallica bloque les appels venant d'un
serveur (protection Cloudflare) et n'autorise pas une page d'un autre site à lire ses réponses (CORS). Un
lien ne peut pas non plus lancer la recherche interne du lecteur Gallica. La page doit donc être connue à
l'avance.

## 8. Limites

- **Une correction par IA non vérifiée par un humain.** Les corrections d'OCR et les décisions de garder ou
  rejeter ont été prises par un modèle, passage par passage, sans contrôle humain systématique ni taux
  d'erreur mesuré. Des corrections silencieuses (un mot rétabli à tort, une forme ancienne normalisée) sont
  possibles. Les modèles utilisés sont de petits modèles, choisis pour leur coût.
- **Des dates reconstituées par l'IA.** 813 dates ont été déduites d'indices historiques. Elles sont
  justifiées dans les fichiers de nettoyage, mais **la base de l'application ne distingue plus ces dates
  déduites des dates lues** : toutes y sont considérées comme fiables.
- **Des dates aberrantes passées à travers.** 91 passages de la base portent une année impossible
  (1191 pour 1797, 4814 pour 1814…), héritée d'une erreur d'OCR sur les chiffres. Ils sont rangés en
  période « inconnue » et l'application les utilise rarement, mais ils n'ont pas été corrigés.
- **Un découpage qui coupe les lettres.** Les lettres longues ont été coupées en parties d'environ 200
  mots avant le nettoyage. Près de 12 000 fragments coupés au milieu d'une phrase ont été rejetés : des
  lettres sont donc incomplètes, et un passage de la base n'est souvent qu'une partie de lettre.
- **Une sélection éditoriale du XIXᵉ siècle.** La *Correspondance* publiée sous Napoléon III est une
  édition officielle : elle a écarté des lettres jugées gênantes. Le corpus hérite de cette sélection.
- **Des textes d'attribution discutable.** Certains petits recueils (opuscules de circonstance, textes
  publiés après la chute de l'Empire) mériteraient une vérification de leur authenticité ; les bulletins
  et certains rapports ne sont pas toujours de la main de Napoléon.
- **Des liens Gallica approximatifs pour les tomes 16 à 32.** Gallica n'y fournit pas de table des
  lettres : la page est estimée par interpolation dans le tome (voir « Les liens vers Gallica »).

## 9. Ce qu'un travail plus long, rigoureux et humain permettrait

- **Mesurer la qualité** : relire un échantillon tiré au hasard dans chaque collection, en le comparant
  aux images de Gallica, pour connaître le taux réel d'erreurs d'OCR restantes, de corrections fautives
  et de dates fausses.
- **Vérifier toutes les dates incertaines** : les quelque 1 300 dates reconstituées ou corrigées et les 91
  dates aberrantes, une par une, contre l'édition imprimée ; puis garder dans la base un **niveau de
  fiabilité** (date lue, date déduite, date approximative) au lieu d'un simple « fiable ».
- **Découper par lettre, pas par longueur** : conserver chaque lettre entière et l'encoder en XML-TEI
  (date, lieu, destinataire, page de l'édition), le format de référence des éditions numériques savantes.
- **Lier chaque lettre des tomes 16 à 32 à sa page exacte** dans Gallica, en alignant le texte avec l'OCR
  page par page, ou en obtenant de la BnF un accès à la recherche dans les documents (`ContentSearch`).
- **Repérer les doublons** entre collections (une même lettre peut figurer dans la *Correspondance* et
  dans un recueil particulier).
- **Identifier les personnes et les lieux** et les relier à des référentiels (data.bnf.fr, Wikidata), pour
  lever les ambiguïtés et permettre des recherches par personne ou par lieu.
- **Évaluer l'authenticité** des petits recueils avec l'aide d'historiens.
- **Compléter la sélection** : l'édition moderne de la *Correspondance générale* publiée par la Fondation
  Napoléon est bien plus complète que celle du Second Empire, mais elle est protégée par le droit d'auteur
  et ne pourrait être utilisée que dans un cadre convenu avec ses éditeurs.
- **Publier le corpus lui-même**, avec sa documentation et un identifiant pérenne, pour qu'il puisse être
  vérifié, cité et réutilisé.
