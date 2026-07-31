"""Henter Scryfall bulk 'default_cards' og bygger et prisopslag
pr. scryfall-ID. EUR-priser kommer fra Cardmarket via Scryfall.

Scryfall kræver en beskrivende User-Agent + Accept-header på alle kald;
uden dem svarer de HTTP 400 Bad Request."""
import json
import urllib.request

HEADERS = {
    "User-Agent": "BinderTutor/1.0 (github.com/binder-tutor)",
    "Accept": "application/json",
}


def _get_json(url: str):
    req = urllib.request.Request(url, headers=HEADERS)
    return json.load(urllib.request.urlopen(req))


def load_price_map() -> dict[str, dict]:
    """Returnér {scryfallId: {'eur': float|None, 'eur_foil': float|None}}."""
    # Hent hele bulk-data-listen og find default_cards-entryen - mere robust
    # end by-type-endpointet, som kan svare uden download_uri.
    listing = _get_json("https://api.scryfall.com/bulk-data")
    entries = listing.get("data", [])
    meta = next((e for e in entries if e.get("type") == "default_cards"), None)
    if not meta or "download_uri" not in meta:
        types = [e.get("type") for e in entries]
        raise RuntimeError(f"default_cards ikke fundet i bulk-data (fik: {types})")
    data = _get_json(meta["download_uri"])
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
