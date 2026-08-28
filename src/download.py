"""Téléchargement des CSV sources vers data/raw/."""
import requests

from . import config


def _download(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(url, timeout=60, stream=True)
    r.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in r.iter_content(chunk_size=1 << 20):
            f.write(chunk)
    return dest


def download_registre(registre_resource):
    return _download(registre_resource["url"], config.RAW_DIR / "registre_cantines.csv")


def download_teledeclarations(td_resources):
    """Télécharge un CSV par année et retourne {année: chemin}."""
    paths = {}
    for year, res in td_resources.items():
        paths[year] = _download(res["url"], config.RAW_DIR / f"campagne_td_{year}.csv")
    return paths
