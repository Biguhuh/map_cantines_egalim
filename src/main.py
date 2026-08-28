"""Point d'entrée : régénère la carte des cantines EGALIM (17 & 79) si de
nouvelles données ont été publiées sur data.gouv.fr.

Usage :
    python -m src.main            # ne fait rien si les données n'ont pas changé
    python -m src.main --force    # régénère la carte même sans changement détecté
"""
import argparse
from datetime import datetime

from . import build_data, config, download, geocode, provisional_year, render_map, sources, state
from .utils import digits


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true",
        help="Régénère la carte même si aucune nouvelle version des données n'est détectée.",
    )
    args = parser.parse_args()

    print("Vérification des dernières versions publiées sur data.gouv.fr…")
    registre_resource = sources.get_registre_resource()
    td_resources = sources.get_teledeclaration_resources()
    current_meta = state.build_current_meta(registre_resource, td_resources)
    previous_state = state.load_state()

    if not args.force and not state.has_changed(current_meta, previous_state):
        print("Aucune nouvelle version des données. Rien à faire.")
        return

    print("Nouvelle version détectée : téléchargement des données…")
    registre_path = download.download_registre(registre_resource)
    td_paths = download.download_teledeclarations(td_resources)

    print(f"Filtrage sur les départements {', '.join(config.DEPARTMENTS)}…")
    rows = build_data.read_registre(registre_path, config.DEPARTMENTS)
    valid_sirets = {digits(row.get("siret")) for row in rows if digits(row.get("siret"))}
    print(f"{len(rows)} cantines retenues.")

    geocode_cache = geocode.load_cache()
    geocode.ensure_locations(valid_sirets, geocode_cache)
    geocode.save_cache(geocode_cache)

    cantines = build_data.build_cantines(rows, geocode_cache)
    epci_by_insee = build_data.build_epci_by_insee(rows)

    td_rows_by_year = {
        year: build_data.read_teledeclaration(path) for year, path in td_paths.items()
    }
    td_embed = build_data.build_td_embed(td_rows_by_year, valid_sirets)

    fallback_year = str(datetime.now().year - 1)
    if fallback_year in td_resources:
        print(f"CSV officiel {fallback_year} disponible : pas besoin de l'API ma-cantine.")
    else:
        provisional = provisional_year.fetch_provisional_year(rows, fallback_year)
        if provisional:
            td_embed[fallback_year] = provisional

    generated_at = datetime.now().strftime("%d/%m/%Y")
    output_path = render_map.render(cantines, td_embed, epci_by_insee, generated_at)
    print(f"Carte régénérée : {output_path}")

    state.save_state(current_meta)


if __name__ == "__main__":
    main()
