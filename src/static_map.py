"""Carte fixe (SVG) des résultats EGALIM des communes d'une intercommunalité.

Un rond par commune : le centre donne la part de bio, l'anneau la part de
produits durables & de qualité, chacun coloré selon l'objectif EGALIM
(20 % bio, 50 % durable & qualité). Un classement à droite permet à chaque
commune de se situer par rapport à ses voisines.

Seules les cantines d'écoles et de crèches sont prises en compte (les
collèges relèvent du département). Les valeurs d'une commune sont la moyenne
de ses cantines déclarées, pondérée par leur nombre de repas annuels.

Les données viennent de la carte déjà générée (docs/index.html) ; les
contours des communes de l'API publique geo.api.gouv.fr.

Usage :
    python -m src.static_map --epci 200041317            # CA du Niortais
    python -m src.static_map --epci 200041317 --annee 2024
    python -m src.static_map --tous                      # toutes, + la galerie à la racine du site
"""
import argparse
import json
import math
import re
from datetime import date
from html import escape
from pathlib import Path

import requests

from . import config

GEO_API = "https://geo.api.gouv.fr"
CARTES_DIR = config.ROOT / "docs" / "cartes"
CARTES_URL = "https://biguhuh.github.io/map_cantines_egalim/cartes/"
# Page de la galerie des cartes, à la racine du site (dépôt Biguhuh.github.io).
GALLERY_URL = "https://biguhuh.github.io/cartes-egalim.html"
GALLERY_FILE = config.ROOT.parent / "Biguhuh.github.io" / "cartes-egalim.html"
DEPT_NAMES = {"17": "Charente-Maritime", "79": "Deux-Sèvres"}

# Objectifs EGALIM pour la restauration collective.
OBJ_BIO = 20
OBJ_DURABLE = 50

