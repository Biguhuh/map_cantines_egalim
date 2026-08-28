"""Lecture des CSV sources et construction des structures embarquées dans la carte."""
import csv

from . import config
from .utils import digits


def read_registre(path, departments):
    """Lit le registre national et ne garde que les cantines des départements ciblés."""
    rows = []
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("department") in departments:
                rows.append(row)
    return rows


def read_teledeclaration(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def build_cantines(rows, geocode_cache):
    """Construit la liste CANTINES (clés courtes, identiques à la carte d'origine)."""
    cantines = []
    for row in rows:
        siret = digits(row.get("siret"))
        loc = geocode_cache.get(siret, {})
        cantines.append({
            "n": row.get("name") or "",
            "a": loc.get("address"),
            "c": row.get("city") or "",
            "cp": row.get("postal_code") or "",
            "d": row.get("department") or "",
            "ins": row.get("city_insee_code") or "",
            "t": row.get("production_type") or "",
            "s": row.get("sector_list") or "",
            "mt": row.get("management_type") or "",
            "em": row.get("economic_model") or "",
            "ym": row.get("yearly_meal_count") or "",
            "dm": row.get("daily_meal_count") or "",
            "si": row.get("siret") or "",
            "lat": loc.get("lat"),
            "lon": loc.get("lon"),
        })
    return cantines


def build_epci_by_insee(rows):
    """Construit la table INSEE -> nom de l'EPCI, à partir du registre filtré."""
    epci = {}
    for row in rows:
        insee = row.get("city_insee_code")
        lib = row.get("epci_lib")
        if insee and lib:
            epci[insee] = lib
    return epci


def build_td_embed(td_rows_by_year, valid_sirets):
    """Construit TD_EMBED : {année: {siret: [%bio, %durable_et_qualite]}}.

    %durable_et_qualite = ratio_bio + ratio_egalim_hors_bio, la valeur comparée
    au seuil légal de 50% de produits durables et de qualité (dont bio).
    Seules les cantines des départements ciblés (`valid_sirets`) sont conservées.
    """
    td_embed = {}
    for year, td_rows in td_rows_by_year.items():
        per_siret = {}
        for row in td_rows:
            siret = digits(row.get("canteen_siret"))
            if not siret or siret not in valid_sirets:
                continue
            try:
                bio = float(row["teledeclaration_ratio_bio"]) * 100
                hors_bio = float(row["teledeclaration_ratio_egalim_hors_bio"]) * 100
            except (KeyError, ValueError, TypeError):
                continue
            per_siret[siret] = [round(bio, 1), round(bio + hors_bio, 1)]
        if per_siret:
            td_embed[year] = per_siret
    return td_embed
