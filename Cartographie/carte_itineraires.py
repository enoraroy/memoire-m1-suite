"""
Génération de deux cartes HTML interactives (Folium / Leaflet) représentant
les itinéraires géographiques des auteurs de la collection `authors` de la
base MongoDB `references_biblio_mongo`.

Deux cartes sont produites :
  - carte_formation.html : étapes de formation
  - carte_emploi.html    : étapes d'emploi

Pour chaque auteur disposant d'au moins une étape géolocalisée, les étapes
sont triées chronologiquement et représentées par des cercles dont la couleur
va du plus foncé (étape la plus ancienne) au plus clair (étape la plus récente).
Cela permet de lire le parcours sans imputer de direction.

Chaque auteur constitue un calque (FeatureGroup) distinct. Au chargement,
un seul homme et une seule femme sont affichés par défaut.

Encodage visuel :
  bleu foncé→clair = homme   (genre.valeur ou genre_impute.valeur = 'male')
  rouge foncé→clair = femme  (idem = 'female')
  gris foncé→clair = genre inconnu
"""

import math
import folium
from branca.element import MacroElement, Template
from pymongo import MongoClient

# --- Configuration -----------------------------------------------------------

MONGO_URI       = "mongodb://localhost:27017/"
DB_NAME         = "references_biblio_mongo"
COLLECTION_NAME = "authors"

OUTPUT_FORMATION = "carte_formation.html"
OUTPUT_EMPLOI    = "carte_emploi.html"

# Dégradés par genre : (R_foncé, G_foncé, B_foncé) → (R_clair, G_clair, B_clair)
GRADIENTS = {
    "male":    ((13,  71, 161), (187, 222, 251)),   # bleu 900 → bleu 100
    "female":  ((183, 28,  28), (255, 205, 210)),   # rouge 900 → rouge 100
    "unknown": ((66,  66,  66), (224, 224, 224)),   # gris 800 → gris 200
}

MAP_CENTER     = (20, 0)
MAP_ZOOM_START = 2

TILES_URL  = "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
TILES_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>'

CIRCLE_RADIUS  = 7
CIRCLE_WEIGHT  = 1
CIRCLE_OPACITY = 0.9

LEGEND_HTML = """
{% macro html(this, kwargs) %}
<div style="position: fixed; bottom: 30px; left: 30px; z-index: 1000;
            background: white; padding: 10px 16px; border: 1px solid #bbb;
            border-radius: 6px; font-size: 12px; font-family: Arial, sans-serif;
            box-shadow: 0 2px 6px rgba(0,0,0,0.2); min-width: 210px;">

    <div style="font-weight:bold; margin-bottom:8px; font-size:13px;">Lecture de la carte</div>

    <div style="font-weight:bold; margin-bottom:5px;">Genre</div>
    <div style="display:flex; flex-direction:column; gap:4px; margin-bottom:10px;">
        <div style="display:flex; align-items:center; gap:8px;">
            <div style="width:70px; height:12px; border-radius:3px;
                        background: linear-gradient(to right, #0d47a1, #bbdefb);
                        border:1px solid #ccc; flex-shrink:0;"></div>
            <span>Homme</span>
        </div>
        <div style="display:flex; align-items:center; gap:8px;">
            <div style="width:70px; height:12px; border-radius:3px;
                        background: linear-gradient(to right, #b71c1c, #ffcdd2);
                        border:1px solid #ccc; flex-shrink:0;"></div>
            <span>Femme</span>
        </div>
        <div style="display:flex; align-items:center; gap:8px;">
            <div style="width:70px; height:12px; border-radius:3px;
                        background: linear-gradient(to right, #424242, #e0e0e0);
                        border:1px solid #ccc; flex-shrink:0;"></div>
            <span>Inconnu</span>
        </div>
    </div>

    <div style="border-top:1px solid #ddd; padding-top:8px; margin-bottom:8px;">
        <div style="font-weight:bold; margin-bottom:4px;">Chronologie</div>
        <div style="display:flex; justify-content:space-between; font-size:11px; color:#555; margin-bottom:3px;">
            <span>plus foncé = plus ancien et plus clair = plus récent</span>
    </div>

    <div style="border-top:1px solid #ddd; padding-top:6px; font-size:11px; color:#555;">
        Cochez/décochez les auteurs<br>via &#9776; (haut à droite)
    </div>
</div>
{% endmacro %}
"""


