# La scène : Longwood, un soir

*[English version](SCENE.en.md)*

Napoléon parle depuis une pièce de Longwood, sa maison d'exil à Sainte-Hélène, au printemps 1821. Ce document
explique comment cette scène est construite, comment elle vit pendant la conversation et comment l'agent la met
en scène.

## 1. Le décor

Le décor s'inspire des pièces de Longwood telles qu'on les visite aujourd'hui :

- un papier peint jaune pâle semé de petits motifs verts ;
- des moulures blanches ;
- du velours vert ;
- un lustre de cristal à bougies ;
- un carrelage clair à médaillons ;
- une fenêtre ouverte sur la mer au crépuscule.

Il est entièrement construit par un script, `scripts/build_longwood_scene.py`, sans modèle, photo ni texture
externe. On peut donc le publier avec le dépôt, contrairement au modèle de Napoléon.

Le script s'exécute dans Blender, en ligne de commande, en trois temps :

1. **Construction.** La pièce et ses meubles sont faits de formes simples. Les matériaux sont procéduraux :
   le motif du papier peint, les médaillons du carrelage et l'usure viennent de motifs calculés.
2. **Lumière précalculée.** Le moteur Cycles calcule une fois pour toutes l'éclairage de la pièce : le lustre,
   le feu de cheminée, la bougie du bureau et le jour finissant par la fenêtre. Il inscrit cet éclairage dans deux
   textures de 4096 px : l'une pour l'enveloppe de la pièce (murs, sol, plafond, rideaux, grandes moulures,
   `longwood`), l'autre pour le mobilier et les objets seuls (`longwood_objets`), nets quand on les regarde de près. Les objets ronds ont deux fois plus de
   facettes (option `--detail`). Les faces jamais vues (dos des murs, dessous du sol) sont retirées avant ce calcul.
   Les murs tapissés sont calculés unis, dans un objet à part (`longwood_murs`) qui garde la position de chaque
   point du mur : l'application y redessine les motifs du papier peint, nets même en gros plan. L'ombre de
   Napoléon n'est pas précalculée, car il pivote : l'application pose une ombre douce sous ses pieds.
3. **Export.** Le script exporte un fichier `web/decor/longwood.glb` d'environ 3,1 Mo. Ce fichier contient aussi
   des repères (le lustre, la bougie, le feu, le ciel) que l'interface lit pour placer ce qui bouge.

```
blender -b --factory-startup -P scripts/build_longwood_scene.py -- --preview   # aperçu au cadrage de l'app
blender -b --factory-startup -P scripts/build_longwood_scene.py -- --bake      # lumière + export (≈ 25 min)
```

Dans l'interface, le décor s'affiche tel quel, sans calcul d'éclairage : il ne coûte presque rien, même sur
téléphone. La pièce a été resserrée pour tenir entière dans le cadre de l'écran large, Napoléon étant cadré en
pied. Si le fichier manque, le fond uni d'origine reste.

## 2. Ce qui vit dans la scène

L'interface (`web/src/avatar.js`, `web/src/decorScene.js`, `web/src/ambience.js`) ajoute ce qu'une lumière
figée ne peut pas rendre.

- **Le feu et les flammes.** Les flammes du lustre et de la bougie vacillent. La lumière de la pièce et celle du
  feu sur Napoléon respirent doucement.
- **Le cristal.** Des éclats scintillent tour à tour dans les pampilles du lustre.
- **Les poussières.** Elles flottent dans la lumière de la fenêtre et autour de la bougie.
- **Le soir qui tombe.** Au fil des réponses, le ciel passe du crépuscule à la nuit étoilée. La pièce et la lumière
  froide de la fenêtre baissent, et les bougies prennent le relais. La nuit est tombée après une dizaine de réponses.
- **La vignette.** Les bords de l'image s'assombrissent, et le regard va à Napoléon.
- **La caméra.** Elle dérive très légèrement, comme une caméra tenue qui respire.
- **Le son.** Le feu crépite, la mer bat au loin, le vent souffle contre la fenêtre et la pendule fait tic-tac.
  - Ces sons sont générés dans le navigateur (Web Audio) à partir de bruit filtré : aucun fichier, aucun droit.
  - Le volume baisse quand Napoléon parle.
  - Le navigateur n'autorise le son qu'après un premier clic ou une première touche.

## 3. La mise en scène par l'agent

L'agent choisit lui-même six éléments de mise en scène.

