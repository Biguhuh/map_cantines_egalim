# Carte des cantines EGALIM — Charente-Maritime (17) & Deux-Sèvres (79)

Carte interactive (Leaflet) des cantines scolaires et collectives des
départements 17 et 79, avec leurs indicateurs EGALIM (part de bio et de
produits durables & de qualité) et une comparaison entre structures
gérantes (départements pour les collèges, communautés de communes pour
les écoles et crèches).

La carte publiée est un **fichier HTML autonome** ([docs/index.html](docs/index.html)) :
toutes les données sont embarquées dans la page, aucun serveur ni base de
données n'est nécessaire. Elle est régénérée automatiquement chaque mois
par une GitHub Action à partir des données ouvertes publiées par
[ma-cantine](https://ma-cantine.agriculture.gouv.fr) sur data.gouv.fr.

## Sources des données

- [Registre National des Cantines](https://www.data.gouv.fr/datasets/registre-national-des-cantines) —
  identité, localisation administrative et caractéristiques de chaque cantine.
- [Résultats de campagnes de télédéclaration des cantines](https://www.data.gouv.fr/datasets/resultats-de-campagnes-de-teledeclaration-des-cantines) —
  part de bio et de produits durables & de qualité déclarée chaque année (2021+).
- [API publique ma-cantine](https://ma-cantine.agriculture.gouv.fr/api/v1/publishedCanteens/) —
  secours pour la campagne la plus récente tant que son CSV agrégé n'est pas
  encore publié (voir plus bas).
- [recherche-entreprises.api.gouv.fr](https://recherche-entreprises.api.gouv.fr/) (SIRENE) —
  adresse postale de l'établissement à partir de son SIRET.
- [api-adresse.data.gouv.fr](https://api-adresse.data.gouv.fr/) (Base Adresse Nationale) —
  géocodage précis (latitude/longitude) de cette adresse.

Données publiques sous [Licence Ouverte / Open Licence 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence).

## Structure du dépôt

```
src/                Code Python du générateur
  config.py          Chemins, départements ciblés, URLs des APIs
  sources.py         Résolution des dernières ressources sur data.gouv.fr
  state.py           Suivi de version pour ne rebuilder qu'en cas de nouveauté
  download.py        Téléchargement des CSV sources
  geocode.py         SIRET -> adresse (SIRENE) -> lat/lon (BAN), avec cache
  build_data.py      Filtrage et mise en forme des données pour la carte
  provisional_year.py Secours API ma-cantine pour l'année sans CSV officiel
  render_map.py      Injection des données dans le template HTML
  main.py            Orchestration (point d'entrée)
template/
  map_template.html  Squelette HTML/CSS/JS de la carte (placeholders __XXX__)
docs/
  index.html          Carte générée, publiée via GitHub Pages
data/
  state.json          Dernières versions de données traitées (committé)
  cache/
    geocode_cache.json  Cache SIRET -> adresse/lat/lon (committé)
  raw/                 CSV sources téléchargés (ignoré par git)
.github/workflows/
  update-map.yml      Job mensuel : vérifie, régénère, committe si besoin
```

## Installation locale

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Utilisation

```bash
# Régénère la carte seulement si data.gouv.fr propose une nouvelle version
python -m src.main

# Force la régénération même sans changement détecté
python -m src.main --force
```

Le premier lancement géocode ~1 000 cantines (un appel SIRENE + un appel BAN
par cantine, ~0,1 s de pause entre chaque) : compter quelques minutes. Les
exécutions suivantes ne géocodent que les cantines nouvellement apparues
dans le registre, grâce au cache `data/cache/geocode_cache.json`.

## Campagne la plus récente : secours via l'API ma-cantine

Le CSV agrégé d'une campagne de télédéclaration (ex : 2025) n'est publié sur
data.gouv.fr qu'avec un certain délai après la fin de la campagne. En
attendant, `src/provisional_year.py` interroge individuellement l'API
publique `publishedCanteens/{id}` (celle qui alimente les fiches publiques
du site ma-cantine) pour l'année `aujourd'hui - 1`, et reconstruit les mêmes
indicateurs (%bio, %durable & qualité) à partir du détail par cantine.

Dès que `sources.get_teledeclaration_resources()` détecte que le CSV
officiel de cette année est disponible, ce secours est automatiquement
désactivé pour elle : le CSV agrégé fait toujours foi dès qu'il existe,
aucune intervention manuelle n'est nécessaire. Ces données provisoires ne
sont pas mises en cache (contrairement au géocodage) puisqu'elles évoluent
tout au long de l'année, au fil des nouvelles télédéclarations.

## Automatisation (GitHub Actions)

Le workflow [`update-map.yml`](.github/workflows/update-map.yml) tourne le
1er de chaque mois : il compare les métadonnées (`last_modified`) des
ressources data.gouv.fr à celles enregistrées dans `data/state.json`. Si
rien n'a changé, il ne fait rien. Sinon, il régénère `docs/index.html` et
committe le résultat (carte, cache de géocodage, état) directement sur la
branche par défaut. Il peut aussi être déclenché manuellement depuis
l'onglet *Actions* (avec l'option *force* pour ignorer la détection de
changement).

## Publication (GitHub Pages)

Une fois le dépôt poussé sur GitHub, activer GitHub Pages sur le dossier
`docs/` de la branche par défaut (*Settings → Pages → Source: Deploy from
a branch → Branch: main, /docs*). La carte sera alors disponible à
`https://<utilisateur>.github.io/<depot>/`.

## Étendre à d'autres départements

Modifier `DEPARTMENTS` dans [`src/config.py`](src/config.py). Le reste du
pipeline (filtrage, géocodage, télédéclarations) s'adapte automatiquement ;
seuls les libellés fixes du template (titre, cases à cocher 17/79,
libellés des départements gestionnaires des collèges) sont à ajuster
manuellement dans [`template/map_template.html`](template/map_template.html)
si de nouveaux départements sont ajoutés.
