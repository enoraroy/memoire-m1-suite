import mysql.connector
import re
import time
import random
import unicodedata
import json
import os
import requests
from difflib import SequenceMatcher
from scholarly import scholarly, ProxyGenerator

# Note : j'ai du installer et créer un environnement en python 3.11 pour utiliser scholarly !
# Le dépôt utilisé est le suivant : https://github.com/scholarly-python-package/scholarly

DB_CONFIG = {
    "host": "localhost",
    "user": "your_db_user",
    "password": "your_db_password",
    "database": "your_database_name"
}

# Nombre maximum de références à tester par auteur si le profil direct échoue
MAX_REFS_TO_TRY = 5
# Nombre maximum de résultats Google Scholar à parcourir par recherche
MAX_PUB_RESULTS = 3
TIMEOUT_SECONDS = 60
JSON_LOG_FILE = "scholar_results.json"
# Dossier de stockage des PDFs téléchargés
PDF_DIR = "downloaded_pdfs"

if not os.path.exists(PDF_DIR):
    os.makedirs(PDF_DIR)

# =========================
# PROXIES ET PERSISTANCE
# =========================

pg = ProxyGenerator()

def refresh_proxies():
    # Renouvelle la liste de proxies libres pour contourner les limitations de débit de Google Scholar
    print("[INFO] Renouvellement des proxies...")
    try:
        pg.FreeProxies()
        scholarly.use_proxy(pg)
        if hasattr(scholarly, 'navigator'):
            scholarly.navigator.timeout = TIMEOUT_SECONDS
        print("[INFO] Nouveau proxy configuré.")
    except Exception as e:
        print(f"[AVERT] Problème lors du renouvellement des proxies : {e}")

