"""Parsere for ManaBox-data. CSV virker nu; Drive-backup-formatet
tilføjes i parse_backup() når vi har en prøvefil."""
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


def parse_backup(raw: bytes) -> list[dict]:
    """ManaBox Google Drive-backup. Format ukendt endnu -
    upload en backup-fil, så bygger vi denne parser.
    Sandsynligvis SQLite eller JSON: sniff magic bytes."""
    if raw[:16] == b"SQLite format 3\x00":
        raise NotImplementedError(
            "Backup er SQLite - send en prøvefil, så mapper vi tabellerne.")
    if raw[:2] in (b"PK", b"\x1f\x8b"):
        raise NotImplementedError(
            "Backup er zip/gzip-pakket - send en prøvefil.")
    raise NotImplementedError("Ukendt backup-format - send en prøvefil.")


def parse(filename: str, raw: bytes) -> list[dict]:
    if filename.lower().endswith(".csv"):
        return parse_csv(raw)
    return parse_backup(raw)
