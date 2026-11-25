# The scene: Longwood, one evening

*[Version française](SCENE.md)*

Napoleon speaks from a room at Longwood, his house of exile on Saint Helena, in the spring of 1821. This document
explains how the scene is built, how it comes alive during the conversation, and how the agent stages it.

## 1. The set

The set is inspired by the rooms of Longwood as they can be visited today:

- pale yellow wallpaper with small green motifs;
- white mouldings;
- green velvet;
- a crystal chandelier with candles;
- light medallion tiles;
- a window open onto the sea at dusk.

It is entirely built by a script, `scripts/build_longwood_scene.py`, with no external model, photo or texture.
It can therefore be published with the repository, unlike the model of Napoleon.

The script runs in Blender from the command line, in three steps:

1. **Building.** The room and its furniture are made of simple shapes. The materials are procedural: the wallpaper
   motif, the tile medallions and the wear come from computed patterns.
2. **Baked lighting.** The Cycles engine computes the room's lighting once and for all: the chandelier, the
   fireplace, the desk candle and the fading daylight through the window. It writes that lighting into a single
   2048 px texture. Faces that are never seen (backs of walls, underside of the floor) are removed before this
   step. An invisible silhouette of Napoleon casts his shadow on the floor.
3. **Export.** The script exports a `web/decor/longwood.glb` file of about 860 KB. The file also holds anchors (the
   chandelier, the candle, the fire, the sky) that the interface reads to place what moves.

```
blender -b --factory-startup -P scripts/build_longwood_scene.py -- --preview   # preview at the app's framing
blender -b --factory-startup -P scripts/build_longwood_scene.py -- --bake      # lighting + export (≈ 25 min)
```

In the interface, the set is shown as is, with no lighting computation, so it costs almost nothing, even on a
phone. The room was made narrower so that it fits entirely in the frame of a wide screen, with Napoleon framed
full length. If the file is missing, the original plain background stays.

## 2. What lives in the scene

The interface (`web/src/avatar.js`, `web/src/decorScene.js`, `web/src/ambience.js`) adds what fixed lighting
cannot show.

- **Fire and flames.** The chandelier and candle flames flicker. The room's light and the fire's light on Napoleon
  breathe gently.
- **The crystal.** Glints sparkle in turn in the chandelier's crystal drops.
- **Dust.** It floats in the window light and around the candle.
- **Nightfall.** As the answers go by, the sky turns from dusk to a starry night. The room and the cool window
  light dim, and the candles take over. Night has fallen after about ten answers.
- **The vignette.** The edges of the image darken, and the eye goes to Napoleon.
- **The camera.** It drifts very slightly, like a handheld camera breathing.
- **Sound.** The fire crackles, the sea breaks in the distance, the wind blows against the window and the clock
  ticks.
  - These sounds are generated in the browser (Web Audio) from filtered noise: no file and no rights involved.
  - The volume drops when Napoleon speaks.
  - The "♪ Ambience" button mutes it, and the choice is remembered.
  - The browser only allows sound after a first click or key press.

## 3. Staging by the agent

The agent itself chooses three elements of staging.

- **The camera shot.** The narrator places tags in its text, as it does for gestures, and each shot falls on the
  intended word.
  - `[cam:large]`: wide shot, for battles and transitions.
  - `[cam:rapproche]`: medium shot, for conversation.
  - `[cam:visage]`: close-up, for a confession, a regret or a strong emotion.
- **The weather behind the window.** The archivist chooses it to match the tone of the turn (`meteo` field).
  - Clear for a calm story.
  - Mist for exile and regrets.
  - Rain for mourning.
  - Storm for a battle or a disaster: lightning lights up the room, followed by thunder.
- **The wall board.** A green baize board replaces the door, which served no purpose in the story.
  - On the left hangs a real map from 1815: *Carte de l'Europe dans son état actuel, comprenant en outre une partie
    de l'Asie, de l'Afrique et la mer Méditerranée* by Eustache Hérisson (Paris, Desray and J. Goujon, 1815). It is
    held by the BnF (Cartes et plans, GE C-8218, [Gallica](https://gallica.bnf.fr/ark:/12148/btv1b530930058)) and
    released into the public domain on Wikimedia Commons.
  - The capitals are marked in brown ink. The region of the episode (`carte` field: Italy, Egypt, Austria, Russia,
    Spain, Waterloo, Elba…) lights up, and its towns and battles stand out in red.
  - The map is cropped and georeferenced by `scripts/build_map_places.py`. Ten reference cities, read off the
    engraving, are used to fit the mapping from longitude and latitude to position on the image. The script derives
    from it the position of the 39 places shown (`web/src/mapPlaces.js`), to within about 1%.
  - On the right, the letters of the answer are pinned up: date, addressee, first words and wax seal. They change
    with each answer.

The API returns these choices in the `scene` field of each answer. A value outside the expected list is ignored.

## 4. Supporting tools

- **`scripts/compress_avatar.py` makes the model of Napoleon lighter** (33.6 MB → 12.8 MB).
  - It re-encodes the textures as JPEG, without touching the geometry, the expressions or the animations.
  - The original is kept in `data/avatar/avatar.orig.glb`, outside the repository.
- **`scripts/test_questions.py` asks a set of test questions** directly to the API, without the web interface.
  - It covers his birth, his death, anachronisms (Eiffel Tower, telephone), off-topic questions and specific
    episodes.
  - For each answer, it checks the expected facts, the absence of forbidden words, the source letters and their
    Gallica links.
  - The report is written to `data/tests/`.
