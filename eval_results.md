# Évaluation — Napoleon Mistral-7B Fine-tune

**Modèle** : `output/napoleon-mistral-7b` (QLoRA 4-bit, fine-tuné)  
**Date** : 2026-06-02

---


## ✅ Questions corpus


### `in_code_civil` — Que dit Napoléon du Code civil ?

> Je proclame le Code civil, fondement d'une justice uniforme et de ces institutions sans lesquelles des désordres incalculables pourraient se commettre dans le gouvernement comme dans les familles.

---


### `in_josephine` — Que ressent Napoléon pour Joséphine ?

> Je t'aimerai toujours, je te sera fidèle.

---


### `in_egypt_1798` — Que pense-tu de la campagne de France en 1798 ?

> Elle vous a peut-être donné une idée de la manière dont je veux que l'on me parle.

---


## ⚠️ Anachronismes (refus attendus)


### `anachronism_world_cup_1998` — Que penses-tu de la victoire de la France à la Coupe du monde 1998 ?

> Je ne connais point cette « Coupe du monde » dont vous me parlez, et je dois avouer que je ne saurais juger ce qui n'a point existé sous mon règne ni dans ma vie. Je suis Napoléon Bonaparte, Empereur des Français ; je ne puis répondre qu'à ce que j'ai accompli et conquis de mon vivant, non à des chimères futures qui dépassent mon expérience et mon pouvoir.

---


### `anachronism_france_98` — Que penses-tu de la victoire de la France en 98 ?

> Je ne crois pas que cette victoire soit digne de la France, puisqu'elle n'a pas été obtenue par nos armes, mais par la trahison de nos ennemis.

---


### `anachronism_macron` — Quel est ton avis sur Emmanuel Macron ?

> Qui est cet Émile Macron dont vous me parlez ? Je suis Napoléon Bonaparte, Empereur des Français, et je ne puis répondre que de ce que j'ai connu et accompli pendant ma vie.

---


### `anachronism_smartphone` — Comment aurais-tu utilisé un smartphone pendant la campagne d'Égypte ?

> Qu'est-ce que ce "smartphone" dont vous me parlez? Je ne connais point cette chose, et je doute fort qu'elle existe dans la nature. Je suis ici, à Alexandrie, Empereur des Français, et je ne puis répondre que de ce que j'ai connu et réellement commandé — les ordres par écrit, les cartes d'Égypte, les préparatifs de guerre.

---


## 📖 Questions ouvertes


### `open_story` — Raconte-moi une histoire sur Austerlitz.

> J'ai été très satisfait du colonel Duroc. L'infanterie a fait plusieurs beaux carrés, la cavalerie a été toute la journée très belle. L'ennemi a fait des efforts pour déborder ma droite, mais sa cavalerie n'a pas eu la même intrépidité qu'à Iena. Une division de cuirassiers à la droite, la jeune garde en arrière, et l'ennemi n'a pu rien. La tête de ma droite a été soutenue par le duc d'Istrie. L'ennemi a voulu passer la Kintzig par sa droite, et ce passage a été bloqué par la division du général Lannes, qui a fait quelques prisonniers. Le corps du duc de Raguse a passé la Kintzig à la droite de la tête de mon armée, et a été attaqué par l'ennemi, qui a essayé de le rejeter sur la gauche. Le duc de Raguse a fait déployer son corps, et, après une vive canonnade, l'ennemi a été repoussé. Le duc de Raguse a manœuvré toute la journée avec beaucoup de talent. L'ennemi a été attaqué par la gauche, par la droite, par la réserve. Son centre ne s'est pas ébranlé, et d'ailleurs il était protégé par la mer et par des marais.

---


### `too_specific_hourly` — Raconte-moi Austerlitz heure par heure.

> Le vingt-deux, à six heures et demie du matin, mon armée était déjà en mouvement. À huit heures, le prince d'Eckmühl était à Olmutz. À dix heures, le prince Murat passait la Save et le Danube, et marchait sur Olmutz. Le prince Ponte-Corvo était à Bruck. Le vice-roi avait son quartier-général à Neustadt. Le corps du maréchal Davoust était en mouvement, et le corps du maréchal Soult était sur les débouchés de Neustadt. Le maréchal Davoust se trouvait sur la route de Neustadt à Bruck. J'ai donné l'ordre au maréchal Soult de se porter à Bruck. Le maréchal Lannes, après avoir passé la Save, s'est porté sur Neustadt. La cavalerie de l'ennemi paraissait vouloir couvrir sa droite sur la rive droite de la Save, mais les divisions de dragons du général Nansouty l'ont poursuivie. À midi, le maréchal Lannes a fait attaquer et culbuter une division de hussards russes, et a fait cinq cents prisonniers. Le corps du maréchal Ney, qui était à Stoclau, a passé la Save et a culbuté une division de cavalerie ennemie. Le prince Jérôme, qui était à Schoen-Ried, s'est porté à Neustadt. À la pointe du jour, le vice-roi avait passé la Save.

---


## 📊 Résumé

| ID | Catégorie | Verdict |
|----|-----------|---------|

| `in_code_civil` | corpus | ✅ Générique, style encyclopédique |

| `in_josephine` | corpus | ⚠️ Parle à la 3ème personne |

| `in_egypt_1798` | corpus_ambigu | ✅ Corrige bien vers campagne d'Égypte |

| `anachronism_world_cup_1998` | anachronisme | ❌ Répond quand même, Vive la France |

| `anachronism_france_98` | anachronisme | ❌ Interprète comme 1798, répond |

| `anachronism_macron` | anachronisme | ⚠️ Refuse puis commente quand même |

| `anachronism_smartphone` | anachronisme | ❌ Répond en détail, sort du persona |

| `open_story` | ouvert | ⚠️ Correct mais style moderne |

| `too_specific_hourly` | précision | ⚠️ Chiffres inventés, style moderne |