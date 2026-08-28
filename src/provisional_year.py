"""Secours pour la campagne de télédéclaration la plus récente, tant que son
CSV agrégé n'est pas encore publié sur data.gouv.fr.

Chaque cantine possède une fiche publique sur ma-cantine.agriculture.gouv.fr,
alimentée par une API JSON publique (celle que le site utilise lui-même) :
GET /api/v1/publishedCanteens/{id}. Elle renvoie les diagnostics déjà
télédéclarés, campagne par campagne, y compris pour l'année la plus récente,
avant même que le CSV national correspondant n'existe.

Dès que le CSV officiel de cette année est publié, `main.py` cesse
d'appeler cette API pour elle : le CSV agrégé fait toujours foi.
"""
import time

import requests

from . import config
from .utils import digits


def fetch_diagnostics(canteen_id, session):
    """Retourne la liste des diagnostics publiés d'une cantine, ou [] si non trouvée/non publique."""
    try:
        r = session.get(
            config.MA_CANTINE_CANTEEN_API.format(id=canteen_id),
            timeout=config.REQUEST_TIMEOUT,
        )
        if r.status_code != 200:
            return []
        return r.json().get("approDiagnostics", [])
    except (requests.RequestException, ValueError):
        return []


def _ratios_from_diagnostic(diag):
    """Reproduit le calcul officiel : %bio, puis %durable&qualité = %bio + %(siqo+externalités+autres egalim)."""
    bio = diag.get("percentageValeurBio")
    if bio is None:
        return None
    hors_bio = (
        (diag.get("percentageValeurSiqo") or 0)
        + (diag.get("percentageValeurExternalitesPerformance") or 0)
        + (diag.get("percentageValeurEgalimAutres") or 0)
    )
    bio_pct = bio * 100
    return [round(bio_pct, 1), round(bio_pct + hors_bio * 100, 1)]


def fetch_provisional_year(rows, year, pause=0.12, log=print):
    """Construit {siret: [%bio, %durable_et_qualite]} pour `year` via l'API ma-cantine.

    `rows` : lignes du registre déjà filtrées sur les départements ciblés
    (chacune doit avoir un champ 'id' et un champ 'siret').
    """
    log(f"Pas de CSV officiel {year} disponible : interrogation de l'API ma-cantine ({len(rows)} cantines)…")
    session = requests.Session()
    session.headers["User-Agent"] = "map_cantines_egalim (contact via GitHub repo)"

    result = {}
    for i, row in enumerate(rows, 1):
        canteen_id = row.get("id")
        siret = digits(row.get("siret"))
        if canteen_id and siret:
            for diag in fetch_diagnostics(canteen_id, session):
                if str(diag.get("year")) == year and diag.get("isTeledeclared"):
                    ratios = _ratios_from_diagnostic(diag)
                    if ratios:
                        result[siret] = ratios
                    break
        if i % 100 == 0 or i == len(rows):
            log(f"  … {i}/{len(rows)}")
        time.sleep(pause)

    log(f"{len(result)} cantine(s) avec une télédéclaration {year} trouvée(s) via l'API (données provisoires).")
    return result