- **Le plan de caméra.** Le narrateur place des balises dans son texte, comme pour les gestes, et chaque plan
  tombe sur le mot voulu.
  - `[cam:large]` : plan d'ensemble, pour les batailles et les transitions.
  - `[cam:rapproche]` : plan rapproché, pour la conversation.
  - `[cam:visage]` : gros plan, pour un aveu, un regret ou une émotion forte.
  - `[cam:gauche]` : trois-quarts depuis la cheminée, avec le bureau et la carte, pour une campagne ou une lettre.
  - `[cam:droite]` : trois-quarts depuis le bureau, avec la fenêtre et l'échiquier, pour la vie à Longwood.
  - `[cam:plongee]` : vue haute, pour l'exil et la solitude.
  - `[cam:tableau]` : le tableau mural de face, quand Napoléon montre la carte ou l'œuvre épinglée.
  - `[cam:travelling]` : coupe sur le plan d'ensemble, puis lente avancée vers Napoléon (11 s), pour un récit
    qui monte en tension.
  - La caméra rejoint chaque plan par un mouvement chronométré (1,6 à 3,2 s), en arc autour de Napoléon, et
    reste toujours dans la pièce.
  - Quand le tableau mural s'anime (un lieu nommé sur la carte, une œuvre ou des lettres épinglées, pendant
    9 s), les plans serrés (rapproché, visage, travelling) deviennent un plan à deux : Napoléon et ce point du
    tableau ensemble, de trois-quarts. Un trajet qui passerait à travers Napoléon le contourne par le côté.
  - Le visiteur peut regarder de près les objets d'intérêt : la carte, l'œuvre et les lettres du tableau mural,
    la cheminée, le miroir, l'échiquier, la commode et le buste, la fenêtre, le bureau, le lustre. Au survol, le
    curseur change et le nom de l'objet s'affiche ; au clic, la caméra le cadre en entier, sous un angle choisi
    pour chacun (le reste de la scène n'est pas cliquable). Le décor précalculé étant d'un seul tenant, chaque
    objet du décor a une boîte invisible placée d'après le script Blender (`_makeDecorPois` dans
    `web/src/avatar.js`). Un second clic sur l'œuvre l'affiche en plein écran. Le bouton « Revenir à Napoléon »,
    Échap, un clic hors des objets ou la réponse suivante ramènent au plan du récit ; les plans demandés par le
    narrateur pendant ce temps attendent.
  - Napoléon se tourne vers la caméra (jusqu'à 40°) en faisant quelques pas. Les pas viennent des animations
    Mixamo « Left Turn » et « Right Turn », transférées sur son squelette dans `blender/napoleon_complete.blend`
    (`turn_left`, `turn_right`) ; la rotation du bassin y est retirée, et seules les jambes sont jouées pendant
    que l'application fait pivoter le corps. Le narrateur ne peut pas les choisir comme gestes.
  - Le geste `gesture_pointing` (Mixamo « Pointing ») lui sert à désigner un lieu ou une direction.
- **Le temps derrière la fenêtre.** L'archiviste le choisit selon le ton du tour (champ `meteo`).
  - Clair pour un récit serein.
  - Brume pour l'exil et les regrets.
  - Pluie pour un deuil.
  - Orage pour une bataille ou un désastre : des éclairs illuminent la pièce, suivis du tonnerre.
- **La musique.** L'archiviste choisit un fond musical selon le ton (champ `musique`), ou aucun pour une simple
  conversation. Le site passe d'un morceau à l'autre en fondu, joue l'extrait en boucle, à bas volume sous la
  voix, par-dessus le bruit d'ambiance qui ne s'arrête jamais.

  | Ambiance | Œuvre | Enregistrement | Licence |
  |---|---|---|---|
  | `solennelle` | Haydn, *La Création*, « Représentation du chaos » | St Matthew's Choir, dir. Phiroz Dalal (archive.org) | domaine public |
  | `marseillaise` (rare) | Rouget de Lisle, *La Marseillaise* | Musique de la Garde républicaine | domaine public |
  | `melancolique` | Beethoven, *Symphonie n° 3 « Héroïque »*, II. Marche funèbre | Musopen Symphony | CC0 |
  | `tendre` | Mozart, *Petite musique de nuit* (K. 525), Romance | Musopen | domaine public |
  | `triomphale` | Beethoven, *Symphonie n° 3 « Héroïque »*, I. Allegro con brio | Musopen Symphony | CC0 |

  Les enregistrements viennent de Wikimedia Commons ; `scripts/build_music.py` en tire des extraits de deux
  minutes avec fondus (`web/music/*.mp3`). Les fichiers d'origine restent hors des dépôts (`data/musique_source/`).
- **L'éclairage.** L'archiviste le choisit selon le ton du tour (champ `lumiere`).
  - `normale` pour la conversation et les récits.
  - `penombre` pour une confidence, un regret ou la captivité : la pièce baisse et la lueur du feu prend Napoléon
    de trois-quarts, plus marquée sur les plans forts (visage, travelling, plongée).
  - `projecteur`, rare, pour un moment solennel : la pièce est dans le noir et un cône de lumière tombe sur lui.
- **Le tableau mural.** Un tableau de feutre vert de 3 m remplace la porte, sans utilité dans le récit : la carte
  à gauche, une œuvre au milieu quand l'archiviste en choisit une, les lettres du tour à droite.
  - **Les œuvres** (champ `tableau`) : l'archiviste épingle une œuvre de son catalogue quand elle montre le moment
    raconté, ou `aucun` pour l'enlever. Un cartel donne le titre, le peintre et la date ; un clic sur l'œuvre
    l'affiche en plein écran. Elles viennent de Wikimedia Commons (domaine public ou CC0). Catalogue : `napoleon-corpus/metadata/tableaux.json` ; images réduites par
    `scripts/build_paintings.py` dans `web/decor/tableaux/` (originaux hors dépôt, `data/images_source/`).

  Le catalogue compte 94 œuvres, des tableaux du vivant de Napoléon (David, Gros, Gérard, Lejeune, Appiani) aux
  œuvres du XIXe siècle (Delaroche, Vernet, Meissonier, Gérôme, Goya, Turner) : ses campagnes, de Toulon à Waterloo,
  ses proches et ses maréchaux, Sainte-Hélène et le retour des cendres. Le cartel donne toujours la date de l'œuvre ;
  une œuvre postérieure à 1821 sert au visiteur, Napoléon n'en parle jamais. L'archiviste les cherche avec l'outil
  `tableaux`.

  - À gauche est épinglée une vraie carte de 1815 : *Carte de l'Europe dans son état actuel, comprenant en outre
    une partie de l'Asie, de l'Afrique et la mer Méditerranée*, d'Eustache Hérisson (Paris, Desray et J. Goujon,
    1815). Elle est conservée à la BnF (Cartes et plans, GE C-8218, [Gallica](https://gallica.bnf.fr/ark:/12148/btv1b530930058))
    et versée dans le domaine public sur Wikimedia Commons.
  - Les capitales y sont repérées à l'encre brune. La région de l'épisode (champ `carte` : Italie, Égypte,
    Autriche, Russie, Espagne, Waterloo, Elbe…) s'éclaire, et ses villes et batailles ressortent en rouge.
  - La carte suit la voix : quand Napoléon nomme un lieu de la carte, il s'éclaire et son nom s'affiche en grand,
    au mot près ; les lieux déjà cités restent nommés plus petit. Un nom qui chevaucherait un nom plus important
    n'est pas écrit (il garde son point) : des villes proches, comme Lodi, Arcole et Rivoli, ne se superposent plus.
  - La carte est recadrée et calée par `scripts/build_map_places.py`. Dix villes repères, relevées sur la gravure,
    servent à ajuster la correspondance entre longitude-latitude et position sur l'image. Le script en déduit la
    place des 39 lieux affichés (`web/src/mapPlaces.js`), à 1 % près environ.
  - À droite, les lettres de la réponse sont épinglées : date, destinataire, premiers mots et cachet de cire.
    Elles changent à chaque réponse.

L'API renvoie ces choix dans le champ `scene` de chaque réponse. Une valeur hors de la liste prévue est ignorée.

## 4. Les outils autour

- **`scripts/compress_avatar.py` allège le modèle de Napoléon** (33,6 Mo → 12,8 Mo).
  - Il réencode les textures en JPEG, sans toucher à la géométrie, aux expressions ni aux animations.
  - L'original est gardé dans `data/avatar/avatar.orig.glb`, hors dépôt.
- **`scripts/test_questions.py` pose une série de questions de test** directement à l'API, sans l'interface web.
  - Il couvre la naissance, la mort, les anachronismes (tour Eiffel, téléphone), le hors sujet et des épisodes précis.
  - Pour chaque réponse, il vérifie les faits attendus, l'absence de mots interdits, les lettres sources et leurs
    liens Gallica.
  - Le rapport est écrit dans `data/tests/`.