# Classes, de la meilleure à la moins bonne : (seuil bio, seuil durable). Sous l'objectif,
# deux classes (au moins la moitié, moins de la moitié) ; au-dessus, trois paliers : beaucoup
# de communes atteignent l'objectif, et pas toutes de la même façon. Paliers calés sur la
# répartition 2025 (quart supérieur ≈ 30 % bio / 60 % durable).
THRESHOLDS = [(40, 70), (30, 60), (OBJ_BIO, OBJ_DURABLE), (OBJ_BIO // 2, OBJ_DURABLE // 2), (0, 0)]

# Deux palettes, une couleur par classe ci-dessus. Écarts mesurés en simulation de daltonisme
# (Machado 2009, CIEDE2000 minimal entre deux classes) :
# - « classique » : rouge → orange → verts, la convention la plus parlante. Les clartés très
#   séparées la gardent lisible en deutéranopie (écart ≥ 9) ; la protanopie, où le rouge
#   paraît sombre, reste hors de portée de toute palette rouge-vert (écart ≈ 4).
# - « daltonien » : dérivée de ColorBrewer PiYG, magenta et rose sous l'objectif ; écart ≥ 21
#   en protanopie, deutéranopie et tritanopie.
# La page de chaque carte et la galerie proposent de passer de l'une à l'autre.
PALETTES = {
    "classique": {
        "colors": ["#1a6b32", "#58b04f", "#f3f9c4", "#fa9f3c", "#b0171f"],
        "low_names": ("Orange", "Rouge"),
        "suffix": "",
        "other_note": "Version aux couleurs adaptées aux daltoniens",
    },
    "daltonien": {
        "colors": ["#1f5214", "#5aa02c", "#c9e89b", "#ef9fcc", "#a6106d"],
        "low_names": ("Rose", "Magenta"),
        "suffix": "-daltonien",
        "other_note": "Version aux couleurs classiques",
    },
}

# Interrupteur classique / daltoniens, commun aux pages de cartes et à la galerie. Le choix est
# mémorisé dans le navigateur (même clé partout) et posé sur <html data-palette> dès le <head>,
# pour éviter d'afficher d'abord la mauvaise version. Les éléments portant data-classique et
# data-daltonien (lien de téléchargement, vignettes) suivent le choix. Sans JavaScript, le
# bouton reste caché et la version classique s'affiche.
PALETTE_HEAD_SCRIPT = """<script>
  document.documentElement.classList.add("js");
  try { if (localStorage.getItem("egalim-palette") === "daltonien") document.documentElement.dataset.palette = "daltonien"; } catch (e) {}
</script>"""
PALETTE_TOGGLE_CSS = """  .palette-toggle { display: none; }
  .js .palette-toggle { display: inline-block; }
  .palette-toggle[aria-pressed="true"] { border-color: var(--accent); color: var(--accent); }"""
PALETTE_TOGGLE_BUTTON = ('<button class="btn palette-toggle" type="button" aria-pressed="false">'
                         'Couleurs adaptées aux daltoniens</button>')
PALETTE_TOGGLE_SCRIPT = """<script>
  (function () {
    var root = document.documentElement, btn = document.querySelector(".palette-toggle");
    function apply(p) {
      if (p === "daltonien") root.dataset.palette = "daltonien"; else delete root.dataset.palette;
      if (btn) btn.setAttribute("aria-pressed", p === "daltonien");
      document.querySelectorAll("[data-classique][data-daltonien]").forEach(function (el) {
        var v = el.getAttribute("data-" + p);
        if (el.tagName === "IMG") el.src = v; else el.href = v;
      });
    }
    apply(root.dataset.palette || "classique");
    if (btn) btn.addEventListener("click", function () {
      var p = root.dataset.palette === "daltonien" ? "classique" : "daltonien";
      try { localStorage.setItem("egalim-palette", p); } catch (e) {}
      apply(p);
    });
  })();
</script>"""
C_NODATA = "#b9bcc2"
C_INK, C_MUTED, C_LINE, C_BG = "#1b2733", "#5c6773", "#c9ced4", "#ffffff"
C_COMMUNE, C_COMMUNE_EMPTY = "#eef1f4", "#f8f9fa"


# ---------------------------------------------------------------------------
# Données
# ---------------------------------------------------------------------------

def load_embedded(name, page):
    """Lit la constante JS `const NAME = {...};` embarquée dans la carte HTML."""
    m = re.search(rf"const {name}\s*=\s*", page)
    if not m:
        raise SystemExit(f"{name} introuvable dans {config.OUTPUT_FILE}")
    value, _ = json.JSONDecoder().raw_decode(page, m.end())
    return value


def classify_etab(sector):
    """Même règle que la carte : un collège prime sur le reste."""
    sector = sector or ""
    if "Secondaire collège" in sector:
        return "college"
    if "Crèche" in sector:
        return "creche"
    if "Ecole primaire" in sector:
        return "ecole"
    return None


def fetch_epci(code, session):
    r = session.get(f"{GEO_API}/epcis/{code}", params={"fields": "nom,code"}, timeout=config.REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()


def fetch_communes(code, session):
    r = session.get(
        f"{GEO_API}/epcis/{code}/communes",
        params={"fields": "nom,code,centre,contour", "format": "json"},
        timeout=config.REQUEST_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def commune_results(communes, cantines, td_year):
    """Agrège, par commune, les cantines d'écoles et de crèches déclarées cette année."""
    by_insee = {c["code"]: {"total": 0, "declared": 0, "w": 0.0, "bio": 0.0, "durable": 0.0} for c in communes}
    for c in cantines:
        res = by_insee.get(c.get("ins"))
        if res is None or classify_etab(c.get("s")) not in ("ecole", "creche"):
            continue
        res["total"] += 1
        td = td_year.get(c.get("si"))
        if not td or td[0] is None or td[1] is None:
            continue
        try:
            w = float(c.get("ym") or 0) or 1.0
        except ValueError:
            w = 1.0
        res["declared"] += 1
        res["w"] += w
        res["bio"] += w * td[0]
        res["durable"] += w * td[1]
    for res in by_insee.values():
        if res["w"]:
            res["bio"] /= res["w"]
            res["durable"] /= res["w"]
        else:
            res["bio"] = res["durable"] = None
    return by_insee


# ---------------------------------------------------------------------------
# Rendu SVG
# ---------------------------------------------------------------------------

def level_color(value, kind, colors):
    """Couleur de la classe d'une valeur, kind valant "bio" ou "durable"."""
    if value is None:
        return C_NODATA
    col = 0 if kind == "bio" else 1
    return next(color for color, t in zip(colors, THRESHOLDS) if value >= t[col])


def rings(geometry):
    """Anneaux extérieurs et trous d'un Polygon/MultiPolygon GeoJSON."""
    if geometry["type"] == "Polygon":
        return geometry["coordinates"]
    return [ring for poly in geometry["coordinates"] for ring in poly]


class Projection:
    """Projection équirectangulaire locale, suffisante à l'échelle d'une intercommunalité."""

    def __init__(self, communes, x0, y0, width, height):
        pts = [p for c in communes for ring in rings(c["contour"]) for p in ring]
        lons, lats = [p[0] for p in pts], [p[1] for p in pts]
        self.k_lon = math.cos(math.radians((min(lats) + max(lats)) / 2))
        self.lon0, self.lat1 = min(lons), max(lats)
        span_x = (max(lons) - min(lons)) * self.k_lon
        span_y = max(lats) - min(lats)
        self.scale = min(width / span_x, height / span_y)
        self.x0 = x0 + (width - span_x * self.scale) / 2
        self.y0 = y0 + (height - span_y * self.scale) / 2

    def __call__(self, lon, lat):
        return (self.x0 + (lon - self.lon0) * self.k_lon * self.scale,
                self.y0 + (self.lat1 - lat) * self.scale)


def path_d(geometry, proj):
    parts = []
    for ring in rings(geometry):
        # Les contours IGN sont bien plus fins que le pixel : on saute les points à moins
        # d'1 px du précédent, ce qui divise le poids du SVG sans différence visible.
        pts = []
        for lon, lat in ring:
            x, y = proj(lon, lat)
            if not pts or abs(x - pts[-1][0]) + abs(y - pts[-1][1]) >= 1:
                pts.append((x, y))
        if len(pts) < 3:
            continue
        parts.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + "Z")
    return "".join(parts)


def pct(v):
    return "—" if v is None else f"{v:.0f} %"


def marker(x, y, res, colors, r_out=13, r_in=8.5):
    if not res["declared"]:
        return (f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r_out - 2.5}" fill="{C_BG}" '
                f'stroke="{C_NODATA}" stroke-width="2.5" stroke-dasharray="3 2.5"/>')
    ring = level_color(res["durable"], "durable", colors)
    fill = level_color(res["bio"], "bio", colors)
    return (f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r_out}" fill="{ring}" stroke="{C_INK}" stroke-opacity=".75" stroke-width="1.2"/>'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r_in}" fill="{fill}" stroke="{C_BG}" stroke-width="1.6"/>')


def place_labels(points, r, size):
    """Place le nom de chaque commune sous son rond, ou à défaut au-dessus, à droite, à
    gauche ou en diagonale : la première position qui ne touche ni un autre nom ni un autre rond. Sinon, celle
    qui empiète le moins. Largeur du texte estimée (pas de moteur de rendu ici)."""
    def box(lx, ly, anchor, w):
        left = {"middle": lx - w / 2, "start": lx, "end": lx - w}[anchor]
        return (left - 2, ly - size, left + w + 2, ly + size * 0.3)

    def overlap(a, b):
        return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))

    rings_ = [(x - r, y - r, x + r, y + r) for x, y, _, _ in points]
    placed, result = [], []
    for i, (x, y, name, _) in enumerate(points):
        w = len(name) * size * 0.6
        d = r * 0.7
        candidates = [
            (x, y + r + size + 1, "middle"),
            (x, y - r - 4, "middle"),
            (x + r + 4, y + size * 0.35, "start"),
            (x - r - 4, y + size * 0.35, "end"),
            (x + d, y + d + size, "start"),
            (x - d, y + d + size, "end"),
            (x + d, y - d - 2, "start"),
            (x - d, y - d - 2, "end"),
        ]
        obstacles = placed + [b for j, b in enumerate(rings_) if j != i]
        scored = [(sum(overlap(box(*cand, w), o) for o in obstacles), k, cand) for k, cand in enumerate(candidates)]
        _, _, best = min(scored)
        placed.append(box(*best, w))
        result.append(best)
    return result


