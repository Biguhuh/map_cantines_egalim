"""Géolocalisation des cantines par SIRET.

Deux appels publics et sans clé, enchaînés :
1. recherche-entreprises.api.gouv.fr (SIRENE) : SIRET -> adresse postale.
2. api-adresse.data.gouv.fr (Base Adresse Nationale) : adresse -> lat/lon précis.

Les résultats sont mis en cache indéfiniment par SIRET dans
data/cache/geocode_cache.json : une adresse d'établissement ne change
quasiment jamais, donc les exécutions mensuelles suivantes ne géocodent
que les nouvelles cantines apparues dans le registre.
"""
import json
import re
import time

import requests

from . import config
from .utils import digits


def load_cache():
    if not config.GEOCODE_CACHE_FILE.exists():
        return {}
    with open(config.GEOCODE_CACHE_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_cache(cache):
    config.GEOCODE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(config.GEOCODE_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2, sort_keys=True)


def _format_address(raw_adresse):
    """Insère une virgule avant le code postal pour lisibilité (comme sur la carte d'origine)."""
    return re.sub(r"\s(\d{5}\s)", r", \1", raw_adresse, count=1)


def fetch_sirene_address(siret, session):
    """Retourne l'adresse postale brute d'un établissement, ou None si introuvable."""
    try:
        r = session.get(
            config.SIRENE_SEARCH_API,
            params={"q": siret},
            timeout=config.REQUEST_TIMEOUT,
        )
        if r.status_code != 200:
            return None
        results = r.json().get("results", [])
        if not results:
            return None
        entreprise = results[0]
        for etab in entreprise.get("matching_etablissements", []):
            if etab.get("siret") == siret and etab.get("adresse"):
                return _format_address(etab["adresse"])
        siege = entreprise.get("siege") or {}
        if siege.get("siret") == siret and siege.get("adresse"):
            return _format_address(siege["adresse"])
    except (requests.RequestException, ValueError):
        return None
    return None


def geocode_address(address, session, citycode=None):
    """Retourne (lat, lon) via la BAN, ou (None, None) si pas de résultat fiable.

    `citycode` (code INSEE de la commune attendue) est transmis comme filtre dur
    de l'API, pas comme simple indice de score : sans lui, une adresse mal
    formée (numéro dupliqué, abréviation SIRENE non standard...) peut matcher
    en texte libre une rue homonyme dans une tout autre région, avec un score
    suffisant pour passer le seuil. Avec le filtre, on obtient soit le bon
    point, soit aucun résultat — jamais un point dans le mauvais département.
    """
    try:
        params = {"q": address, "limit": 1}
        if citycode:
            params["citycode"] = citycode
        r = session.get(config.BAN_SEARCH_API, params=params, timeout=config.REQUEST_TIMEOUT)
        if r.status_code != 200:
            return None, None
        features = r.json().get("features", [])
        if not features:
            return None, None
        best = features[0]
        if best["properties"].get("score", 0) < config.GEOCODE_MIN_SCORE:
            return None, None
        lon, lat = best["geometry"]["coordinates"]
        return round(lat, 6), round(lon, 6)
    except (requests.RequestException, ValueError, KeyError):
        return None, None


def ensure_locations(rows, cache, pause=0.12, log=print):
    """Complète `cache` (dict SIRET -> {address, lat, lon}) pour les cantines manquantes.

    `rows` : lignes du registre déjà filtrées sur les départements ciblés.
    """
    missing = {}
    for row in rows:
        siret = digits(row.get("siret"))
        if siret and siret not in cache and siret not in missing:
            missing[siret] = row.get("city_insee_code")
    if not missing:
        return cache
    log(f"Géolocalisation de {len(missing)} nouvelle(s) cantine(s)…")
    session = requests.Session()
    session.headers["User-Agent"] = "map_cantines_egalim (contact via GitHub repo)"
    for i, (siret, insee) in enumerate(missing.items(), 1):
        address = fetch_sirene_address(siret, session)
        lat = lon = None
        if address:
            lat, lon = geocode_address(address, session, citycode=insee)
        cache[siret] = {"address": address, "lat": lat, "lon": lon}
        if i % 50 == 0 or i == len(missing):
            log(f"  … {i}/{len(missing)}")
        time.sleep(pause)
    return cache
