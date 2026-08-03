"""Henter Scryfall bulk 'default_cards' og bygger et opslag pr. scryfall-ID.

Kortdata vedligeholdes IKKE lokalt — Scryfall er eneste kilde til både:
  - EUR-priser (via Cardmarket)
  - de gameplay-felter frontenden filtrerer på: mana value, farveidentitet,
    farver, typelinje, regeltekst og manaomkostning

Scryfall kræver en beskrivende User-Agent + Accept-header (ellers 400).
Bulk-formatet er gzippet JSONL (ét kortobjekt pr. linje) med linket i feltet
'jsonl_download_uri' — ikke længere en JSON-array i 'download_uri'.

Filen er ~500 MB udpakket, så den streames linje for linje og filtreres ned til
de ID'er vi faktisk bruger, i stedet for at ligge i hukommelsen som helhed."""
import gzip
import json
import urllib.request

BULK_URL = "https://api.scryfall.com/bulk-data/default_cards"

HEADERS = {
    "User-Agent": "BinderTutor/1.0 (github.com/binder-tutor)",
    "Accept": "application/json",
}


def _get_json(url: str):
    req = urllib.request.Request(url, headers=HEADERS)
    return json.load(urllib.request.urlopen(req))


def _face_text(c: dict, key: str) -> str:
    """oracle_text/type_line/mana_cost ligger på card_faces for DFC'er og
    split-kort. Saml dem, så fritekstsøgning også rammer bagsiden."""
    v = c.get(key)
    if v:
        return v
    parts = [f.get(key) for f in (c.get("card_faces") or []) if f.get(key)]
    return "\n//\n".join(parts)


def _colors(c: dict) -> list:
    """Top-level 'colors' mangler på DFC'er — saml unionen fra faces."""
    if c.get("colors") is not None:
        return c["colors"]
    out = set()
    for f in c.get("card_faces") or []:
        out.update(f.get("colors") or [])
    return sorted(out)


def _entry(c: dict) -> dict:
    p = c.get("prices") or {}
    eur, eurf = p.get("eur"), p.get("eur_foil")
    return {
        "eur": float(eur) if eur else None,
        "eur_foil": float(eurf) if eurf else None,
        "cmc": c.get("cmc"),
        "ci": c.get("color_identity") or [],
        "colors": _colors(c),
        "type": _face_text(c, "type_line"),
        "text": _face_text(c, "oracle_text"),
        "mana": _face_text(c, "mana_cost"),
    }


def load_card_map(ids: set[str] | None = None) -> dict[str, dict]:
    """Returnér {scryfallId: {eur, eur_foil, cmc, ci, colors, type, text, mana}}.

    ids: begræns til de kort vi faktisk har brug for (typisk alle kort i
    samlingerne). None = behold alt (~90.000 kort, langt tungere i hukommelsen).
    """
    meta = _get_json(BULK_URL)

    # Nyt format: gzippet JSONL i 'jsonl_download_uri'. Fald tilbage til den
    # gamle JSON-array i 'download_uri', hvis Scryfall ruller tilbage.
    jsonl_url = meta.get("jsonl_download_uri")
    array_url = meta.get("download_uri")
    if not jsonl_url and not array_url:
        raise RuntimeError(f"intet download-link; felter: {sorted(meta.keys())}")

    out: dict[str, dict] = {}

    if jsonl_url:
        req = urllib.request.Request(jsonl_url, headers=HEADERS)
        with urllib.request.urlopen(req) as resp:
            stream = gzip.GzipFile(fileobj=resp) if jsonl_url.endswith(".gz") else resp
            for line in stream:
                line = line.strip()
                if not line:
                    continue
                c = json.loads(line)
                cid = c.get("id")
                if cid and (ids is None or cid in ids):
                    out[cid] = _entry(c)
    else:
        for c in _get_json(array_url):
            cid = c.get("id")
            if cid and (ids is None or cid in ids):
                out[cid] = _entry(c)

    return out


# Bagudkompatibelt alias — funktionen hed tidligere load_price_map().
def load_price_map(ids: set[str] | None = None) -> dict[str, dict]:
    return load_card_map(ids)


def price_of(card: dict, cmap: dict) -> float | None:
    """Bedste EUR-pris for et kort (foil-pris hvis foil)."""
    p = cmap.get(card.get("scryfallId"))
    if not p:
        return None
    return (p["eur_foil"] if card.get("foil") else p["eur"]) or p["eur"]
