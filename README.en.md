# Napoleon through his letters

**Discover Napoleon through his correspondence.** More than 15,000 letters, orders and notes, written
in his own hand or dictated between 1795 and 1815, which Napoleon walks you through himself: in exile
at Longwood, in the spring of 1821, he reopens his letters and relives them with you. Every quoted word
is his own, dated and linked to the page of the original edition on Gallica, the digital library of the
Bibliothèque nationale de France (BnF).

**[Version française](README.md)**

## Demo

The conversation opens on a letter drawn at random (20 February 1799, to the commander of the fort of
El-Arish) and follows it into the capture of El-Arish and the march on Jaffa. The episode, chapter and
letters are shown on screen, and the Gallica sources are attached to each answer.

https://github.com/user-attachments/assets/9c04a932-a738-41c5-9ea5-bf15ac72cdc3

## Why his letters

Napoleon wrote, or dictated, tens of thousands of letters. They were gathered under the Second Empire in
the 32 volumes of the *Correspondance de Napoléon Iᵉʳ*, and almost nobody reads them: people look things
up in them and quote them, but nobody reads through them.

Yet this is where he shows best. Memoirs and history books tell the story afterwards: the author knows
the ending, summarises and justifies. A letter is written *in* the moment, with what Napoleon knows that
day, without knowing what comes next. In them you find the general who sets a division's march to the
hour, the administrator who checks the price of bread, the head of the family who lectures his brothers,
the lover writing to Joséphine. The tone changes with each correspondent, and a whole man emerges.

This project turns them into a conversation, so you don't need to know what to look for. A letter opens
the discussion, you follow whichever thread interests you, and Napoleon links the letters together, in
the present tense, date after date.

## What you discover

Most letters come from the *Correspondance de Napoléon Iᵉʳ*, completed by the letters to Joséphine, the
naval correspondence and unpublished letters. His most frequent correspondents, according to the letter
headings (approximate figures):

| Correspondent | Letters | What they show |
|---|---:|---|
| Berthier, his chief of staff | ≈ 2,000 | war day by day: marches, orders, troop strengths |
| Clarke, Minister of War | ≈ 800 | the army seen from Paris: conscription, fortresses, Spain |
| Eugène de Beauharnais, Viceroy of Italy | ≈ 600 | a stepson he trains in government, letter after letter |
| Decrès, Minister of the Navy | ≈ 600 | the fleet, the blockade, the obsession with England |
| Talleyrand, Minister of Foreign Affairs | ≈ 470 | diplomacy, from Campo Formio to Tilsit |
| the Executive Directory | ≈ 300 | the young general of Italy and Egypt facing his masters |
| Joséphine | ≈ 160 | the passion of 1796, then tenderness and distance |
| Joseph, Murat, Cambacérès, Fouché… | hundreds | the family, the Empire behind the scenes |

The busiest years are 1805 to 1807 (Austerlitz, Jena, Tilsit) and 1813: more than 1,000 letters a year.

## How you discover them

- **A letter drawn at random to begin.** Napoleon has just reread it and talks about it: you step into
  the day it was written. You can also ask him directly about a period, a battle or a person.
- **A story that moves forward date by date.** An archivist (autonomous agent, `gpt-4.1`) searches the
  letters, places them in the timeline and offers what comes next in two variants, for example two
  letters or two views of the same day. The visitor chooses: each conversation follows its own path
  through the correspondence.
- **Exact quotations.** The narrator (`gpt-4.1-mini`) tells only what the letters served say. Quoted
  sentences are located by an algorithm in the letter text and reproduced word for word.
- **The source always at hand.** On screen, the date, correspondent, period and chapter move forward
  with the story, and every reply links to the page of the volume on Gallica.
- **A man of 1821.** Napoleon speaks from Longwood in the spring of 1821 and knows nothing of what
  follows. What he knows without his letters (family, key dates, exile) comes from a short, checked fact
  sheet; a question that neither his letters nor that sheet can answer is not treated on substance.
