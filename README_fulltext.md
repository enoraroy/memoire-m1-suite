# Telecharger_fulltext

Ce dossier regroupe les scripts utilisés pour le téléchargement automatisé de fulltexts d'articles depuis une base de données. Cette méthode a permis de récupérer 3392 fichiers PDFs de fulltext de manière automatique !

---

Fichiers de sortie :

| Fichier | Produit par | Description |
|---|---|---|
| `articles_valides/` | `doi_downloader.py` | Dossier contenant les PDFs téléchargés, nommés `REF_[ID]_[DOI].pdf` |
| `journal_telechargement.log` | `doi_downloader.py` | Journal d'exécution avec statut de chaque téléchargement |
| `downloaded_pdfs/` | `scholar_scraper.py` | PDFs récupérés via les liens eprint Google Scholar |
| `scholar_results.json` | `scholar_scraper.py` | Log JSON des résultats de recherche Scholar par auteur |

---

## Description des scripts

### `doi_downloader.py` — Téléchargement de PDFs par DOI

Parcourt l'ensemble des références de la table `reference` disposant d'un DOI et tente de télécharger le PDF correspondant via deux méthodes successives.

**Méthode 1 — Sci-Hub :** le script interroge en séquence plusieurs miroirs Sci-Hub configurables selon la tendance légale du moment (aller sur le wikipédia pour voir les sites). Chaque appel est lancé dans un sous-processus isolé avec timeout pour éviter le blocage. Le fichier téléchargé est validé (signature `%PDF`, taille minimale) avant d'être conservé (cela fait suite à un premier *run* où j'avais téléchargé de nombreux pdf vides, de 0ko, n'étant donc pas pertinents).

**Méthode 2 — Anna's Archive :** si Sci-Hub échoue sur tous les miroirs, le script fait appel au downloader [annas-archive-downloader](https://github.com/FreesoSaiFared/annas-archive-downloader), à cloner séparément et dont le chemin est à renseigner en configuration.

Le script est conçu pour être interrompu et repris : il lit le dernier identifiant traité dans le fichier de log et reprend à partir de là. Les PDFs déjà présents et valides sont ignorés.

> Compte tenu de la taille des fichiers de texte, je ne suis pas certaine qu'il soit pertinent ni possible de les déposer sur le Github.

---

### `scholar_scraper.py` — Téléchargement de fulltexts via Google Scholar

Ce script est né d'une observation faite en cours de route : en cherchant à récupérer les identifiants Google Scholar des auteurs de la collection, il est apparu que Scholar expose pour certaines publications un lien direct vers le fulltext (`eprint_url`), souvent vers une version en accès ouvert déposée sur une archive institutionnelle ou un site personnel. Le script a donc été conçu pour exploiter ce canal, même si son point d'entrée reste la table `authors` plutôt que la table `reference`.

**Pourquoi passer par les auteurs et non par les références ?**
Google Scholar n'offre pas d'API permettant de chercher une publication directement par DOI ou identifiant. La voie la plus fiable pour retrouver une publication est de croiser le nom de l'auteur avec des mots-clés du titre, ce qui implique de partir des notices auteurs de la base pour construire les requêtes. C'est ce détour par les auteurs qui a rendu visible l'existence de fulltexts accessibles — et qui justifie la présence de ce script dans ce dossier malgré son point d'entrée inhabituel.

**Structure du script :**

Pour chaque auteur de la table `authors` dont l'identifiant Scholar n'est pas encore renseigné, deux stratégies sont appliquées successivement :

**Stratégie 1 — Recherche directe du profil :** le script recherche l'auteur par nom complet sur Google Scholar. La correspondance entre le nom en base et le nom retourné par Scholar est évaluée par une fonction de matching robuste aux abréviations (ex. « T. Szeniczey » = « Tamas Szeniczey »).

**Stratégie 2 — Recherche par publication :** si aucun profil direct n'est trouvé, le script interroge les références associées à l'auteur (table `ecriture` × `reference`) et tente de retrouver ses publications sur Scholar. Les titres sont comparés par plus longue sous-séquence commune (seuil configurable). Lorsqu'une publication est identifiée, le script tente de télécharger le PDF via le lien `eprint_url`, et extrait l'identifiant Scholar de l'auteur depuis la liste des co-auteurs.

Les résultats sont journalisés dans `scholar_results.json` à chaque auteur traité, ce qui permet la reprise en cas d'interruption. Des pauses aléatoires entre les requêtes limitent le risque de blocage par Google Scholar. Le renouvellement des proxies libres est géré automatiquement en cas d'erreur.

---

## Notes méthodologiques

Les deux scripts partagent la même convention de nommage pour les PDFs : `REF_[ID]_[TITRE_OU_DOI].pdf`, où `ID` est l'identifiant de la référence en base.

La validation des PDFs téléchargés repose sur la vérification de la signature binaire `%PDF` en en-tête de fichier, complétée par un contrôle de taille minimale. Un fichier HTML de redirection ou une page d'erreur ne passera pas cette validation.

Le matching de noms d'auteurs ne se base pas sur la similarité globale des chaînes mais sur l'intersection des tokens normalisés (sans accents, sans ponctuation), complétée par une détection des initiales. Cette approche est plus pertinence face aux variantes typographiques fréquentes dans les données de Google Scholar.

---

## Prérequis

Une instance MySQL locale est requise avec la base et les tables attendues par les scripts. Les identifiants de connexion sont à renseigner dans la section `DB_CONFIG` de chaque script.

Le downloader Anna's Archive et celui de Google Scholar doivent être clonés séparément :

```
https://github.com/scholarly-python-package/scholarly
https://github.com/FreesoSaiFared/annas-archive-downloader
```

Le chemin local est à renseigner dans `PATH_ANNA_DIR` dans `doi_downloader.py`.

---

## Dépendances

```
pip install mysql-connector-python doi2pdf requests
```

Versions testées :

```
python               3.11
mysql-connector      8.3
doi2pdf              0.1
requests             2.32
scholarly            1.7
```
