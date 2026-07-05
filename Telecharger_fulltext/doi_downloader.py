import os
import logging
import mysql.connector
import subprocess
import time
import sys
import re
from doi2pdf import doi2pdf  # requis pour le sous-processus

# -------------------------------------------------------------------
# CONFIGURATION
# Clonez le downloader Anna's Archive ici :
# https://github.com/FreesoSaiFared/annas-archive-downloader
# -------------------------------------------------------------------

PATH_ANNA_DIR = r"C:\path\to\annas-archive-downloader"
PATH_ANNA_SCRIPT = os.path.join(PATH_ANNA_DIR, "annadl.py")
OUTPUT_FOLDER = "articles_valides"
LOG_FILE = "journal_telechargement.log"

SCI_HUB_MIRRORS = [
    "https://sci-hub.se",
    "https://sci-hub.st",
    "https://sci-hub.ru",
    "https://sci-hub.pub",
    "https://sci-hub.it"
]

DB_CONFIG = {
    'host': 'localhost',
    'user': 'your_db_user',
    'password': 'your_db_password',
    'database': 'your_database_name'
}

os.makedirs(OUTPUT_FOLDER, exist_ok=True)

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def dernier_id_traite_depuis_log():
    if not os.path.exists(LOG_FILE):
        return 0

    pattern = re.compile(r"ID\s+(\d+)")
    dernier_id = 0

    with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            match = pattern.search(line)
            if match:
                dernier_id = max(dernier_id, int(match.group(1)))

    return dernier_id


def afficher_progression(index, total, id_ref):
    pourcentage = (index / total) * 100 if total else 0
    print(f"[{index}/{total}] ({pourcentage:.1f} %) — ID {id_ref}")


def est_un_vrai_pdf(chemin):
    if not os.path.exists(chemin):
        return False
    try:
        if os.path.getsize(chemin) < 1000:
            return False
        with open(chemin, 'rb') as f:
            return f.read(4) == b'%PDF'
    except:
        return False


def methode_1_doi2pdf_multi_mirrors(doi, destination, timeout=40):
    for mirror in SCI_HUB_MIRRORS:
        print(f"    Sci-Hub : {mirror}")

        if os.path.exists(destination):
            os.remove(destination)

        env = os.environ.copy()
        env["SCI_HUB_URL"] = mirror

        try:
            subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "from doi2pdf import doi2pdf;"
                        f"doi2pdf('{doi}', output=r'{destination}')"
                    )
                ],
                env=env,
                timeout=timeout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            if est_un_vrai_pdf(destination):
                return True
            else:
                if os.path.exists(destination):
                    os.remove(destination)

        except subprocess.TimeoutExpired:
            logging.warning(f"ID bloqué sur Sci-Hub ({mirror}) — timeout")
            if os.path.exists(destination):
                os.remove(destination)

        except Exception as e:
            logging.warning(f"Sci-Hub erreur {mirror} : {e}")
            if os.path.exists(destination):
                os.remove(destination)

    return False


def methode_2_anna(doi):
    try:
        print("    Anna's Archive...")
        subprocess.run(
            ["python", PATH_ANNA_SCRIPT, "download", doi],
            cwd=PATH_ANNA_DIR,
            timeout=90,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return True
    except subprocess.TimeoutExpired:
        logging.warning("Anna Archive timeout")
        return False
    except Exception as e:
        logging.warning(f"Anna Archive Error: {e}")
        return False


def executer_programme():
    db = None
    try:
        dernier_id = dernier_id_traite_depuis_log()
        print(f"Reprise après ID {dernier_id}")

        db = mysql.connector.connect(**DB_CONFIG)
        cursor = db.cursor(dictionary=True)

        query = """
            SELECT id, doi
            FROM reference
            WHERE doi IS NOT NULL
              AND TRIM(doi) != ''
              AND id > %s
            ORDER BY id ASC
        """
        cursor.execute(query, (dernier_id,))
        articles = cursor.fetchall()

        total = len(articles)
        print(f"{total} articles à traiter")

        for index, art in enumerate(articles, start=1):
            id_ref = art['id']
            doi = art['doi'].strip()

            afficher_progression(index, total, id_ref)

            clean_doi = "".join(c if c.isalnum() else "_" for c in doi)
            nom_fichier = f"REF_{id_ref}_{clean_doi}.pdf"
            chemin = os.path.join(OUTPUT_FOLDER, nom_fichier)

            if os.path.exists(chemin) and est_un_vrai_pdf(chemin):
                print("    Déjà téléchargé")
                continue

            # Sci-Hub
            if methode_1_doi2pdf_multi_mirrors(doi, chemin):
                logging.info(f"ID {id_ref} - SUCCÈS (Sci-Hub)")
                continue

            # Anna
            if methode_2_anna(doi):
                logging.info(f"ID {id_ref} - SUCCÈS (Anna)")
            else:
                logging.error(f"ID {id_ref} - ÉCHEC TOTAL")

            time.sleep(2)

    except KeyboardInterrupt:
        print("\nArrêt utilisateur.")
    except Exception as e:
        print(f"Erreur générale : {e}")
    finally:
        if db and db.is_connected():
            cursor.close()
            db.close()
        print("Fin du programme.")


if __name__ == "__main__":
    executer_programme()