"""Suivi de la version des données déjà traitées (pour ne reconstruire la carte
que lorsqu'une nouvelle version est publiée sur data.gouv.fr)."""
import json

from . import config


def load_state():
    if not config.STATE_FILE.exists():
        return {}
    with open(config.STATE_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    config.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(config.STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)


def build_current_meta(registre_resource, td_resources):
    return {
        "registre": registre_resource,
        "teledeclarations": td_resources,
    }


def has_changed(current_meta, previous_state):
    return current_meta != previous_state
