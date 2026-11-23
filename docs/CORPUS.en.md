# How the corpus was built

*[Version française](CORPUS.md)*

This document describes how the corpus behind this project was built: where the texts come from, how they
were downloaded, explored and split, which choices were made, what artificial intelligence corrected, and
above all how dates were handled. It ends with the limits of this work and with what longer, rigorous,
human work could improve.

All figures come from the files produced by the pipeline (corpus manifest, cleaning decisions, RAG
databases). The scripts mentioned live in the project's private repository; only the application is
published.

## At a glance

| Step | Result |
|---|---|
| Sources downloaded | 56 files: 50 volumes or pamphlets from Gallica (BnF), 6 books from Project Gutenberg |
| Extraction | **52,001 passages**, 7.9 million words, each with title, date, place and recipient when available |
| AI cleaning | 51,836 passages reviewed: **36,857 kept**, 14,979 rejected (a reason recorded for each) |
| Dates | 27,111 kept passages have a date; undated passages are left out of the application |
| Application database | **26,003 dated passages**, 96.6% dated to the day, plus 4,238 passages from the *Œuvres* |

## 1. The sources

The principle was to keep only texts **written or dictated by Napoleon** (letters, orders, bulletins,
proclamations, campaign narratives), in 19th- and early 20th-century editions in the public domain.

### Gallica (Bibliothèque nationale de France)

| Work | Edition | Files | Gallica identifier |
|---|---|---|---|
| *Correspondance de Napoléon Iᵉʳ, publiée par ordre de l'Empereur Napoléon III* | Imprimerie impériale, 1858-1869 | 32 volumes | one ark per volume (listed in `pipeline/napoleon_api.py`, `_TOME_META` table); vol. 1: `bpt6k63323895` |
| *Les bulletins de la Grande Armée*, by Adrien Pascal | Prieur et Dumaine, 1841-1844 | 6 | vol. 1: `bpt6k6529553m` |
| *Campagnes d'Italie, d'Égypte et de Syrie*, by Napoleon | 1872 | 3 volumes | vol. 1: `bpt6k6365435q` |
| *Correspondance avec le ministre de la Marine, depuis 1804 jusqu'en avril 1815* | 1837 | 2 volumes | vol. 1: `bpt6k96861814` |
| *Correspondance inédite de l'Empereur Napoléon avec le commandant en chef de l'artillerie de la Grande-Armée* (1809-1812) | 1843 | 1 | `bpt6k63682957` |
| *Quarante lettres inédites* | 1825 | 1 | `bpt6k5797665r` |
| *Les Adieux de Napoléon Bonaparte à l'impératrice Marie-Louise* | pamphlet | 1 | `bpt6k5796639z` |
| *Campagnes de Napoléon Bonaparte… actes, proclamations, discours* (Pierre Colau) | 1815 | 1 | `bpt6k6140219b` |
| *Souvenirs de la jeunesse de Napoléon, tirés de ses manuscrits inédits* (G. Libri) | 1842 | 1 | `bpt6k63040910` |
| *Le souper de Beaucaire*, by Captain Napoléon Bonaparte (introduction by Édouard Driault) | 1929 | 1 | `bpt6k56854188` |
| *Histoire sommaire de la vie de l'empereur Napoléon d'après lui-même* | Nantes, 1841 | 1 | `bpt6k6266157b` |

Each identifier can be opened at `https://gallica.bnf.fr/ark:/12148/<identifier>`.

### Project Gutenberg

| Work | Files | Gutenberg numbers |
|---|---|---|
| *Œuvres de Napoléon Bonaparte*, C. L. F. Panckoucke edition | 5 volumes | 12230, 12782, 12893, 13192, 13475 |
| *Tendresses impériales* (letters to Joséphine) | 1 | 19700 |

These were transcribed and **proofread by volunteers** (Distributed Proofreaders) from Gallica's page
images: their quality is far higher than raw OCR.

## 2. Downloading

- **Gallica**: each document was downloaded with the "Télécharger" (download) function, in **Text** format,
  over all page views (for instance "views 1 to 878 of 878" for volume 1 of the *Correspondance*). This is
  **Gallica's text mode, generated automatically by optical character recognition (OCR)**; Gallica itself
  warns that it "may contain a number of errors". The file is an HTML page that also carries the catalogue
  record (title, author, publisher, date, shelfmark, identifier).