def rank_communes(communes, results):
    """Communes ayant au moins une cantine, de la meilleure part de bio à la moins bonne
    (puis durable, puis nom) ; celles sans télédéclaration en dernier."""
    return sorted(
        (c for c in communes if results[c["code"]]["total"]),
        key=lambda c: (results[c["code"]]["bio"] is None, -(results[c["code"]]["bio"] or 0),
                       -(results[c["code"]]["durable"] or 0), c["nom"]),
    )


def map_title(epci, annee):
    return f"Cantines scolaires de la {epci['nom']} — EGALIM {annee}"


def render_svg(epci, communes, results, annee, palette="classique"):
    pal = PALETTES[palette]
    colors = pal["colors"]
    title_id = f"carte-titre{pal['suffix']}"  # unique : les deux versions cohabitent sur la page
    ranked = rank_communes(communes, results)
    # Le classement fixe la hauteur : une grande intercommunalité allonge l'image plutôt
    # que de tasser les lignes. Au-delà de 60 communes, ronds et noms rapetissent.
    row_h = 19
    dense = len(communes) > 60
    r_out, r_in, label_size = (9, 6, 9.5) if dense else (13, 8.5, 11.5)
    W = 1400
    MAP_X, MAP_Y, MAP_W = 30, 120, 860
    MAP_H = max(720, 50 + len(ranked) * row_h)
    H = MAP_Y + MAP_H + 160
    LIST_X = 930
    proj = Projection(communes, MAP_X, MAP_Y, MAP_W, MAP_H)

    out = [
        # Une image pour les lecteurs d'écran, plutôt qu'une suite de textes épars ; le
        # classement détaillé est donné en tableau sur la page de la carte.
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        f'font-family="Segoe UI, Helvetica, Arial, sans-serif" role="img" aria-labelledby="{title_id}">',
        f'<title id="{title_id}">{escape(map_title(epci, annee))} : carte et classement des communes selon '
        f'leur part de produits bio et de produits durables &amp; de qualité.</title>',
        f'<rect width="{W}" height="{H}" fill="{C_BG}"/>',
        f'<a class="nav" href="{GALLERY_URL}"><text x="30" y="26" font-size="13" fill="{C_MUTED}">← Toutes les cartes</text></a>',
        f'<text x="30" y="60" font-size="28" font-weight="700" fill="{C_INK}">'
        f'{escape(map_title(epci, annee))}</text>',
        f'<text x="30" y="90" font-size="16" fill="{C_MUTED}">Par commune : part de produits <tspan font-weight="700">bio</tspan> '
        f'au centre, part de produits <tspan font-weight="700">durables &amp; de qualité</tspan> sur l\'anneau. '
        f'Écoles et crèches.</text>',
    ]

    # Communes
    out.append(f'<g stroke="{C_LINE}" stroke-width="1" stroke-linejoin="round">')
    for c in communes:
        fill = C_COMMUNE if results[c["code"]]["total"] else C_COMMUNE_EMPTY
        out.append(f'<path d="{path_d(c["contour"], proj)}" fill="{fill}"><title>{escape(c["nom"])}</title></path>')
    out.append("</g>")

    # Ronds + noms (les communes sans cantine recensée n'ont pas de rond)
    points = []
    for c in communes:
        res = results[c["code"]]
        if res["total"]:
            x, y = proj(*c["centre"]["coordinates"])
            points.append((x, y, c["nom"], res))
    marks = [marker(x, y, res, colors, r_out, r_in) for x, y, _, res in points]
    labels = [
        f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" font-size="{label_size}" fill="{C_INK}" '
        f'stroke="{C_BG}" stroke-width="3" paint-order="stroke">{escape(name)}</text>'
        for (lx, ly, anchor), (_, _, name, _) in zip(place_labels(points, r_out, label_size), points)
    ]
    out += labels + marks

    # Classement
    y = MAP_Y + 6
    out.append(f'<text x="{LIST_X}" y="{y}" font-size="15" font-weight="700" fill="{C_INK}">Classement des communes</text>')
    y += 24
    out.append(f'<g font-size="12" fill="{C_MUTED}"><text x="{LIST_X + 250}" y="{y}" text-anchor="end">Bio</text>'
               f'<text x="{LIST_X + 330}" y="{y}" text-anchor="end">Durable</text>'
               f'<text x="{LIST_X + 430}" y="{y}" text-anchor="end">Cantines</text></g>')
    y += 8
    for i, c in enumerate(ranked, start=1):
        res = results[c["code"]]
        y += row_h
        cy = y - 4
        rank = f"{i}." if res["declared"] else ""
        out.append(
            f'<g font-size="12.5" fill="{C_INK}">'
            f'<text x="{LIST_X + 18}" y="{y}" text-anchor="end" fill="{C_MUTED}">{rank}</text>'
            f'{marker(LIST_X + 32, cy, res, colors, r_out=7, r_in=4.5)}'
            f'<text x="{LIST_X + 46}" y="{y}">{escape(c["nom"])}</text>'
            f'<text x="{LIST_X + 250}" y="{y}" text-anchor="end" font-weight="600">{pct(res["bio"])}</text>'
            f'<text x="{LIST_X + 330}" y="{y}" text-anchor="end">{pct(res["durable"])}</text>'
            f'<text x="{LIST_X + 430}" y="{y}" text-anchor="end" fill="{C_MUTED}">{res["declared"]}/{res["total"]}</text>'
            f'</g>')

    # Légende
    ly = MAP_Y + MAP_H + 30
    out.append(f'<g font-size="13" fill="{C_INK}">')
    out.append(f'<text x="30" y="{ly}" font-weight="700">Lecture</text>')
    lx = 30
    for i, (color, (bio_min, dur_min)) in enumerate(zip(colors, THRESHOLDS)):
        if i == 0:
            bio_txt, dur_txt = f"≥ {bio_min}", f"≥ {dur_min}"
        elif i == len(THRESHOLDS) - 1:
            bio_txt, dur_txt = f"&lt; {THRESHOLDS[i - 1][0]}", f"&lt; {THRESHOLDS[i - 1][1]}"
        else:
            bio_txt, dur_txt = f"{bio_min}–{THRESHOLDS[i - 1][0]}", f"{dur_min}–{THRESHOLDS[i - 1][1]}"
        out.append(f'<rect x="{lx}" y="{ly + 14}" width="16" height="16" rx="3" fill="{color}" '
                   f'stroke="{C_INK}" stroke-opacity=".75"/>'
                   f'<text x="{lx + 23}" y="{ly + 27}">bio {bio_txt} % · durable {dur_txt} %</text>')
        lx += 212
    out.append(f'<circle cx="{lx + 8}" cy="{ly + 22}" r="7" fill="{C_BG}" stroke="{C_NODATA}" stroke-width="2.5" stroke-dasharray="3 2.5"/>'
               f'<text x="{lx + 23}" y="{ly + 27}">pas de télédéclaration</text>')
    out.append(f'<text x="30" y="{ly + 54}" fill="{C_MUTED}" font-size="12">Vert : objectif EGALIM atteint '
               f'({OBJ_BIO} % de bio, {OBJ_DURABLE} % de produits durables &amp; de qualité dont le bio), '
               f'd\'autant plus foncé qu\'il est dépassé. {pal["low_names"][0]} : au moins la moitié de l\'objectif. '
               f'{pal["low_names"][1]} : moins de la moitié.</text>')
    out.append("</g>")

    # Source, et où trouver l'autre version des couleurs (utile sur une carte imprimée ou transférée)
    out.append(
        f'<g font-size="11.5" fill="{C_MUTED}">'
        f'<text x="30" y="{H - 54}">{pal["other_note"]} : biguhuh.github.io/cartes-egalim.html</text>'
        f'<text x="30" y="{H - 36}">Valeur d\'une commune : moyenne de ses cantines déclarées, pondérée par le nombre de repas. '
        f'« Cantines » : déclarées / recensées.</text>'
        f'<text x="30" y="{H - 18}">Sources : télédéclarations EGALIM {annee} (ma-cantine, data.gouv.fr), registre national '
        f'des cantines ; contours IGN via geo.api.gouv.fr. Généré le {date.today():%d/%m/%Y} — '
        f'biguhuh.github.io/map_cantines_egalim</text></g>')
    out.append("</svg>")
    return "\n".join(out)