class Legend(MacroElement):
    def __init__(self):
        super().__init__()
        self._template = Template(LEGEND_HTML)


# --- Fonctions utilitaires ---------------------------------------------------

def get_gender_key(author):
    g = (author.get("genre") or {}).get("valeur")
    if g is None:
        g = (author.get("genre_impute") or {}).get("valeur")
    if g == "male":   return "male"
    if g == "female": return "female"
    return "unknown"


def extract_coordinates(entry):
    if not entry or not isinstance(entry, dict):
        return None
    loc = (entry.get("ecole") or {}).get("location") or entry.get("location")
    if not loc:
        return None
    coords = loc.get("coordinates")
    if not coords or len(coords) != 2:
        return None
    lon, lat = coords
    return (lat, lon)


def extract_year(entry):
    for key in ("annee_debut", "annee_obtention", "annee_fin"):
        val = entry.get(key)
        if val:
            return int(val)
    return None


def extract_year_end(entry):
    for key in ("annee_fin", "annee_obtention"):
        val = entry.get(key)
        if val:
            return int(val)
    return None


def is_en_cours(entry):
    return entry.get("en_cours") is True


def interpolate_color(dark_rgb, light_rgb, t):
    """Interpolation linéaire entre deux couleurs RGB pour t dans [0, 1].
    t=0 → couleur foncée (étape la plus ancienne)
    t=1 → couleur claire (étape la plus récente)
    """
    r = int(dark_rgb[0] + t * (light_rgb[0] - dark_rgb[0]))
    g = int(dark_rgb[1] + t * (light_rgb[1] - dark_rgb[1]))
    b = int(dark_rgb[2] + t * (light_rgb[2] - dark_rgb[2]))
    return f"#{r:02x}{g:02x}{b:02x}"


def step_colors(n_steps, gender_key):
    """Retourne une liste de n_steps couleurs du foncé au clair."""
    dark, light = GRADIENTS[gender_key]
    if n_steps == 1:
        return [interpolate_color(dark, light, 0.0)]
    return [interpolate_color(dark, light, i / (n_steps - 1)) for i in range(n_steps)]


def build_popup(author_name, step, step_type):
    color_hdr  = "#2e7d32" if step_type == "formation" else "#1565c0"
    label_type = "Formation" if step_type == "formation" else "Emploi"

    inst   = step.get("label") or "—"
    ecole  = step.get("ecole") or ""
    detail = step.get("detail") or "—"

    periode = step.get("periode") or ""
    if not periode:
        y_start  = step.get("year")
        y_end    = step.get("year_end")
        en_cours = step.get("en_cours", False)
        if y_start and y_end:     periode = f"{y_start} – {y_end}"
        elif y_start and en_cours: periode = f"{y_start} – présent"
        elif y_start:              periode = str(y_start)
        else:                      periode = "Période inconnue"

    ecole_row = (
        f'<div style="margin-bottom:4px;"><span style="color:#555;">📌 Campus :</span> {ecole}</div>'
        if ecole else ""
    )

    html = f"""
    <div style="font-family:Arial,sans-serif; min-width:220px; font-size:13px;">
      <div style="background:{color_hdr}; color:white; padding:6px 10px;
                  border-radius:4px 4px 0 0; margin:-1px -1px 8px -1px;">
        <b>{author_name}</b>
      </div>
      <div style="padding:0 4px 4px 4px;">
        <div style="margin-bottom:4px;"><span style="color:#555;">📍 Institution :</span> {inst}</div>
        {ecole_row}
        <div style="margin-bottom:4px;"><span style="color:#555;">Type :</span> {label_type}</div>
        <div style="margin-bottom:4px;"><span style="color:#555;">📋 Détail :</span> {detail}</div>
        <div><span style="color:#555;">📅 Période :</span> {periode}</div>
      </div>
    </div>
    """
    return folium.Popup(html, max_width=320)


