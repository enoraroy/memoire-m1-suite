import math
import folium
import pandas as pd
import requests
from pymongo import MongoClient
from branca.element import Template, MacroElement

DB_NAME = "references_biblio_mongo"
GEOJSON_URL = "https://raw.githubusercontent.com/python-visualization/folium/master/examples/data/world-countries.json"

def get_db():
    client = MongoClient("mongodb://localhost:27017/")
    return client[DB_NAME]

def add_html_legend(m):
    template = """
    {% macro html(this, kwargs) %}
    <div id='maplegend' class='maplegend'
        style='position: fixed; z-index:9999; border:2px solid #aaa;
        background-color:rgba(255,255,255,0.92); border-radius:6px;
        padding: 12px 14px; font-size:13px; right: 20px; bottom: 20px;
        font-family: Arial; box-shadow: 2px 2px 8px rgba(0,0,0,0.2); min-width:200px;'>
        <div style='font-weight:bold; border-bottom:1px solid #ccc; margin-bottom:8px; padding-bottom:4px;'>
            Part des femmes (H &harr; F)
        </div>
        <div style='display:flex; align-items:center; gap:6px; margin-bottom:4px;'>
            <div style='background: linear-gradient(to right, #2166ac, #f7f7f7, #b2182b);
                        width:120px; height:12px; border:1px solid #ccc; border-radius:2px;'></div>
        </div>
        <div style='display:flex; justify-content:space-between; font-size:11px; color:#555; margin-bottom:8px;'>
            <span>100% H</span><span>50/50</span><span>100% F</span>
        </div>
        <div style='border-top:1px solid #eee; padding-top:6px;'>
            <div style='font-size:11px; color:#555; margin-bottom:4px;'>Taille du cercle = effectif total</div>
            <div style='display:flex; align-items:center; gap:6px; font-size:11px;'>
                <span style='background:#888; border-radius:50%; width:8px; height:8px; display:inline-block;'></span> genre declare
            </div>
            <div style='display:flex; align-items:center; gap:6px; font-size:11px; margin-top:2px;'>
                <span style='background:#888; border-radius:50%; width:8px; height:8px; display:inline-block;
                             border: 2px dashed #555;'></span> dont genre impute
            </div>
        </div>
        <div style='font-size:10px; color:#888; margin-top:6px;'>Cliquez sur un cercle pour les details</div>
    </div>
    {% endmacro %}
    """
    macro = MacroElement()
    macro._template = Template(template)
    m.get_root().add_child(macro)

def ratio_to_color(ratio):
    if ratio is None or pd.isna(ratio):
        return '#cccccc'
    if ratio <= 0.5:
        t = ratio * 2
        r, g, b = int(33 + t * 214), int(102 + t * 145), int(172 + t * 75)
    else:
        t = (ratio - 0.5) * 2
        r, g, b = int(247 - t * 69), int(247 - t * 223), int(247 - t * 204)
    return f'#{r:02x}{g:02x}{b:02x}'

def radius_for_total(total, max_total, min_r=5, max_r=30):
    if total == 0:
        return min_r
    return min_r + (max_r - min_r) * math.sqrt(total / max_total)

def process_data(db):
    print("Extraction des donnees MongoDB...")
    stats_pays = {}

    for author in db.authors.find():
        nationalites = author.get("nationalites", [])
        if not nationalites:
            continue
        genre_obj = author.get("genre")
        genre_declare = genre_obj.get("valeur") if genre_obj else None
        genre_impute_obj = author.get("genre_impute")
        genre_impute = genre_impute_obj.get("valeur") if genre_impute_obj else None

        for nat in nationalites:
            pays = nat.get("nom_pays")
            if not pays:
                continue
            if pays not in stats_pays:
                stats_pays[pays] = {"m_declare": 0, "f_declare": 0, "m_impute": 0, "f_impute": 0, "na": 0}

            if genre_declare == "male":       stats_pays[pays]["m_declare"] += 1
            elif genre_declare == "female":   stats_pays[pays]["f_declare"] += 1
            elif genre_impute == "male":      stats_pays[pays]["m_impute"]  += 1
            elif genre_impute == "female":    stats_pays[pays]["f_impute"]  += 1
            else:                             stats_pays[pays]["na"]        += 1

    rows = []
    for pays, s in stats_pays.items():
        m_tot = s["m_declare"] + s["m_impute"]
        f_tot = s["f_declare"] + s["f_impute"]
        total_gendered = m_tot + f_tot
        rows.append({
            "name":      pays,
            "ratio":     f_tot / total_gendered if total_gendered > 0 else None,
            "m_declare": s["m_declare"], "f_declare": s["f_declare"],
            "m_impute":  s["m_impute"],  "f_impute":  s["f_impute"],
            "na":        s["na"],
            "total":     total_gendered + s["na"]
        })
    return pd.DataFrame(rows)

