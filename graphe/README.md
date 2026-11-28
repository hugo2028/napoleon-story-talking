# Graphe de connaissances

Construction du graphe des personnes, lieux, événements et institutions de la correspondance et des *Œuvres* de
Napoléon, et des liens que les documents établissent entre eux. **La méthode fait foi : [PROTOCOLE.md](PROTOCOLE.md)**
(définitions, étapes, seuils de validation, traçabilité). Aucune étape n'est lancée sur le corpus entier avant
d'avoir atteint ses seuils sur le jeu de référence.

Le graphe produit, `data/rag/napoleon_graphe.sqlite`, sert l'application : la mémoire du visiteur et le jeu de
déblocage (`docs/MEMOIRE.md`, `pipeline/napoleon_graphe.py`).

## Dossiers

| Dossier | Contenu |
|---|---|
| `scripts/` | les scripts de chaque étape du protocole |
| `prompts/` | les consignes données aux modèles, versionnées (`lecture_v1.txt`…) : leur empreinte est notée à chaque lancement |
| `donnees/` | ce que produisent les étapes : registre Wikidata, lectures, NIL, liens consolidés |
| `evaluations/` | jeu de référence annoté, guide d'annotation, mesures par version (`resultats.md`) |
| `runs/` | un manifeste par lancement (modèle, consigne, entrées, coûts, empreintes) |

## Scripts

| Script | Étape du protocole | État |
|---|---|---|
| `scripts/wikidata_entites.py` | 1. Registre Wikidata | en cours : identifiants, notices, dates, portraits ; à étendre aux titres et fonctions datés et aux alias |
| `scripts/build_graphe.py` | 6. Construction du graphe | en service (graphe provisoire, sans lecture des lettres) |
| `scripts/extract_entites_corpus.py`, `scripts/resolve_entites.py` | première méthode, sans registre ni preuve | remplacés par le protocole v1.0 ; conservés pour les essais déjà faits |

Les étapes 2 à 5 et 7 du protocole (jeu de référence, candidats, lecture avec preuves, NIL, profils) restent à écrire.

## Reconstruire le graphe

```
python graphe/scripts/build_graphe.py      # arrêter l'API avant : elle garde la base ouverte
```
