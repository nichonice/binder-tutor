"""Henter Scryfall bulk 'default_cards' og bygger et prisopslag
pr. scryfall-ID. EUR-priser kommer fra Cardmarket via Scryfall."""
import json
import urllib.request


def load_price_map() -> dict[str, dict]:
    """Returnér {scryfallId: {'eur': float|None, 'eur_foil': float|None}}."""
    meta = json.load(urllib.request.urlopen(
        "https://api.scryfall.com/bulk-data/default-cards"))
    url = meta["download_uri"]
    data = json.load(urllib.request.urlopen(url))
    out = {}
    for c in data:
        p = c.get("prices") or {}
        eur = p.get("eur")
        eurf = p.get("eur_foil")
        out[c["id"]] = {
            "eur": float(eur) if eur else None,
            "eur_foil": float(eurf) if eurf else None,
        }
    return out


def price_of(card: dict, pmap: dict) -> float | None:
    """Bedste EUR-pris for et kort (foil-pris hvis foil)."""
    p = pmap.get(card.get("scryfallId"))
    if not p:
        return None
    return (p["eur_foil"] if card.get("foil") else p["eur"]) or p["eur"]
