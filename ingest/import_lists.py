"""Henter kortnavne fra en Archidekt- eller Moxfield-URL serverside.
Klienten kan ikke selv gøre det pga. CORS, så nat-jobbet klarer det."""
import json
import re
import urllib.request

HEADERS = {
    "User-Agent": "BinderTutor/1.0 (github.com/binder-tutor)",
    "Accept": "application/json",
}


def _json(url: str):
    req = urllib.request.Request(url, headers=HEADERS)
    return json.load(urllib.request.urlopen(req))


def enrich(names: list[str]) -> dict[str, dict]:
    """Slå kortnavne op hos Scryfall og returnér
    {navn.lower(): {'scryfallId', 'set', 'cn'}}.
    Bruger /cards/collection (op til 75 identifiers pr. POST)."""
    uniq = list({n for n in names if n})
    out: dict[str, dict] = {}
    for i in range(0, len(uniq), 75):
        batch = uniq[i:i + 75]
        body = json.dumps(
            {"identifiers": [{"name": n} for n in batch]}).encode()
        req = urllib.request.Request(
            "https://api.scryfall.com/cards/collection", data=body,
            headers={**HEADERS, "Content-Type": "application/json"},
            method="POST")
        j = json.load(urllib.request.urlopen(req))
        for c in j.get("data", []):
            out[c["name"].lower()] = {
                "scryfallId": c["id"],
                "set": (c.get("set") or "").upper(),
                "cn": c.get("collector_number", ""),
            }
    return out


def fetch_names(url: str) -> list[str]:
    """Returnér kortnavne fra en deck/collection/wishlist-URL."""
    m = re.search(r"archidekt\.com/(?:decks|collection)/(\d+)", url)
    if m:
        j = _json(f"https://archidekt.com/api/decks/{m.group(1)}/")
        return [
            c["card"]["oracleCard"]["name"]
            for c in j.get("cards", [])
            if c.get("card", {}).get("oracleCard", {}).get("name")
        ]

    m = re.search(r"moxfield\.com/collection/([\w-]+)", url)
    if m:
        names, page = [], 1
        while True:
            j = _json("https://api2.moxfield.com/v1/collections/"
                      f"{m.group(1)}?pageNumber={page}&pageSize=100")
            for row in j.get("data", []):
                c = row.get("card", row)
                if c.get("name"):
                    names.append(c["name"])
            if page >= j.get("totalPages", 1):
                break
            page += 1
        return names

    m = re.search(r"moxfield\.com/decks/([\w-]+)", url)
    if m:
        j = _json(f"https://api2.moxfield.com/v3/decks/all/{m.group(1)}")
        names = []
        for board in (j.get("boards") or {}).values():
            for c in (board.get("cards") or {}).values():
                n = (c.get("card") or {}).get("name")
                if n:
                    names.append(n)
        return names

    raise ValueError(f"ukendt URL (kun Archidekt/Moxfield): {url}")
