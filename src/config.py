"""Configuration centrale du générateur de carte."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CACHE_DIR = DATA_DIR / "cache"
STATE_FILE = DATA_DIR / "state.json"
GEOCODE_CACHE_FILE = CACHE_DIR / "geocode_cache.json"

TEMPLATE_FILE = ROOT / "template" / "map_template.html"
OUTPUT_FILE = ROOT / "docs" / "index.html"

# Départements couverts par la carte.
DEPARTMENTS = ["17", "79"]

# Jeux de données data.gouv.fr (ma-cantine / agriculture.gouv.fr).
DATA_GOUV_API = "https://www.data.gouv.fr/api/1/datasets/{slug}/"
REGISTRE_DATASET_SLUG = "registre-national-des-cantines"
TELEDECLARATION_DATASET_SLUG = "resultats-de-campagnes-de-teledeclaration-des-cantines"

# APIs publiques pour la géolocalisation (adresse + coordonnées).
SIRENE_SEARCH_API = "https://recherche-entreprises.api.gouv.fr/search"
BAN_SEARCH_API = "https://api-adresse.data.gouv.fr/search/"
GEOCODE_MIN_SCORE = 0.35

# API publique ma-cantine (celle utilisée par leurs propres pages /nos-cantines/...),
# utilisée en secours pour la campagne la plus récente tant que son CSV agrégé
# n'est pas encore publié sur data.gouv.fr.
MA_CANTINE_CANTEEN_API = "https://ma-cantine.agriculture.gouv.fr/api/v1/publishedCanteens/{id}"

REQUEST_TIMEOUT = 20