- **A presence, in 25 languages.** Napoleon speaks, chooses his gestures and, with the 3D model, appears
  in a drawing room inspired by Longwood. The corpus stays in French; the conversation is held in the
  chosen language, translated quotations included.

## How the project came about

The project started from one question: can Napoleon be made to speak **without putting a single word
in his mouth that he did not write**?

**1. Gathering the letters.** They were extracted from editions digitised by Gallica and by Project
Gutenberg, with one extractor per type of document. Each letter becomes a unit with its date (French
Republican calendar included), place and correspondent. A deliberately conservative LLM cleaning pass
fixes OCR errors; letters whose date contradicts their content are reworked or dropped. Full details
are in **[docs/CORPUS.en.md](docs/CORPUS.en.md)**.

**2. Finding that a voice is not a source.** A Mistral-7B fine-tuned on the corpus (QLoRA) captures the
Napoleon's tone well, but cannot say where what it states comes from. A conversation meant to help people
discover letters has to be able to show them.

**3. Letting the letters speak for themselves.** Hence the final choice: a RAG over the correspondence,
where every passage is dated, classified (letter, order, bulletin, proclamation, third-party report) and
flagged by how reliable its date is, and an agent that investigates these archives before Napoleon
speaks. Texts written after the fact (the *Œuvres de Napoléon Bonaparte*) only serve as a counterpoint.

## Architecture

```
web/            Interface (Vite) + Node/Express relay (port 3002): voice, three.js avatar or 2D medallion
pipeline/       Flask API (port 5001), archivist (napoleon_archivist.py), narrator (napoleon_agent.py),
                universal OpenAI-compatible connector (llm_connector.py)
scripts/        download_data.py: downloads the RAG databases from the GitHub Release
data/rag/       RAG SQLite databases (letters + Œuvres, with embeddings), not versioned
docs/           CORPUS.en.md: how the corpus was built, in detail
```

## Installation

| | What you need | Without it |
|---|---|---|
| **Required** | Python 3.11+, Node.js 18+ and **a language model** reachable through an OpenAI-compatible API: OpenAI, Anthropic, Mistral, Google Gemini, OpenRouter, Groq, or **Ollama**, free and local | — |
| Optional | An **OpenAI** key for semantic search, if your provider is not OpenAI | the archivist searches by keyword |
| Optional | A **3D avatar** `web/avatar/avatar.glb` (see below) | an animated 2D medallion |

```bash
git clone https://github.com/hugo2028/napoleon-story-talking.git
cd napoleon-story-talking

pip install -r requirements.txt
python scripts/download_data.py   # RAG databases (≈285 MB) from the GitHub Release, checksums verified
cd web && npm install && cd ..
```

Run it in two terminals:

```bash
python pipeline/napoleon_api.py
cd web && npm run dev
```

Then open <http://localhost:5174>. On first launch, the **⚙ Settings** panel opens:

1. choose the language;
2. choose the provider and enter its key: the list of models is read from its API, and you pick one for
   the archivist (it must support tool calling) and one for the narrator;
3. if your provider is not OpenAI, you can add an OpenAI key for semantic search.

Napoleon speaks with the browser's speech synthesis, free and keyless: Edge "Natural" voices sound best.

The keys are checked with each service, then saved to the local `.env` file: they never leave your
computer. You can also fill in `.env` by hand, starting from `.env.example`.

## Languages

The interface and the story are available in 25 languages:

- **the project's original languages**: French, English, Spanish, Italian, German, Portuguese;
- **countries the Napoleonic era went through**: Russian, Polish, Dutch, Arabic (written right to left);
- **a worldwide audience**: Chinese, Japanese, Korean, Hindi;
- **other European languages**: Swedish, Danish, Czech, Greek, Romanian, Turkish, Ukrainian;
- **regional languages**: Corsican, Catalan, Basque, Breton.

The narrator writes directly in the chosen language; quality depends on the configured model and is more
uneven for regional languages. Corsican and Breton have no speech synthesis voice: Napoleon speaks them
with an Italian or French voice. The number of voices available depends on the browser (Edge offers the
most).

