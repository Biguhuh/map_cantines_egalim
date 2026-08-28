"""Résolution des URLs et métadonnées des jeux de données data.gouv.fr."""
import re

import requests

from . import config


def _get_dataset(slug):
    url = config.DATA_GOUV_API.format(slug=slug)
    r = requests.get(url, timeout=config.REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()


def get_registre_resource():
    """Retourne {"url", "last_modified"} pour le CSV du registre national des cantines."""
    dataset = _get_dataset(config.REGISTRE_DATASET_SLUG)
    for res in dataset.get("resources", []):
        if res.get("format") == "csv":
            return {"url": res["url"], "last_modified": res.get("last_modified")}
    raise RuntimeError("Aucune ressource CSV trouvée pour le registre des cantines.")


def get_teledeclaration_resources():
    """Retourne {année: {"url", "last_modified"}} pour les CSV de télédéclaration."""
    dataset = _get_dataset(config.TELEDECLARATION_DATASET_SLUG)
    out = {}
    for res in dataset.get("resources", []):
        if res.get("format") != "csv":
            continue
        m = re.search(r"20\d{2}", res.get("title", ""))
        if not m:
            continue
        year = m.group(0)
        out[year] = {"url": res["url"], "last_modified": res.get("last_modified")}
    return out