def build_itinerary(author, field_name):
    steps = []
    for entry in (author.get(field_name) or []):
        coords = extract_coordinates(entry)
        if coords is None:
            continue
        steps.append({
            "coords":   coords,
            "year":     extract_year(entry),
            "year_end": extract_year_end(entry),
            "label":    (entry.get("institution") or "").strip(),
            "detail":   (entry.get("diplome") or entry.get("poste") or "").strip(),
            "periode":  (entry.get("periode") or "").strip(),
            "ecole":    (entry.get("ecole") or {}).get("nom", "").strip(),
            "en_cours": is_en_cours(entry),
        })
    steps.sort(key=lambda s: (0, s["year"]) if s["year"] is not None else (1, 0))
    return steps


def get_layer_name(author, n_lieux):
    name = (author.get("nom_complet") or "").strip()
    if not name:
        nom    = (author.get("Nom") or "").strip()
        prenom = (author.get("Prenom") or "").strip()
        name   = ", ".join(p for p in (nom, prenom) if p)
    if not name:
        name = f"Auteur sans nom (_id={author.get('_id')})"
    idmysql = author.get("idmysql")
    suffix  = f" [{idmysql}]" if idmysql is not None else ""
    return f"{name}{suffix} ({n_lieux} lieu{'x' if n_lieux > 1 else ''})"


def get_author_name(author):
    name = (author.get("nom_complet") or "").strip()
    if not name:
        nom    = (author.get("Nom") or "").strip()
        prenom = (author.get("Prenom") or "").strip()
        name   = ", ".join(p for p in (nom, prenom) if p)
    return name or f"Auteur (_id={author.get('_id')})"


# --- Construction de la carte ------------------------------------------------

def build_map(authors, field_name, output_path):
    fmap = folium.Map(
        location=MAP_CENTER,
        zoom_start=MAP_ZOOM_START,
        tiles=TILES_URL,
        attr=TILES_ATTR,
    )

    # Pré-calcul + tri par nombre de lieux décroissant
    items = []
    for author in authors:
        steps = build_itinerary(author, field_name)
        if steps:
            n_lieux = len({s["coords"] for s in steps})
            items.append((author, steps, n_lieux))
    items.sort(key=lambda t: (-t[2], (t[0].get("nom_complet") or "")))

    # On repère le premier homme et la première femme pour l'affichage initial
    first_shown = {"male": False, "female": False, "unknown": False}

    for author, steps, n_lieux in items:
        gk     = get_gender_key(author)
        name   = get_author_name(author)
        colors = step_colors(len(steps), gk)

        # Afficher uniquement le premier auteur de chaque genre au chargement
        show = not first_shown[gk]
        first_shown[gk] = True

        group = folium.FeatureGroup(
            name=get_layer_name(author, n_lieux),
            show=show,
        )

        for step, color in zip(steps, colors):
            year_str = str(step["year"]) if step["year"] else "?"
            folium.CircleMarker(
                location=step["coords"],
                radius=CIRCLE_RADIUS,
                color="#555555",
                weight=CIRCLE_WEIGHT,
                fill=True,
                fill_color=color,
                fill_opacity=CIRCLE_OPACITY,
                popup=build_popup(name, step, field_name),
                tooltip=folium.Tooltip(
                    f"<b>{name}</b> — {year_str}",
                    sticky=False,
                ),
            ).add_to(group)

        group.add_to(fmap)

    fmap.get_root().add_child(Legend())
    folium.LayerControl(collapsed=True).add_to(fmap)
    fmap.save(output_path)
    print(f"Carte enregistrée : {output_path}  ({len(items)} auteurs)")


# --- Programme principal -----------------------------------------------------

def main():
    client = MongoClient(MONGO_URI)
    col    = client[DB_NAME][COLLECTION_NAME]

    build_map(list(col.find({"formation.location": {"$exists": True}})),
              "formation", OUTPUT_FORMATION)
    build_map(list(col.find({"emploi.location": {"$exists": True}})),
              "emploi", OUTPUT_EMPLOI)

    client.close()


if __name__ == "__main__":
    main()