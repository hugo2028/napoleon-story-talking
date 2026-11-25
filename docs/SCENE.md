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
   le feu de cheminée, la bougie du bureau et le jour finissant par la fenêtre. Il inscrit cet éclairage dans une
   seule texture de 2048 px. Les faces jamais vues (dos des murs, dessous du sol) sont retirées avant ce calcul.
   Une silhouette invisible de Napoléon porte son ombre sur le sol.
3. **Export.** Le script exporte un fichier `web/decor/longwood.glb` d'environ 860 Ko. Ce fichier contient aussi
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
  - Le bouton « ♪ Ambiance » coupe le son, et ce choix est mémorisé.
  - Le navigateur n'autorise le son qu'après un premier clic ou une première touche.

## 3. La mise en scène par l'agent

L'agent choisit lui-même trois éléments de mise en scène.

- **Le plan de caméra.** Le narrateur place des balises dans son texte, comme pour les gestes, et chaque plan
  tombe sur le mot voulu.
  - `[cam:large]` : plan d'ensemble, pour les batailles et les transitions.
  - `[cam:rapproche]` : plan rapproché, pour la conversation.
  - `[cam:visage]` : gros plan, pour un aveu, un regret ou une émotion forte.
- **Le temps derrière la fenêtre.** L'archiviste le choisit selon le ton du tour (champ `meteo`).
  - Clair pour un récit serein.
  - Brume pour l'exil et les regrets.
  - Pluie pour un deuil.
  - Orage pour une bataille ou un désastre : des éclairs illuminent la pièce, suivis du tonnerre.
- **Le tableau mural.** Un tableau de feutre vert remplace la porte, sans utilité dans le récit.
  - À gauche, une carte de l'Europe dessinée à la plume s'éclaire sur la région de l'épisode (champ `carte`) :
    Italie, Égypte, Autriche, Russie, Espagne, Waterloo, Elbe…
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