def load_processed_ids():
    # Charge les IDs d'auteurs déjà traités depuis le fichier JSON pour permettre la reprise
    if not os.path.exists(JSON_LOG_FILE):
        return set()
    processed = set()
    try:
        with open(JSON_LOG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            for entry in data:
                processed.add(entry["author_id"])
        print(f"[INFO] {len(processed)} auteurs déjà traités, ignorés.")
    except (json.JSONDecodeError, KeyError):
        pass
    return processed

def save_to_json(data):
    # Ajoute un résultat au fichier JSON de log (lecture + réécriture complète pour éviter la corruption)
    results = []
    if os.path.exists(JSON_LOG_FILE):
        with open(JSON_LOG_FILE, 'r', encoding='utf-8') as f:
            try:
                results = json.load(f)
            except json.JSONDecodeError:
                results = []
    results.append(data)
    with open(JSON_LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=4, ensure_ascii=False)

print("[INFO] Initialisation du ProxyGenerator...")
refresh_proxies()

# =========================
# NORMALISATION ET CORRESPONDANCE
# =========================

def normalize_text(text: str) -> str:
    # Supprime les accents, la ponctuation et met en minuscules pour comparer des chaînes hétérogènes
    if not text:
        return ""
    text = str(text).lower()
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()

def name_match_score(db_name, gs_name):
    # Détecte si deux noms désignent la même personne, même si l'un est abrégé (ex. "T. Szeniczey" = "Tamas Szeniczey")
    n1 = normalize_text(db_name).split()
    n2 = normalize_text(gs_name).split()

    set1, set2 = set(n1), set(n2)
    intersection = set1.intersection(set2)

    if len(intersection) >= 1:
        # Correspondance certaine si deux mots communs (prénom + nom tous les deux présents)
        if len(intersection) >= 2:
            return True
        # Correspondance par initiale : "t" correspond à "tamas"
        for w1 in n1:
            for w2 in n2:
                if w1 == w2:
                    continue
                if (len(w1) == 1 and w2.startswith(w1)) or (len(w2) == 1 and w1.startswith(w2)):
                    return True

    return False

def ordered_word_match(title1: str, title2: str, threshold: float = 0.85):
    # Vérifie si deux titres sont suffisamment similaires en comparant la plus longue sous-séquence commune
    norm1, norm2 = normalize_text(title1), normalize_text(title2)
    words1, words2 = norm1.split(), norm2.split()
    if len(words1) < 3 or len(words2) < 3:
        return False
    matcher = SequenceMatcher(None, words1, words2)
    match = matcher.find_longest_match(0, len(words1), 0, len(words2))
    shortest_len = min(len(words1), len(words2))
    return (match.size / shortest_len >= threshold) if shortest_len else False

def download_pdf(url, ref_id, original_title):
    # Tente de télécharger le PDF associé à une publication et le nomme REF_[ID]_[TITRE].pdf
    try:
        safe_title = re.sub(r'[^a-zA-Z0-9]', '_', original_title)[:50]
        filename = f"REF_{ref_id}_{safe_title}.pdf"
        filepath = os.path.join(PDF_DIR, filename)

        print(f"      [INFO] Téléchargement : {filename}...")
        response = requests.get(url, stream=True, timeout=15)

        if response.status_code == 200:
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            print("      [INFO] PDF téléchargé.")
            return True
        else:
            print(f"      [AVERT] Echec du téléchargement (statut {response.status_code})")
    except Exception as e:
        print(f"      [AVERT] Erreur lors du téléchargement : {e}")
    return False

# =========================
# RECHERCHE GOOGLE SCHOLAR
# =========================

def safe_search_author(full_name):
    # Recherche un profil auteur Google Scholar par nom complet
    # Retourne l'identifiant Scholar si trouvé, None sinon
    for attempt in range(2):
        try:
            print(f"    [INFO] Tentative {attempt+1}/2 : recherche du profil auteur...")
            search = scholarly.search_author(full_name)
            for cand in search:
                if name_match_score(full_name, cand.get("name", "")):
                    sid = cand.get("scholar_id")
                    if sid:
                        return sid
            return None
        except Exception as e:
            print(f"    [AVERT] Erreur profil : {e}")
            refresh_proxies()
    return None

def safe_search_pub(full_name, ref_title, ref_id):
    # Recherche une publication par auteur + titre, tente de télécharger le PDF,
    # et extrait l'identifiant Scholar de l'auteur depuis la liste des co-auteurs
    query = f'"{full_name}" "{" ".join(ref_title.split()[:10])}"'

    for attempt in range(2):
        try:
            print(f"    [INFO] Tentative {attempt+1}/2 : recherche de la publication...")
            search = scholarly.search_pubs(query)

            for _ in range(MAX_PUB_RESULTS):
                pub = next(search)
                gs_title = pub.get("bib", {}).get("title", "")

                if ordered_word_match(ref_title, gs_title):
                    print("      [INFO] Publication correspondante trouvée.")

                    eprint_url = pub.get("eprint_url") or pub.get("pub_url")
                    if eprint_url:
                        download_pdf(eprint_url, ref_id, gs_title)
                    else:
                        print("      [INFO] Aucun lien PDF disponible.")

                    authors_list = pub.get("bib", {}).get("author", [])
                    ids_list = pub.get("author_id", [])

                    for i, author_name in enumerate(authors_list):
                        if name_match_score(full_name, author_name):
                            if i < len(ids_list) and ids_list[i]:
                                print(f"      [INFO] ID Scholar trouvé pour {author_name} : {ids_list[i]}")
                                return 'FOUND', ids_list[i]
                            elif i < len(ids_list) and not ids_list[i]:
                                print(f"      [INFO] Auteur trouvé ({author_name}) mais sans ID Scholar.")

                    return 'NO_PROFILE', None
            return None, None

        except StopIteration:
            return None, None
        except Exception as e:
            print(f"    [AVERT] Erreur publication : {e}")
            refresh_proxies()

    return None, None

# =========================
# PIPELINE PRINCIPAL
# =========================

def main():
    processed_ids = load_processed_ids()

    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cur = conn.cursor(dictionary=True)

        # Récupère les auteurs sans identifiant Scholar, VIAF ou IdRef
        cur.execute("""
            SELECT id, NomComplet
            FROM authors
            WHERE ppn_viaf IS NULL
              AND googlescholarid IS NULL
              AND ppn_idref IS NULL
            LIMIT 20000
        """)
        authors = cur.fetchall()

        for auth in authors:
            author_id, full_name = auth["id"], auth["NomComplet"]

            if author_id in processed_ids:
                continue

            print(f"\n--- ID {author_id} : {full_name} ---")

            # Tentative 1 : recherche directe du profil auteur
            gs_id = safe_search_author(full_name)
            status_log = "NOT_FOUND"

            if not gs_id:
                # Tentative 2 : recherche via ses publications si le profil direct est introuvable
                cur.execute("""
                    SELECT r.id, r.title
                    FROM ecriture e
                    JOIN reference r ON e.reference_id = r.id
                    WHERE e.author_id = %s
                """, (author_id,))

                refs = cur.fetchall()
                valid_refs = [r for r in refs if r["title"]]
                # Priorité aux titres les plus longs (plus distinctifs, moins de faux positifs)
                valid_refs.sort(key=lambda x: len(x["title"].split()), reverse=True)
                refs_to_try = valid_refs[:MAX_REFS_TO_TRY]

                for ref in refs_to_try:
                    r_id = ref["id"]
                    r_title = ref["title"]

                    status, result_id = safe_search_pub(full_name, r_title, r_id)

                    if status == 'FOUND':
                        gs_id = result_id
                        status_log = "SUCCESS"
                        break
                    elif status == 'NO_PROFILE':
                        gs_id = "NONE"
                        status_log = "CONFIRMED_NO_PROFILE"
                        break
            else:
                status_log = "SUCCESS_DIRECT"

            save_to_json({
                "author_id": author_id,
                "name": full_name,
                "scholar_id": gs_id if (gs_id and gs_id != "NONE") else None,
                "status": status_log,
                "timestamp": time.ctime()
            })

            processed_ids.add(author_id)
            print(f"    [LOG] {status_log} (Scholar ID : {gs_id})")
            # Pause aléatoire pour limiter le risque de blocage par Google Scholar
            time.sleep(random.uniform(5, 10))

    except KeyboardInterrupt:
        print("\n[INFO] Arret manuel.")
    except Exception as e:
        print(f"[ERREUR] Erreur critique : {e}")
    finally:
        if 'conn' in locals() and conn.is_connected():
            conn.close()
            print("[INFO] Connexion base de donnees fermee.")

if __name__ == "__main__":
    main()