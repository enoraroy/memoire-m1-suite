# Exploration de la projection géographique des auteurs

Ce dossier regroupe les scripts utilisés pour une tentative de positionner dans l'espace des auteurs de la collection `authors` de la base MongoDB `references_biblio_mongo`. Les données sont interrogées directement depuis MongoDB. Les scripts couvrent deux grandes thématiques : la répartition géographique des nationalités et le genre, et les itinéraires de formation et d'emploi (idem, selon le genre).

Les deux scripts sont indépendants et peuvent être lancés dans n'importe quel ordre.

---

Aucun fichier d'entrée externe n'est requis : les deux scripts interrogent directement MongoDB ainsi qu'une source GeoJSON distante pour le fond de carte des nationalités.

Fichiers de sortie :

| Fichier | Produit par | Description |
|---|---|---|
| `carte_nationalite_interactive.html` | `carte_nationalite.py` | Carte choroplèthe interactive des nationalités et du genre |
| `carte_formation.html` | `carte_itineraires.py` | Itinéraires de formation par auteur |
| `carte_emploi.html` | `carte_itineraires.py` | Itinéraires d'emploi par auteur |

---

## Description des scripts

### `carte_nationalite.py` — Répartition géographique des nationalités et du genre

Produit une carte mondiale interactive représentant, pour chaque pays, la composition par genre des auteurs qui lui sont rattachés. Pour chaque auteur, la nationalité est lue depuis le champ `nationalites` de la collection `authors`. Le genre est issu du champ `genre.valeur` (genre déclaré) ou, à défaut, de `genre_impute.valeur` (genre imputé algorithmiquement).

**Encodage visuel :**
- La couleur de chaque cercle suit un dégradé divergent : bleu pour une majorité d'hommes, rouge pour une majorité de femmes, blanc au point d'équilibre 50/50.
- La taille du cercle est proportionnelle à la racine carrée de l'effectif total du pays.
- Un anneau en pointillé signale la présence d'auteurs dont le genre a été imputé (et non déclaré).

La distinction entre genre déclaré et genre imputé est explicitée dans la légende et dans les popups au clic, qui détaillent les effectifs et proportions pour chacune des deux sources.

Les frontières nationales sont issues du dépôt GeoJSON [`world-countries`](https://github.com/python-visualization/folium/blob/master/examples/data/world-countries.json) de Folium. Les centroides sont calculés comme la moyenne des coordonnées du polygone principal de chaque pays.

Sortie : `carte_nationalite_interactive.html`.

---

### `carte_itineraires.py` — Itinéraires géographiques de formation et d'emploi

Produit deux cartes interactives représentant les parcours géographiques individuels des auteurs, l'une pour la formation (champ `formation`) et l'autre pour l'emploi (champ `emploi`). Seuls les auteurs disposant d'au moins une étape géolocalisée sont représentés.

Pour chaque auteur, les étapes sont triées chronologiquement — en priorité par `annee_debut`, puis `annee_obtention`, puis `annee_fin` — et représentées par des cercles dont la couleur suit un dégradé du foncé (étape la plus ancienne) au clair (étape la plus récente). Ce choix graphique permet de lire l'ordre des étapes sans imputer de direction ou de continuité entre elles, contrairement à un tracé fléché.

**Encodage visuel :**
- Bleu foncé → clair : homme (`male`)
- Rouge foncé → clair : femme (`female`)
- Gris foncé → clair : genre inconnu

Chaque auteur constitue un calque (FeatureGroup) distinct, activable/désactivable dans le panneau en haut à droite. Au chargement, un seul auteur homme et une seule auteure femme sont affichés par défaut.

Les coordonnées de chaque étape sont lues depuis le sous-champ `ecole.location` (coordonnées précises du campus, prioritaires) ou `location` (coordonnées de l'institution parente). **Les étapes sans coordonnées sont ignorées.**

Sorties : `carte_formation.html`, `carte_emploi.html`.

---

## Notes méthodologiques

Les deux scripts partagent le même fond de carte (CartoDB Positron), sobre et en anglais, privilégié pour sa lisibilité à l'échelle mondiale.

Le genre imputé, présent dans les deux visualisations, est issu d'une procédure distincte documentée dans le dépôt dédié à mon mémoire. Il est distingué du genre déclaré dans les représentations : anneau en pointillé dans la carte des nationalités, mention explicite dans les popups de la carte des itinéraires.

Les auteurs à nationalités multiples contribuent à plusieurs pays simultanément dans la carte des nationalités — chaque nationalité reçoit le genre de l'auteur concerné. Cette convention est signalée dans la légende.

---

## Dépendances

```
pip install pymongo folium branca pandas requests
```

Versions testées :

```
python     3.11
pymongo    4.7
folium     0.18
branca     0.7
pandas     2.2
requests   2.32
```

Une instance MongoDB locale est requise (`mongodb://localhost:27017/`), avec la base `references_biblio_mongo` et sa collection `authors` (dispo sur le dépôt Github de mon mémoire!).