def slugify(text):
    text = text.lower()
    for a, b in (("àâä", "a"), ("éèêë", "e"), ("îï", "i"), ("ôö", "o"), ("ùûü", "u"), ("ç", "c")):
        text = re.sub(f"[{a}]", b, text)
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def main():
    parser = argparse.ArgumentParser(description="Carte fixe EGALIM des communes d'une intercommunalité.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--epci", help="Code SIREN de l'intercommunalité (ex. 200041317 pour la CA du Niortais).")
    target.add_argument("--tous", action="store_true",
                        help="Toutes les intercommunalités des départements couverts, plus la page de galerie.")
    parser.add_argument("--page", type=Path, default=GALLERY_FILE,
                        help=f"Page de galerie écrite avec --tous (par défaut : {GALLERY_FILE}).")
    parser.add_argument("--annee", help="Année EGALIM (par défaut : la plus récente).")
    parser.add_argument("--out", type=Path, help="Fichier SVG de sortie, avec --epci (par défaut : docs/cartes/<epci>-<année>.svg).")
    args = parser.parse_args()

    page = config.OUTPUT_FILE.read_text(encoding="utf-8")
    cantines = load_embedded("CANTINES", page)
    td = load_embedded("TD_EMBED", page)
    annee = args.annee or max(td)
    if annee not in td:
        raise SystemExit(f"Année {annee} absente des données (disponibles : {', '.join(sorted(td))})")

    session = requests.Session()
    deps = epcis_of_departments(config.DEPARTMENTS, session) if args.tous else {args.epci: None}
    generated = []
    for code, dep in deps.items():
        epci = fetch_epci(code, session)
        communes = fetch_communes(code, session)
        results = commune_results(communes, cantines, td[annee])

        out = (args.out if not args.tous and args.out else
               CARTES_DIR / f"{slugify(epci['nom'])}-{annee}.svg")
        out.parent.mkdir(parents=True, exist_ok=True)
        svgs = {}
        for palette, pal in PALETTES.items():
            path = out.with_name(out.stem + pal["suffix"] + ".svg")
            svg = render_svg(epci, communes, results, annee, palette)
            path.write_text(svg, encoding="utf-8")
            svgs[palette] = (svg, path.name)
        out.with_suffix(".html").write_text(
            render_map_page(epci, annee, svgs, rank_communes(communes, results), results),
            encoding="utf-8")

        n_with = sum(1 for r in results.values() if r["total"])
        n_decl = sum(1 for r in results.values() if r["declared"])
        generated.append((epci, dep, out, len(communes), n_with, n_decl))
        print(f"{epci['nom']} ({annee}) : {len(communes)} communes, {n_with} avec cantine, "
              f"{n_decl} avec télédéclaration -> {out}")

    if args.tous:
        if args.page.parent.is_dir():
            args.page.write_text(render_gallery(generated, annee), encoding="utf-8")
            print(f"Galerie -> {args.page}")
        else:
            print(f"Galerie non écrite : dossier {args.page.parent} introuvable (voir --page).")


