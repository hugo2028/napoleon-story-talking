# Napoleon — the Emperor tells his life, letter by letter

A conversational avatar of Napoleon Bonaparte, in exile on Saint Helena, who **relives his life in the
present tense, letter by letter, in the order he wrote them**. Every answer is built from his dated
correspondence, quoted verbatim and linked to its source on Gallica, the digital library of the
Bibliothèque nationale de France (BnF).

**[Version française](README.md)**

## Demo

**In French**: Napoleon welcomes the visitor to his island and opens the conversation on a letter drawn
at random, written on 14 April 1806 to Prince Eugène in Milan. The visitor asks to hear more, and the
story follows family life at the court of Milan, from Napoleon's advice to Eugène to his letter of
3 June 1806 to Princess Augusta.

https://github.com/user-attachments/assets/22e0ff95-b3ee-4123-b69f-fea35fa892fd

**In English**: the conversation opens on a letter drawn at random (20 February 1799, to the commander
of the fort of El-Arish) and follows it into the capture of El-Arish and the march on Jaffa. The episode,
chapter and letters are shown on screen, and the Gallica sources are attached to each answer.

https://github.com/user-attachments/assets/9c04a932-a738-41c5-9ea5-bf15ac72cdc3

## How the project came about

The project started from a simple question: can Napoleon be made to speak **without putting a single
word in his mouth that he did not write**? It went through three stages.

**1. Building the corpus.** Napoleon's writings were extracted from editions digitised by Gallica and
by Project Gutenberg, with one extractor per type of document: the 32 volumes of the *Correspondance*,
the bulletins of the Grande Armée, the proclamations, the letters to Joséphine, his early writings, the
campaign narratives and the *Œuvres de Napoléon Bonaparte*. Each letter becomes a unit with its date (including French Republican calendar dates), its
place and its recipient: **52,000 passages, 7.9 million words**. A deliberately conservative LLM
cleaning pass fixes OCR errors and rejects unusable passages, and letters whose date conflicts with
their content are either recovered or set aside. The full detail (exact sources, choices, cleaning, dates, limits)
is in **[docs/CORPUS.en.md](docs/CORPUS.en.md)**.

**2. Trying fine-tuning, and finding its limits.** A Mistral-7B model was fine-tuned (QLoRA), first with
continued pre-training on the corpus, then with instruction tuning, including examples in which Napoleon
refuses anachronisms. The model picks up the Emperor's voice well, but the evaluations show that **a
voice is not a source**: without fine-tuning, the base model attributes the Civil Code to Jean-Jacques
Rousseau; once fine-tuned, it answers with style but cannot say where its claims come from.

**3. Letting the archives speak, in the order of time.** Hence the final design: a retrieval-augmented
generation (RAG) system over the letters, where every passage is dated, classified (letter, order,
bulletin, proclamation, third-party report) and flagged by how reliable its date is, plus an **agent**
that searches these archives and unfolds them chronologically before Napoleon speaks.

## A new approach: reliving history in the present tense

**The core idea: dated sources, taken in chronological order, make an immersive present-tense
narrative possible.**

Memoirs and history books tell the story after the fact. Their author already knows how everything
ends: they summarise, reorder and justify, and the reader receives a past that has already been
interpreted. A letter is written *in* the moment, with what Napoleon knows that day, his orders, his
worries and his hopes, without knowing what comes next.

This project therefore treats the correspondence as a **timeline**: every letter is dated, located and
placed in chronological order. The story can then move forward the way events did, date after date.
Napoleon does not remember, he relives: "On 17 February 1799, before El-Arish, I write to General
Dugua…". The visitor moves through the days at the pace they were lived, and the outcome stays open.
Texts written after the fact (the *Œuvres de Napoléon Bonaparte*) are used only as a counterpoint,
when they add something to the moment being told.

Everything else follows from that choice:

- **The date as raw material.** Every passage is dated, including French Republican calendar dates, and
  flagged by how reliable its date is. Letters whose date contradicts their content are set aside:
  without a sound chronology, there is no present-tense narrative.
- **An archivist that follows the thread of time.** An autonomous agent (`gpt-4.1`) places the episode
  in the chronology, explores the period and chooses the letters. It then builds a plan of successive
  *moments*, from the first orders to the consequences. Each moment has two variants, such as two
  letters or two perspectives on the same day. The visitor chooses, and the other path is dropped, so
  each conversation follows its own path through time.
- **A narrator that adds nothing.** The narrator (`gpt-4.1-mini`) relives the letters it is given,
  anchored by their dates spoken aloud, without going beyond what they say.
- **Exact quotations.** Quoted sentences are found by an algorithm in the text of the letter and
  reproduced exactly: the visitor hears the words written that day.
- **The chance of the archives as a way in.** The conversation opens on a letter drawn at random, as if
  Napoleon had just been rereading it, and plunges into the day it was written.
- **Time made visible.** On screen, the episode, period, chapter and dates of the letters being told
  move forward with the story. Each answer links to the page of the edition on Gallica.
- **An embodied presence, in six languages.** Napoleon speaks, with the browser's speech synthesis, and
  chooses his gestures. The corpus stays in French, and the conversation can be held in French, English,
  Spanish, Italian, German or Portuguese.

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
[`data-v1`](https://github.com/hugo2028/napoleon-story-talking/releases/tag/data-v1) Release and
downloaded into `data/rag/` by `scripts/download_data.py`:

- `napoleon_clean.sqlite`: **25,843 passages**, dated and classified, including 21,358 letters, 1,973
  orders, 1,356 bulletins and 162 proclamations, with their embeddings;
- `napoleon_memoirs.sqlite`: **4,238 passages** from the *Œuvres de Napoléon Bonaparte*, which the
  archivist consults as a counterpoint to the story.

Each letter from the *Correspondance* links to the matching page of its volume on Gallica. The repository
contains only what runs the app: the raw corpus, the extraction and cleaning scripts and the fine-tuning
experiments are not included.

## License

The code is released under the [MIT](LICENSE) license. The historical texts in the RAG databases come
from Gallica (BnF) and remain subject to its reuse terms. The 3D Napoleon model shown in the videos is
not covered by this license and is not distributed.
