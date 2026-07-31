"""Henter Scryfall bulk 'default_cards' og bygger et prisopslag
pr. scryfall-ID. EUR-priser kommer fra Cardmarket via Scryfall.

Scryfall kræver en beskrivende User-Agent + Accept-header (ellers 400).
Bulk-formatet er nu gzippet JSONL (ét kortobjekt pr. linje) med linket
i feltet 'jsonl_download_uri' - ikke længere en JSON-array i 'download_uri'."""
import gzip
import json
import urllib.request

HEADERS = {
    "User-Agent": "BinderTutor/1.0 (github.com/binder-tutor)",
    "Accept": "application/json",
}


def _get_json(url: str):
    req = urllib.request.Request(url, headers=HEADERS)
    return json.load(urllib.request.urlopen(req))


def _get_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    return urllib.request.urlopen(req).read()


def _add(out: dict, c: dict) -> None:
    p = c.get("prices") or {}
    eur = p.get("eur")
    eurf = p.get("eur_foil")
    out[c["id"]] = {
        "eur": float(eur) if eur else None,
        "eur_foil": float(eurf) if eurf else None,
    }


def load_price_map() -> dict[str, dict]:
    """Returnér {scryfallId: {'eur': float|None, 'eur_foil': float|None}}."""
    meta = _get_json("https://api.scryfall.com/bulk-data/default_cards")

    # Nyt format: gzippet JSONL i 'jsonl_download_uri'. Fald tilbage til
    # den gamle JSON-array i 'download_uri', hvis Scryfall ruller tilbage.
    jsonl_url = meta.get("jsonl_download_uri")
    array_url = meta.get("download_uri")
    if not jsonl_url and not array_url:
        raise RuntimeError(f"intet download-link; felter: {sorted(meta.keys())}")

    out: dict[str, dict] = {}
    if jsonl_url:
        raw = _get_bytes(jsonl_url)
        if jsonl_url.endswith(".gz"):
            raw = gzip.decompress(raw)
        for line in raw.splitlines():
            line = line.strip()
            if line:
                _add(out, json.loads(line))
    else:
        for c in _get_json(array_url):
            _add(out, c)
    return out


def price_of(card: dict, pmap: dict) -> float | None:
    """Bedste EUR-pris for et kort (foil-pris hvis foil)."""
    p = pmap.get(card.get("scryfallId"))
    if not p:
        return None
    return (p["eur_foil"] if card.get("foil") else p["eur"]) or p["eur"]