def epcis_of_departments(departements, session):
    """{code SIREN: département} des intercommunalités ayant au moins une commune dans ces
    départements. Une intercommunalité à cheval est rangée dans le premier département listé."""
    deps = {}
    for dep in departements:
        r = session.get(f"{GEO_API}/departements/{dep}/communes", params={"fields": "codeEpci"},
                        timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        for c in r.json():
            if c.get("codeEpci"):
                deps.setdefault(c["codeEpci"], dep)
    return dict(sorted(deps.items()))


def render_map_page(epci, annee, svgs, ranked, results):
    """Page d'une carte : la carte en grand, de quoi la télécharger en PDF A4 ou en SVG, et le
    classement en tableau HTML (lisible par les lecteurs d'écran et sur mobile, ce que le
    texte de l'image ne permet pas). svgs : {palette: (svg, nom du fichier)}.

    Les deux versions des couleurs sont intégrées ; un attribut sur <html>, mémorisé dans le
    navigateur et partagé avec la galerie, choisit celle qui s'affiche, s'imprime et se
    télécharge.

    Le PDF passe par la fenêtre d'impression du navigateur, réglée en A4 dans l'orientation
    de la carte : c'est le seul moyen sans dépendance de produire un A4 fidèle au vectoriel."""
    m = re.search(r'viewBox="0 0 (\d+) (\d+)"', svgs["classique"][0])
    w, h = int(m.group(1)), int(m.group(2))
    orientation = "landscape" if w >= h else "portrait"
    # Les cartes sont intégrées telles quelles (et non via <img>) pour que la page puisse en
    # masquer le lien de navigation à l'impression ; leurs dimensions fixes sont laissées au CSS.
    fixed_size = re.compile(r' width="\d+" height="\d+"')
    versions = "\n".join(
        f'<div class="version" data-palette="{palette}">\n{fixed_size.sub("", svg, count=1)}\n</div>'
        for palette, (svg, _) in svgs.items())
    svg_links = " ".join(f'data-{palette}="{escape(name)}"' for palette, (_, name) in svgs.items())
    title = map_title(epci, annee)

    rows = []
    for i, c in enumerate(ranked, start=1):
        res = results[c["code"]]
        rank = str(i) if res["declared"] else "—"
        rows.append(
            f'      <tr><td class="num">{rank}</td><th scope="row">{escape(c["nom"])}</th>'
            f'<td class="num">{pct(res["bio"])}</td><td class="num">{pct(res["durable"])}</td>'
            f'<td class="num">{res["declared"]} / {res["total"]}</td></tr>')
    table_rows = "\n".join(rows)
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
{PALETTE_HEAD_SCRIPT}
<style>
  :root {{ --bg: #f7f7f5; --text: #1a1a1a; --muted: #5a5a5a; --accent: #2f6f4f; --border: #e3e2dd; --btn-bg: #ffffff; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg: #14161a; --text: #f0f0ee; --muted: #a3a6ab; --accent: #6fcf97; --border: #2c2f35; --btn-bg: #1d2025; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--text);
         font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }}
  .bar {{ max-width: 1440px; margin: 0 auto; padding: 20px 16px 12px; display: flex; flex-wrap: wrap;
         align-items: center; justify-content: space-between; gap: 12px; }}
  .back {{ font-size: 14px; color: var(--muted); text-decoration: none; }}
  .back:hover {{ color: var(--accent); }}
  .actions {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  .btn {{ font: inherit; font-size: 14px; font-weight: 600; padding: 9px 14px; border-radius: 8px; cursor: pointer;
         border: 1px solid var(--border); background: var(--btn-bg); color: var(--text); text-decoration: none; }}
  .btn.primary {{ background: var(--accent); border-color: var(--accent); color: #fff; }}
  @media (prefers-color-scheme: dark) {{ .btn.primary {{ color: #10161d; }} }}
  .btn:hover {{ border-color: var(--accent); }}
  .hint {{ max-width: 1440px; margin: 0 auto; padding: 0 16px 12px; font-size: 13px; color: var(--muted); }}
  .map {{ max-width: 1440px; margin: 0 auto 40px; padding: 0 16px; }}
  .map svg {{ display: block; width: 100%; height: auto; border: 1px solid var(--border); border-radius: 10px; background: #fff; }}
  .map svg .nav {{ display: none; }}
  /* Une seule version des couleurs visible (et donc imprimée) à la fois. */
  .version[data-palette="daltonien"] {{ display: none; }}
  html[data-palette="daltonien"] .version[data-palette="classique"] {{ display: none; }}
  html[data-palette="daltonien"] .version[data-palette="daltonien"] {{ display: block; }}
{PALETTE_TOGGLE_CSS}
  .sr-only {{ position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden;
             clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }}
  .ranking {{ max-width: 760px; margin: 0 auto 56px; padding: 0 16px; }}
  .ranking h2 {{ font-size: 20px; margin: 0 0 6px; }}
  .ranking p {{ color: var(--muted); font-size: 14px; margin: 0 0 12px; line-height: 1.5; text-align: justify; hyphens: auto; }}
  .ranking table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  .ranking th, .ranking td {{ padding: 7px 8px; border-bottom: 1px solid var(--border); text-align: left; }}
  .ranking thead th {{ color: var(--muted); font-weight: 600; font-size: 13px; }}
  .ranking tbody th {{ font-weight: 500; }}
  .ranking .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .ranking td.num {{ white-space: nowrap; }}
  @media (max-width: 480px) {{
    .ranking table {{ font-size: 13px; }}
    .ranking th, .ranking td {{ padding: 6px 4px; }}
  }}
  @page {{ size: A4 {orientation}; margin: 8mm; }}
  @media print {{
    body {{ background: #fff; }}
    .bar, .hint, .ranking {{ display: none; }}
    .map {{ max-width: none; margin: 0; padding: 0; }}
    /* La carte tient sur une seule page A4, dans ses proportions. */
    .map svg {{ border: 0; border-radius: 0; width: auto; height: auto;
               max-width: 100%; max-height: {"194mm" if orientation == "landscape" else "281mm"}; margin: 0 auto; }}
  }}
</style>
</head>
<body>
<div class="bar">
  <a class="back" href="{GALLERY_URL}">← Toutes les cartes</a>
  <div class="actions">
    {PALETTE_TOGGLE_BUTTON}
    <button class="btn primary" type="button" onclick="window.print()">⬇ Télécharger en PDF (A4)</button>
    <a class="btn" id="svgLink" href="{escape(svgs["classique"][1])}" {svg_links} download>Image SVG</a>
  </div>
</div>
<main>
<h1 class="sr-only">{escape(title)}</h1>
<p class="hint">Pour le PDF, choisissez « Enregistrer au format PDF » comme imprimante. La page est déjà réglée en A4 {"paysage" if orientation == "landscape" else "portrait"}.</p>
<div class="map">
{versions}
</div>
<section class="ranking" aria-labelledby="classement">
  <h2 id="classement">Classement des communes</h2>
  <p>Part de produits bio et de produits durables &amp; de qualité dans les cantines des écoles et
    crèches de chaque commune, en {annee}. Objectifs EGALIM : {OBJ_BIO} % de bio, {OBJ_DURABLE} % de
    produits durables &amp; de qualité. Valeur d'une commune : moyenne de ses cantines déclarées,
    pondérée par le nombre de repas.</p>
  <table>
    <caption class="sr-only">Classement des communes de la {escape(epci["nom"])} par part de produits bio, EGALIM {annee}</caption>
    <thead>
      <tr><th scope="col" class="num">Rang</th><th scope="col">Commune</th><th scope="col" class="num">Bio</th>
        <th scope="col" class="num">Durable &amp; qualité</th><th scope="col" class="num">Cantines déclarées</th></tr>
    </thead>
    <tbody>
{table_rows}
    </tbody>
  </table>
</section>
</main>
{PALETTE_TOGGLE_SCRIPT}
</body>
</html>
"""


def render_gallery(generated, annee):
    """Page de la galerie (racine du site) : un onglet par département, une vignette
    cliquable par carte."""
    def card(epci, out, n_communes, n_with, n_decl):
        srcs = {p: CARTES_URL + escape(out.stem + pal["suffix"] + ".svg") for p, pal in PALETTES.items()}
        return (
            f'      <a class="card" href="{CARTES_URL}{escape(out.with_suffix(".html").name)}">\n'
            f'        <img src="{srcs["classique"]}" data-classique="{srcs["classique"]}" data-daltonien="{srcs["daltonien"]}" '
            f'alt="Carte EGALIM {annee} de la {escape(epci["nom"])}" loading="lazy">\n'
            f'        <h2>{escape(epci["nom"])}</h2>\n'
            f'        <p>{n_decl} communes déclarées sur {n_with} avec cantine · {n_communes} communes</p>\n'
            f'      </a>')

    deps = [d for d in config.DEPARTMENTS if any(g[1] == d for g in generated)]
    tabs, panels = [], []
    for i, dep in enumerate(deps):
        name = DEPT_NAMES.get(dep, f"Département {dep}")
        rows = sorted((g for g in generated if g[1] == dep), key=lambda g: g[0]["nom"].replace('"', "").casefold())
        tabs.append(
            f'    <button role="tab" id="tab-{dep}" aria-controls="dep-{dep}" data-dep="{dep}" '
            f'aria-selected="{"true" if i == 0 else "false"}" tabindex="{0 if i == 0 else -1}">'
            f'{escape(name)} ({dep}) <span>{len(rows)}</span></button>')
        cards = "\n".join(card(epci, out, n_c, n_w, n_d) for epci, _, out, n_c, n_w, n_d in rows)
        panels.append(
            f'  <section class="dep" id="dep-{dep}" role="tabpanel" aria-labelledby="tab-{dep}">\n'
            f'    <h2 class="dep-title">{escape(name)} ({dep})</h2>\n'
            f'    <div class="grid">\n{cards}\n    </div>\n'
            f'  </section>')
    tabs_html, panels_html = "\n".join(tabs), "\n".join(panels)
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cartes EGALIM {annee} par intercommunalité</title>
<meta name="description" content="Cartes EGALIM {annee} figées, une par intercommunalité de Charente-Maritime et des Deux-Sèvres.">
<!-- Page générée par map_cantines_egalim/src/static_map.py (--tous) : ne pas modifier à la main. -->
{PALETTE_HEAD_SCRIPT}
<style>
  :root {{
    --bg: #f7f7f5;
    --card-bg: #ffffff;
    --text: #1a1a1a;
    --muted: #5a5a5a;
    --accent: #2f6f4f;
    --border: #e3e2dd;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #14161a;
      --card-bg: #1d2025;
      --text: #f0f0ee;
      --muted: #a3a6ab;
      --accent: #6fcf97;
      --border: #2c2f35;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }}
  main {{ max-width: 1100px; margin: 0 auto; padding: 64px 20px 80px; }}
  .back {{ display: inline-block; margin-bottom: 24px; font-size: 14px; color: var(--muted); text-decoration: none; }}
  .back:hover {{ color: var(--accent); }}
  header {{ margin-bottom: 32px; max-width: 780px; }}
  h1 {{ font-size: 28px; margin: 0 0 12px; line-height: 1.25; }}
  header p {{ color: var(--muted); margin: 0 0 8px; font-size: 15px; line-height: 1.55;
             text-align: justify; hyphens: auto; }}
  header a {{ color: var(--accent); }}
  .btn {{ font: inherit; font-size: 14px; font-weight: 600; padding: 9px 14px; border-radius: 8px; cursor: pointer;
         border: 1px solid var(--border); background: var(--card-bg); color: var(--text); margin-top: 8px; }}
  .btn:hover {{ border-color: var(--accent); }}
{PALETTE_TOGGLE_CSS}
  /* Onglets par département. Sans JavaScript, les onglets restent cachés et les départements
     s'affichent l'un sous l'autre, chacun avec son titre. */
  .tabs {{ display: none; gap: 4px; border-bottom: 1px solid var(--border); margin-bottom: 24px; flex-wrap: wrap; }}
  .js .tabs {{ display: flex; }}
  .tabs button {{ font: inherit; font-size: 15px; font-weight: 600; background: none; border: 0; cursor: pointer;
                 color: var(--muted); padding: 10px 14px; border-bottom: 3px solid transparent; margin-bottom: -1px; }}
  .tabs button:hover {{ color: var(--text); }}
  .tabs button[aria-selected="true"] {{ color: var(--accent); border-bottom-color: var(--accent); }}
  .tabs button span {{ font-weight: 400; font-size: 13px; color: var(--muted); margin-left: 4px; }}
  .dep + .dep {{ margin-top: 40px; }}
  .dep-title {{ font-size: 20px; margin: 0 0 16px; }}
  .js .dep-title {{ display: none; }}
  .js .dep + .dep {{ margin-top: 0; }}
  .grid {{ display: grid; gap: 16px; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); }}
  a.card {{
    display: block;
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 12px 12px 16px;
    text-decoration: none;
    color: inherit;
    transition: border-color 0.15s ease, transform 0.15s ease;
  }}
  a.card:hover {{ border-color: var(--accent); transform: translateY(-1px); }}
  /* Les cartes ont un fond blanc fixe : on garde la vignette lisible en mode sombre. */
  .card img {{ display: block; width: 100%; aspect-ratio: 7 / 5; object-fit: cover; object-position: top left;
              border-radius: 8px; background: #fff; border: 1px solid var(--border); }}
  .card h2 {{ margin: 12px 4px 4px; font-size: 16px; color: var(--accent); }}
  .card p {{ margin: 0 4px; font-size: 13px; color: var(--muted); text-align: justify; hyphens: auto; }}
</style>
</head>
<body>
<main>
  <a class="back" href="./">← Tous les projets</a>
  <header>
    <h1>Cartes EGALIM {annee} par intercommunalité</h1>
    <p>Une carte figée par intercommunalité de Charente-Maritime et des Deux-Sèvres. Pour chaque
      commune, la part de bio et de produits durables &amp; de qualité dans les cantines de ses écoles
      et crèches, comparée aux objectifs EGALIM et aux communes voisines.</p>
    <p>Pour explorer cantine par cantine, voir la
      <a href="https://biguhuh.github.io/map_cantines_egalim/">carte interactive</a>.</p>
    {PALETTE_TOGGLE_BUTTON}
  </header>
  <div class="tabs" role="tablist" aria-label="Départements">
{tabs_html}
  </div>
{panels_html}
</main>
<script>
  // Onglets : l'onglet actif suit l'adresse (#17, #79) pour pouvoir partager le lien d'un département.
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  function show(dep, focus) {{
    if (!tabs.some(t => t.dataset.dep === dep)) dep = tabs[0].dataset.dep;
    tabs.forEach(t => {{
      const on = t.dataset.dep === dep;
      t.setAttribute("aria-selected", on);
      t.tabIndex = on ? 0 : -1;
      document.getElementById("dep-" + t.dataset.dep).hidden = !on;
      if (on && focus) t.focus();
    }});
  }}
  tabs.forEach((t, i) => {{
    t.addEventListener("click", () => {{ history.replaceState(null, "", "#" + t.dataset.dep); show(t.dataset.dep); }});
    t.addEventListener("keydown", e => {{
      const d = {{ArrowRight: 1, ArrowLeft: -1}}[e.key];
      if (!d) return;
      const next = tabs[(i + d + tabs.length) % tabs.length];
      history.replaceState(null, "", "#" + next.dataset.dep);
      show(next.dataset.dep, true);
    }});
  }});
  addEventListener("hashchange", () => show(location.hash.slice(1)));
  show(location.hash.slice(1));
</script>
{PALETTE_TOGGLE_SCRIPT}
</body>
</html>
"""


if __name__ == "__main__":
    main()
