"""Parser for ManaBox' CSV-eksport.

ManaBox' egen `.backup`-fil er AES-krypteret (Hive-box med nøglen i telefonens
secure storage) og kan ikke læses serverside. CSV-eksporten er derfor eneste
brugbare kilde — se `fetch_drive.newest_file()`, der prioriterer .csv."""
import csv
import io


def _first(row: dict, *keys: str) -> str:
    """Første ikke-tomme kolonne blandt keys. ManaBox har skiftet
    kolonnenavne før, så vi accepterer flere varianter."""
    for k in keys:
        v = row.get(k)
        if v and v.strip():
            return v.strip()
    return ""


def parse_csv(raw: bytes) -> list[dict]:
    """ManaBox CSV-eksport -> normaliseret kortliste."""
    text = raw.decode("utf-8-sig")
    cards = []
    for r in csv.DictReader(io.StringIO(text)):
        cards.append({
            "name": r["Name"].strip(),
            "set": r["Set code"].upper(),
            "setName": r.get("Set name", ""),
            "cn": r.get("Collector number", ""),
            "foil": r.get("Foil", "normal") != "normal",
            "qty": int(r.get("Quantity") or 1),
            "condition": (r.get("Condition") or "").replace("_", " "),
            "lang": r.get("Language", "en"),
            "rarity": r.get("Rarity", ""),
            "scryfallId": r.get("Scryfall ID", ""),
            "binder": _first(r, "Binder Name", "Binder", "binder_name"),
            "binderType": _first(r, "Binder Type", "binder_type"),
        })
    return cards


def parse(filename: str, raw: bytes) -> list[dict]:
    if filename.lower().endswith(".csv"):
        return parse_csv(raw)
    raise NotImplementedError(
        f"'{filename}' er ikke en CSV. ManaBox' .backup er krypteret og kan "
        f"ikke læses her — lav en CSV-eksport i ManaBox og læg den i "
        f"Drive-mappen.")