def get_country_centroids(geo_data):
    def centroid_of_feature(feature):
        geom = feature["geometry"]
        if geom["type"] == "Polygon":
            coords = geom["coordinates"][0]
        elif geom["type"] == "MultiPolygon":
            coords = max(geom["coordinates"], key=lambda p: len(p[0]))[0]
        else:
            return None, None
        lats = [c[1] for c in coords]
        lons = [c[0] for c in coords]
        return sum(lats) / len(lats), sum(lons) / len(lons)

    return {
        feat["properties"]["name"]: centroid_of_feature(feat)
        for feat in geo_data["features"]
        if centroid_of_feature(feat)[0] is not None
    }

def build_popup(row):
    m_d, f_d = int(row["m_declare"]), int(row["f_declare"])
    m_i, f_i = int(row["m_impute"]),  int(row["f_impute"])
    na, tot   = int(row["na"]),        int(row["total"])
    tot_d, tot_i = m_d + f_d, m_i + f_i

    def pct(n, d):
        return f"{n/d*100:.1f}%" if d > 0 else "—"

    html = f"""
    <div style='font-family:Arial,sans-serif; font-size:12px; min-width:240px; padding:4px;'>
        <div style='font-weight:bold; font-size:14px; border-bottom:2px solid #333;
                    padding-bottom:4px; margin-bottom:8px;'>{row['name']}</div>
        <div style='font-weight:bold; color:#444; margin-bottom:4px;'>Genre declare ({tot_d} auteurs)</div>
        <div style='margin:2px 0;'><span style='color:#2166ac; font-weight:bold;'>&#9794; Hommes :</span> {m_d} ({pct(m_d, tot_d)})</div>
        <div style='margin:2px 0;'><span style='color:#b2182b; font-weight:bold;'>&#9792; Femmes :</span> {f_d} ({pct(f_d, tot_d)})</div>
        <div style='font-weight:bold; color:#444; margin:8px 0 4px; border-top:1px dashed #ccc; padding-top:6px;'>
            Genre impute ({tot_i} auteurs)
            <span style='font-weight:normal; color:#888; font-size:10px;'>(sans genre declare)</span>
        </div>
        <div style='margin:2px 0;'><span style='color:#2166ac; font-weight:bold;'>&#9794; Hommes :</span> {m_i} ({pct(m_i, tot_i)})</div>
        <div style='margin:2px 0;'><span style='color:#b2182b; font-weight:bold;'>&#9792; Femmes :</span> {f_i} ({pct(f_i, tot_i)})</div>
        <div style='margin-top:8px; padding-top:6px; border-top:1px solid #ccc; color:#555; font-size:11px;'>
            Non specifie : {na} &nbsp;|&nbsp; <strong>Total : {tot}</strong>
        </div>
    </div>
    """
    return folium.Popup(html, max_width=300)

def run_map():
    db = get_db()
    df = process_data(db)

    print("Telechargement des frontieres GeoJSON...")
    geo_data = requests.get(GEOJSON_URL).json()
    centroids = get_country_centroids(geo_data)

    m = folium.Map(location=[20, 0], zoom_start=2, tiles='CartoDB positron', max_bounds=True)

    folium.GeoJson(
        geo_data,
        style_function=lambda x: {'fillColor': '#f0f0f0', 'color': '#cccccc', 'weight': 0.4, 'fillOpacity': 0.5}
    ).add_to(m)

    max_total = df["total"].max() if len(df) > 0 else 1

    for _, row in df.sort_values("total", ascending=False).iterrows():
        pays = row["name"]
        if pays not in centroids:
            continue
        lat, lon = centroids[pays]
        ratio    = row["ratio"]
        color    = ratio_to_color(ratio)
        radius   = radius_for_total(row["total"], max_total)
        pct_f    = f"{ratio*100:.0f}%" if ratio is not None and not pd.isna(ratio) else "n/a"

        folium.CircleMarker(
            location=[lat, lon], radius=radius,
            color='#555555', weight=0.8,
            fill=True, fill_color=color, fill_opacity=0.82,
            popup=build_popup(row),
            tooltip=folium.Tooltip(f"<b>{pays}</b><br>Total : {int(row['total'])} | Femmes : {pct_f}", sticky=False)
        ).add_to(m)

        if (row["m_impute"] + row["f_impute"]) > 0:
            folium.CircleMarker(
                location=[lat, lon], radius=radius + 3,
                color='#555555', weight=1.5,
                fill=False, dash_array='4 3', fill_opacity=0,
                tooltip=folium.Tooltip(
                    f"<b>{pays}</b> — dont genre impute : {int(row['m_impute'] + row['f_impute'])}",
                    sticky=False)
            ).add_to(m)

    add_html_legend(m)
    m.save('carte_nationalite_interactive.html')
    print("Carte HTML generee : carte_nationalite_interactive.html")

if __name__ == "__main__":
    run_map()