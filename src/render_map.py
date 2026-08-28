"""Injection des données dans le template HTML pour produire la carte finale."""
import json

from . import config
from .utils import format_fr


def _safe_json(value):
    """JSON compact ; échappe `</` pour ne jamais casser le tag <script> englobant."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def render(cantines, td_embed, epci_by_insee, generated_at):
    template = config.TEMPLATE_FILE.read_text(encoding="utf-8")

    years = sorted(td_embed.keys())
    years_range = f"{years[0]} → {years[-1]}" if years else "—"

    html = (
        template
        .replace("__CANTINES_JSON__", _safe_json(cantines))
        .replace("__TD_EMBED_JSON__", _safe_json(td_embed))
        .replace("__EPCI_JSON__", _safe_json(epci_by_insee))
        .replace("__CANTINES_COUNT__", format_fr(len(cantines)))
        .replace("__YEARS_RANGE__", years_range)
        .replace("__GENERATED_AT__", generated_at)
    )

    config.OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.OUTPUT_FILE.write_text(html, encoding="utf-8")
    return config.OUTPUT_FILE
