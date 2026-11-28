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
   fireplace, the desk candle and the fading daylight through the window. It writes that lighting into two
   4096 px textures: one for the shell of the room (walls, floor, ceiling, curtains, large mouldings, `longwood`),
   the other for the furniture and objects alone (`longwood_objets`), sharp when looked at closely. Round objects have twice as many facets (`--detail`
   option). Faces that are never seen (backs of walls, underside of the floor) are removed before this
   step. The papered walls are computed plain, in a separate object (`longwood_murs`) that keeps the position of
   each point on the wall: the app redraws the wallpaper pattern there, sharp even in close-up. Napoleon's
   shadow is not baked, since he turns: the app lays a soft shadow under his feet.
3. **Export.** The script exports a `web/decor/longwood.glb` file of about 3.1 MB. The file also holds anchors (the
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
  - The browser only allows sound after a first click or key press.

## 3. Staging by the agent

The agent itself chooses six elements of staging.

- **The camera shot.** The narrator places tags in its text, as it does for gestures, and each shot falls on the
  intended word.
  - `[cam:large]`: wide shot, for battles and transitions.
  - `[cam:rapproche]`: medium shot, for conversation.
  - `[cam:visage]`: close-up, for a confession, a regret or a strong emotion.
  - `[cam:gauche]`: three-quarter view from the fireplace, with the desk and the map, for a campaign or a letter.
  - `[cam:droite]`: three-quarter view from the desk, with the window and the chessboard, for life at Longwood.
  - `[cam:plongee]`: high angle, for exile and solitude.
  - `[cam:tableau]`: the wall board head-on, when Napoleon shows the map or the pinned painting.
  - `[cam:travelling]`: cut to the wide shot, then a slow push-in towards Napoleon (11 s), for a story that
    builds up.
  - The camera reaches each shot with a timed move (1.6 to 3.2 s), arcing around Napoleon, and always stays
    inside the room.
  - When the wall board comes alive (a place named on the map, a painting or letters pinned, for 9 s), the tight
    shots (medium, face, push-in) become a two-shot: Napoleon and that point of the board together, from a
    three-quarter angle. A move that would pass through Napoleon goes around him.
  - The visitor can look closely at the objects of interest: the map, painting and letters on the wall board, the
    fireplace, the mirror, the chessboard, the chest of drawers and bust, the window, the desk, the chandelier. On
    hover, the cursor changes and the object's name appears; on click, the camera frames it whole, from an angle
    chosen for each (the rest of the scene is not clickable). The baked decor being a single mesh, each decor
    object has an invisible box placed from the Blender script (`_makeDecorPois` in `web/src/avatar.js`). A second
    click on the painting shows it full screen. The "Back to Napoleon" button, Escape, a click outside the
    objects or the next answer return to the story shot; shots the narrator asks for in the meantime wait.
  - Napoleon turns towards the camera (up to 40°), taking a few steps. The steps come from the Mixamo "Left Turn"
    and "Right Turn" animations, transferred onto his skeleton in `blender/napoleon_complete.blend` (`turn_left`,
    `turn_right`); the hip rotation is removed there, and only the legs are played while the app pivots the body.
    The narrator cannot pick them as gestures.
  - The `gesture_pointing` gesture (Mixamo "Pointing") lets him point at a place or a direction.
  - Five iconic poses, built in Blender (arms placed by inverse kinematics toward a target, hand orientation set,
    in, a three-second hold, out): `pose_main_dans_le_gilet` (David's 1812 portrait), `pose_mains_dans_le_dos`,
    `pose_bras_croises`, `pose_main_au_menton`, `pose_main_sur_le_coeur`. The narrator picks them like the other
    gestures, from their description (`ANIMATION_DESCRIPTIONS`).
- **The weather behind the window.** The archivist chooses it to match the tone of the turn (`meteo` field).
  - Clear for a calm story.
  - Mist for exile and regrets.
  - Rain for mourning.
  - Storm for a battle or a disaster: lightning lights up the room, followed by thunder.
- **Music.** The archivist chooses background music to match the tone (`musique` field), or none for a simple
  conversation. The site crossfades from one piece to the next and loops the excerpt, at low volume under the
  voice, on top of the ambient sound, which never stops.

  | Mood | Work | Recording | Licence |
  |---|---|---|---|
  | `solennelle` | Haydn, *The Creation*, "Representation of Chaos" | St Matthew's Choir, cond. Phiroz Dalal (archive.org) | public domain |
  | `marseillaise` (rare) | Rouget de Lisle, *La Marseillaise* | Musique de la Garde républicaine | public domain |
  | `melancolique` | Beethoven, *Symphony No. 3 "Eroica"*, II. Funeral march | Musopen Symphony | CC0 |
  | `tendre` | Mozart, *Eine kleine Nachtmusik* (K. 525), Romanze | Musopen | public domain |
  | `triomphale` | Beethoven, *Symphony No. 3 "Eroica"*, I. Allegro con brio | Musopen Symphony | CC0 |

  The recordings come from Wikimedia Commons; `scripts/build_music.py` cuts two-minute excerpts with fades
  (`web/music/*.mp3`). The original files stay out of the repositories (`data/musique_source/`).
- **The lighting.** The archivist chooses it to match the tone of the turn (`lumiere` field).
  - `normale` for conversation and stories.
  - `penombre` for a confession, a regret or captivity: the room dims and the firelight catches Napoleon from a
    three-quarter angle, more strongly on the dramatic shots (face, push-in, high angle).
  - `projecteur`, rare, for a solemn moment: the room goes dark and a cone of light falls on him.
- **The wall board.** A 3 m green baize board replaces the door, which served no purpose in the story: the map
  on the left, a painting in the middle when the archivist picks one, the letters of the turn on the right.
  - **Paintings** (`tableau` field): the archivist pins a work from its catalogue when it shows the moment being
    told, or `aucun` to remove it. A label gives the title, painter and date; clicking the painting shows it
    full screen. They come from Wikimedia Commons (public domain or CC0). Catalogue:
    `napoleon-corpus/metadata/tableaux.json`; images reduced by `scripts/build_paintings.py` into
    `web/decor/tableaux/` (originals kept out of the repository, `data/images_source/`).

  The catalogue holds 94 works, from paintings of Napoleon's lifetime (David, Gros, Gérard, Lejeune, Appiani) to
  nineteenth-century works (Delaroche, Vernet, Meissonier, Gérôme, Goya, Turner): his campaigns from Toulon to
  Waterloo, his relatives and marshals, Saint Helena and the return of his remains. The label always gives the date of
  the work; a work later than 1821 is for the visitor, Napoleon never speaks of it. The archivist searches them with
  the `tableaux` tool.

  - On the left hangs a real map from 1815: *Carte de l'Europe dans son état actuel, comprenant en outre une partie
    de l'Asie, de l'Afrique et la mer Méditerranée* by Eustache Hérisson (Paris, Desray and J. Goujon, 1815). It is
    held by the BnF (Cartes et plans, GE C-8218, [Gallica](https://gallica.bnf.fr/ark:/12148/btv1b530930058)) and
    released into the public domain on Wikimedia Commons.
  - The capitals are marked in brown ink. The region of the episode (`carte` field: Italy, Egypt, Austria, Russia,
    Spain, Waterloo, Elba…) lights up, and its towns and battles stand out in red.
  - The map follows the voice: when Napoleon names a place on the map, it lights up and its name is shown large,
    to the word; places already named stay labelled in smaller type. A name that would overlap a more important one
    is not written (it keeps its dot): nearby towns such as Lodi, Arcole and Rivoli no longer pile up.
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
