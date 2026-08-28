"""Petites fonctions utilitaires partagées."""
import re


def digits(value):
    """Ne garde que les chiffres d'une chaîne (normalisation des SIRET)."""
    return re.sub(r"\D", "", value or "")


def format_fr(n):
    """Formate un entier avec des espaces comme séparateur de milliers (ex: 1 081)."""
    return f"{n:,}".replace(",", " ")