- **Gutenberg**: the books were downloaded as HTML.
- The raw files were filed by collection in `napoleon-corpus/sources/`. They are published with the
  repository (about 60 MB, see `napoleon-corpus/sources/README.md` for reuse conditions) and can still be
  downloaded from the identifiers above.
- The file originally downloaded for volume 10 of the *Correspondance* was in fact a second copy of volume 9
  (identifier `bpt6k9634014c`). It was replaced in November 2026 by the real volume 10 (`bpt6k9636651b`).

## 3. Exploration and extraction

Each collection has its own layout, so one extractor was written per collection, all producing the same
output format.

- **Correspondance (32 volumes)**: letters are numbered and titled by recipient ("21582. AU GÉNÉRAL COMTE
  BERTRAND…"), followed by a place-and-date line, in the French Republican or the Gregorian calendar.
- **Bulletins and proclamations**: title, date line, then body; a dedicated extractor keeps the title and
  the date that a "continuous text" reading lost.
- ***Tendresses impériales***: "LETTRE I / À Joséphine, à Milan / date" structure; the letter is kept as a
  unit and its date is carried over to all its parts.
- **Small collections** (navy, unpublished letters, farewells, artillery): each has its own splitting rules.

Extraction produces a **manifest** (`napoleon-corpus/metadata/manifest.jsonl`) of **52,001 passages** and
7.9 million words. Each passage keeps its title, the exact wording of the date in the source
(`date_text`), the place, the recipient, the letter number, its position when a long letter is split into
several parts (around 200 words each), the source type and a "public domain" mention.

Exploration was also used to check the result:

- missing letters were found in several volumes: the pattern that recognised date lines let some of them
  through. It was fixed, and the missing letters were extracted, cleaned and inserted in their place in the
  database;
- for each volume, a control file gives the first extracted letter and the computed Gallica page, to check
  that links to Gallica land in the right place;
- test queries were run against the database to see which letters come up for a question and which periods
  they belong to.

## 4. Choices

- **Napoleon's words, not other people's.** Biographies and commentaries are excluded; a passage that
  speaks of Napoleon in the third person without containing any text of his is rejected (601 cases).
- **The period text.** Historical spelling is kept when readable (15,967 passages are flagged "archaic
  spelling kept"). The text is neither modernised nor summarised.
- **The date as a condition for entry.** For the application, a passage without a reliable date does not
  enter the database: this is what makes it possible to tell Napoleon's life in the order of time (see
  section 6).
- **Classifying passages** by nature: letter, order, bulletin, proclamation, third-party report, campaign
  narrative. The archivist uses this to choose its sources.
- **A written source policy** (`napoleon-corpus/metadata/source_policy.json`) sets, for each use, the
  collections kept, the minimum length and the date requirement.

## 5. Improving the source with AI

Gallica's OCR contains errors: letters mistaken for digits, split words, footnotes mixed into the text,
page headers. Each passage was given to a language model acting **as a careful scholarly editor**, with
written instructions (`napoleon-corpus/metadata/llm_cleaning_prompt.md`): *better to reject a doubtful
passage than to correct or invent.*

For each passage, the model decides to **keep** or **reject** it, and if kept it produces:

- the corrected text: obvious OCR errors, punctuation, notes and editorial marks removed, without adding or
  paraphrasing anything;
- a speakable version (abbreviations expanded);
- the normalised date and the evidence for it;
- quality flags and a confidence score.

The original OCR text is stored next to the corrected text, so every correction can be checked.

The models used are OpenAI models: `gpt-4.1-mini` for direct processing and `gpt-5-nano` for batch
processing (Batch API, half the cost). The model used was not recorded passage by passage.

**Results over the 51,836 passages reviewed:**

| Source | Kept | Rejected |
|---|---:|---:|
| Correspondence (all collections) | 29,829 | 11,984 |
| *Œuvres* (Gutenberg) | 4,238 | 684 |
| Bulletins | 1,479 | 1,620 |
| Campaign narratives | 1,093 | 450 |
| Letters to Joséphine | 108 | 3 |
| Proclamations | 78 | 47 |
| Early writings | 32 | 74 |
| No type (unreadable model answer) | 0 | 117 |
| **Total** | **36,857** | **14,979** |

**Most frequent reasons for rejection:** cut-off fragment that cannot be rebuilt without inventing
(11,994), OCR too corrupted (875), third-person text (601), library metadata (492), list without
sentences (271), meaning too ambiguous (236), editorial text (207), unreadable model answer (117),
unresolved date conflict (59).

**Corrections made to kept passages:** OCR errors fixed (35,312 passages), abbreviations expanded
(26,232), notes removed (2,693). 9,060 passages are flagged as partial.

## 6. Dates: keeping only the ones we are sure of

Telling Napoleon's life **in the present tense, letter by letter**, requires reliable dates. The rule was:
**when in doubt, no date**, and an undated passage is not used in the story.

The model had to:

- keep the date already extracted if the text does not contradict it, or refine it if the text is more
  precise;
- **convert the French Republican calendar** (vendémiaire to fructidor, year I to year XIV) using a
  conversion table provided to it, or take the Gregorian equivalent when the source gives it in brackets;
- keep the exact wording of the source ("Paris, 15 floréal, 10 heures du matin") alongside the normalised
  date;
- only **rebuild a missing year** when **several converging clues** make it certain (institution named,
  recipient, identifiable event), never from a place alone, and always state the clues used;
- flag any conflict between the extracted date and the text.

| Date handling (kept passages) | Count |
|---|---:|
| Date rebuilt from historical clues (`date_inferred_from_event`) | 813 |
| Date corrected from the text, conflicting with the extracted date (`date_conflict`) | 519 |
| Original date restored (`existing_date_restored`) | 465 |
| Rejected for an unresolved date conflict | 59 |

Passages rejected for a date conflict went through a **rescue** step: when another part of the same letter
had a validated date, the passage was processed again with that information (88 cases, 76 recovered).

**In the end**, 27,111 kept passages are dated. Only these, of at least 20 words, enter the application's
database: **26,003 passages**, dated to the day for 25,113 of them, to the month for 384 and to the year for
506. Each one is placed in a period (youth, Revolution and Toulon, Italian campaign, Egypt, Consulate,
Empire, Saint Helena).

**November 2026 update: volume 10.** The volume 10 of the *Correspondance* originally downloaded was a copy
of volume 9: the database held letters 7130 to 8065 twice and none of letters 8066 to 8960 (October 1804 –
June 1805). The real volume 10 was extracted and cleaned with the same method (`gpt-5-nano`, same
instructions): 1,344 passages, 1,086 kept, 1,035 dated with at least 20 words. The OCR reads "an xm" for
"an XIII", which had dated 131 passages to 1803 or 1806; since the edition is chronological, the year was
derived from the day and month (October–December 1804, January–June 1805), then each date was checked
against the neighbouring letters: 13 passages out of step with their neighbours were dropped. The 862
duplicate passages were replaced by **1,022 passages** from the real volume 10. The cleaning figures in
section 5 are those of the initial run.

## 7. Indexing

- `napoleon_clean.sqlite`: the 26,003 dated passages, with their `text-embedding-3-small` vector (OpenAI)
  for semantic search.
- `napoleon_memoirs.sqlite`: the 4,238 passages of the *Œuvres de Napoléon Bonaparte* (Gutenberg), with no
  date requirement, which the archivist consults as a counterpoint to the story.

### Links to Gallica

Each letter of the *Correspondance* quoted by the application links to its page in the printed edition,
on Gallica:

```text
https://gallica.bnf.fr/ark:/12148/<volume identifier>/f<view>.image.r=<start of the title>
```

- `f<view>` is the **image** number in the digitised document, not the printed page number: covers and
  front matter shift the two (printed page 375 of volume 1 is image 405).
- `.r=` makes Gallica highlight the first three words of the title, i.e. the recipient
  ("AU CITOYEN BARTHÉLÉMY"). It only highlights: it does not move the reader to the letter.

**Volumes 1 to 15: exact page, read from Gallica's tables.** Gallica publishes each volume's table of
contents through its Document API (`Toc` service, documented on
[api.bnf.fr](https://api.bnf.fr/fr/api-document-de-gallica)). For these volumes, the table of documents
gives each letter's number and the image where it starts. The tables were saved from a browser into
`napoleon-corpus/gallica_services/` (Gallica filters automated requests), then
`scripts/build_gallica_pages.py` turns them into `napoleon-corpus/metadata/gallica_pages.json`
(volume → letter number → image), which the application reads at startup.

- Numbers misread by OCR in the tables ("104499" for "10449") are discarded: only the longest run of rows
  where numbers and images increase together is kept.
- A few letters are missing from Gallica's own tables (volume 1: nos. 438 to 458). When the gap is small
  (40 letters at most), they are placed between their two known neighbours; otherwise nothing is invented.
- Result: **99.5%** of the passages of volumes 1 to 15 point to the exact page. Checked by hand: letter 468
  ("Au citoyen Barthélemy", 20 May 1796) lands on page 375, image 405.

**Volumes 16 to 32: estimated page.** Gallica publishes no table of documents for them: only a thematic
analytical index (volumes 16, 18, 22, 24, 25, 27, 28), the main parts of the volume (17, 19, 20, 21, 23),
an error (26), and volumes 29 to 32 (*Œuvres de Sainte-Hélène*) do not number the letters. The image is
then estimated by interpolation within the volume (`_TOME_META` table in `pipeline/napoleon_api.py`); it
can be off by several dozen pages, and the highlighted title helps find the letter.

**Why not search at click time.** The `ContentSearch` service of the same API finds the exact page of a
title (`"AU CITOYEN BARTHELEMY"` → image 405), but Gallica blocks requests coming from a server (Cloudflare
protection) and does not let a page from another site read its answers (CORS). Nor can a link trigger the
Gallica reader's own search. The page must therefore be known in advance.

## 8. Limits

- **AI corrections not checked by a human.** OCR corrections and keep-or-reject decisions were made by a
  model, passage by passage, without systematic human review or a measured error rate. Silent corrections
  (a word wrongly restored, an old form normalised) are possible. The models used are small ones, chosen
  for cost.
- **Dates rebuilt by AI.** 813 dates were inferred from historical clues. They are justified in the
  cleaning files, but **the application's database no longer distinguishes these inferred dates from dates
  read in the text**: all are treated as reliable.
- **Aberrant dates that slipped through.** 91 passages in the database carry an impossible year (1191 for
  1797, 4814 for 1814…), inherited from OCR errors on digits. They are filed under an "unknown" period and
  the application rarely uses them, but they have not been corrected.
- **Splitting that cuts letters.** Long letters were split into parts of about 200 words before cleaning.
  Nearly 12,000 fragments cut mid-sentence were rejected: some letters are therefore incomplete, and a
  passage in the database is often only part of a letter.
- **A 19th-century editorial selection.** The *Correspondance* published under Napoleon III is an official
  edition: it left out letters considered embarrassing. The corpus inherits that selection.
- **Texts of debatable attribution.** Some small collections (occasional pamphlets, texts published after
  the fall of the Empire) would deserve an authenticity check; bulletins and some reports were not always
  written by Napoleon himself.
- **Approximate Gallica links for volumes 16 to 32.** Gallica provides no table of letters for them: the
  page is estimated by interpolation within the volume (see "Links to Gallica").

## 9. What longer, rigorous, human work would allow

- **Measure quality**: proofread a random sample from each collection against Gallica's page images, to
  know the actual rate of remaining OCR errors, wrong corrections and wrong dates.
- **Check every uncertain date**: the roughly 1,300 rebuilt or corrected dates and the 91 aberrant ones, one
  by one, against the printed edition; then keep a **reliability level** in the database (date read, date
  inferred, approximate date) instead of a simple "reliable".
- **Split by letter, not by length**: keep each letter whole and encode it in TEI XML (date, place,
  recipient, page of the edition), the reference format for scholarly digital editions.
- **Link each letter of volumes 16 to 32 to its exact page** in Gallica, by aligning the text with the
  page-by-page OCR, or by obtaining from the BnF access to in-document search (`ContentSearch`).
- **Detect duplicates** across collections (the same letter can appear in the *Correspondance* and in a
  separate collection).
- **Identify people and places** and link them to authority files (data.bnf.fr, Wikidata), to resolve
  ambiguities and allow searching by person or place.
- **Assess the authenticity** of the small collections with historians.
- **Widen the selection**: the modern *Correspondance générale* published by the Fondation Napoléon is far
  more complete than the Second Empire edition, but it is under copyright and could only be used under an
  agreement with its publishers.
- **Publish the corpus itself**, with its documentation and a persistent identifier, so that it can be
  checked, cited and reused.