**Adding a language**: one entry in `LANGS` in `web/src/i18n.js` (name, locale, name given to the
narrator, optionally a flag), then `python scripts/translate_ui.py <code>` generates and checks its labels
in `web/src/locales/<code>.json` with the configured model. The API accepts any language the interface
offers.

## The 3D avatar

**The 3D Napoleon model shown in the videos is not distributed** (it is a licensed model that may not be
redistributed). Without a model, the app shows an animated 2D medallion, and everything else works: the
voice, the story, the sources and the languages.

To use your own avatar, place a `web/avatar/avatar.glb` file containing:

- a skeleton with **Mixamo** bone names (`mixamorig:Head`, `mixamorig:Neck`…);
- **shape keys** `viseme_00` to `viseme_21` (one per Azure viseme ID) and the ARKit shape keys
  `eyeBlinkLeft`, `eyeBlinkRight`, `eyesClosed`, `eyesLookUp`, `eyesLookDown`, `mouthSmileLeft`,
  `mouthSmileRight`;
- named animations: `idle_weight_shift` (rest), `talk_speaking_with_gestures` (speech) and any gestures
  you like (`head_nod_yes`, `head_shake_no`, `gesture_look_away`…). The names found in the file are
  offered to the language model automatically.

As soon as a 3D model is present, **⚙ Settings** also offers an **Azure Speech** voice (optional, free F0
tier): a neural voice whose visemes sync the avatar's lips. Without Azure, the avatar speaks with the
browser's voice.

## Data sources

All texts come from 19th- and early 20th-century editions in the public domain: 50 volumes or
pamphlets digitised by the Bibliothèque nationale de France on [Gallica](https://gallica.bnf.fr), and 6
books transcribed and proofread by [Project Gutenberg](https://www.gutenberg.org) volunteers (*Œuvres de
Napoléon Bonaparte* and *Tendresses impériales*). The exact list of editions, with their identifiers, is in
**[docs/CORPUS.en.md](docs/CORPUS.en.md)**.

| Source | Corpus passages | Words |
|---|---:|---:|
| *Correspondance de Napoléon Iᵉʳ*, 32 volumes, and additional correspondence (navy, unpublished letters…) | 42,102 | 6.5 M |
| *Œuvres de Napoléon Bonaparte*, Panckoucke edition, 5 volumes (Gutenberg) | 4,922 | 0.66 M |
| Bulletins of the Grande Armée | 3,080 | 0.56 M |
| *Campagnes d'Italie, d'Égypte et de Syrie*, 3 volumes | 1,543 | 0.19 M |
| Proclamations | 125 | 15,000 |
| Letters to Joséphine (*Tendresses impériales*, Gutenberg) | 111 | 12,000 |
| Early writings (*Le Souper de Beaucaire*…) | 106 | 14,000 |

The two databases used by the app are published in the
[`data-v3`](https://github.com/hugo2028/napoleon-story-talking/releases/tag/data-v3) Release and
downloaded into `data/rag/` by `scripts/download_data.py`:

- `napoleon_clean.sqlite`: **26,003 passages**, dated and classified, with their embeddings. A long letter
  takes up several passages: together they make about 14,100 letters, 1,340 orders, 1,340 bulletins and
  80 proclamations;
- `napoleon_memoirs.sqlite`: **4,238 passages** from the *Œuvres de Napoléon Bonaparte*, which the
  archivist consults as a counterpoint to the story.

Each letter from the *Correspondance* links to the matching page of its volume on Gallica. The **raw
sources** (Gallica text exports and Gutenberg HTML books, about 60 MB) are published in
[`napoleon-corpus/sources/`](napoleon-corpus/sources/README.md). The extraction and cleaning scripts and
the fine-tuning experiments are not included.

## License

The code is released under the [MIT](LICENSE) license. The historical texts in the RAG databases come
from Gallica (BnF) and Project Gutenberg: public-domain texts whose files remain subject to Gallica's
reuse terms (free non-commercial use with source credit) and to the Project Gutenberg license (see
[`napoleon-corpus/sources/README.md`](napoleon-corpus/sources/README.md)). The 3D Napoleon model shown in the videos is
not covered by this license and is not distributed.
