"""Nightly ingest: Firestore(users,wants) + Drive -> parse -> match -> Firestore.

Kilder er nu 100% i Firestore - ingen friends.json / wants-txt mere:
  users/{uid}    {name, driveFolderId, ...}   (brugeren skriver selv i appen)
  wants/{uid}    {cards: [{name, scryfallId, ...}]}

Skriver:
  collections/{uid}            meta: navn, kortantal, chunks, updated
  collections/{uid}/chunks/{n} kortliste i bidder a 800
  matches/{uid}                {ownerUid: {cards:[...], totalEur}}
"""
import json
import os
import sys
from datetime import datetime, timezone

from google.cloud import firestore
from google.oauth2 import service_account

import fetch_drive
import import_lists
import match_wants
import parse_manabox
import prices

# Firestore-dokumenter må max fylde 1 MB. Kortene bærer nu også Scryfalls
# regeltekst, så vi kan ikke bruge et fast antal pr. chunk — vi pakker efter
# faktisk størrelse med god margin, og med et loft på antal for læsegranularitet.
CHUNK = 800
MAX_CHUNK_BYTES = 700_000

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/datastore",
]


def load_users(db) -> list[dict]:
    """Alle registrerede brugere fra Firestore."""
    users = []
    for doc in db.collection("users").stream():
        d = doc.to_dict() or {}
        users.append({
            "id": doc.id,
            "name": d.get("name") or doc.id,
            "driveFolderId": d.get("driveFolderId", ""),
        })
    return users


def load_wants(db, uid: str) -> list[str]:
    """Want-kortnavne for én bruger (wants gemmes som objekter i appen)."""
    doc = db.collection("wants").document(uid).get()
    if not doc.exists:
        return []
    cards = (doc.to_dict() or {}).get("cards", [])
    return [c["name"] if isinstance(c, dict) else c for c in cards]


def process_imports(db, uid: str, now: str) -> None:
    """Hent evt. pendingImports-URL'er (Archidekt/Moxfield) serverside og
    flet kortnavnene ind i brugerens wants. Rydder listen bagefter."""
    uref = db.collection("users").document(uid)
    urls = (uref.get().to_dict() or {}).get("pendingImports", [])
    if not urls:
        return
    wref = db.collection("wants").document(uid)
    cards = (wref.get().to_dict() or {}).get("cards", [])
    have = {(c["name"] if isinstance(c, dict) else c).lower() for c in cards}
    added = 0
    for url in urls:
        try:
            for n in import_lists.fetch_names(url):
                if n.lower() not in have:
                    cards.append({"name": n})
                    have.add(n.lower())
                    added += 1
        except Exception as e:
            print(f"[{uid}] import-fejl for {url}: {e}")
    wref.set({"cards": cards, "updated": now}, merge=True)
    uref.update({"pendingImports": firestore.DELETE_FIELD})
    print(f"[{uid}] importerede {added} nye wants fra {len(urls)} liste(r)")


def enrich_wants(db, uid: str, now: str) -> None:
    """Giv wants uden scryfallId et billede-ID (fx importerede kort).
    Normaliserer også gamle streng-wants til objekter."""
    wref = db.collection("wants").document(uid)
    cards = (wref.get().to_dict() or {}).get("cards", [])
    cards = [{"name": c} if isinstance(c, str) else c for c in cards]
    missing = [c for c in cards if not c.get("scryfallId")]
    if not missing:
        return
    try:
        lookup = import_lists.enrich([c["name"] for c in missing])
    except Exception as e:
        print(f"[{uid}] kunne ikke berige wants: {e}")
        return
    changed = 0
    for c in cards:
        if not c.get("scryfallId"):
            info = lookup.get(c["name"].lower())
            if info:
                c.update(info)
                changed += 1
    if changed:
        wref.set({"cards": cards, "updated": now}, merge=True)
    print(f"[{uid}] berigede {changed} wants med billede")


def enrich_card(card: dict, cmap: dict) -> dict:
    """Læg Scryfall-felterne (pris + gameplay) på et samlingskort, så
    frontenden kan filtrere på farve, mana value, type og regeltekst uden
    selv at slå op. Kort uden scryfallId sendes uændret videre."""
    d = cmap.get(card.get("scryfallId"))
    if not d:
        return {**card}
    eur = (d["eur_foil"] if card.get("foil") else d["eur"]) or d["eur"]
    out = {**card}
    out["eur"] = round(eur, 2) if eur else None
    if d.get("cmc") is not None:
        out["cmc"] = d["cmc"]
    if d.get("ci"):
        out["ci"] = d["ci"]
    if d.get("colors"):
        out["colors"] = d["colors"]
    if d.get("type"):
        out["type"] = d["type"]
    if d.get("text"):
        out["text"] = d["text"]
    if d.get("mana"):
        out["mana"] = d["mana"]
    return out


def chunk_cards(cards: list[dict]):
    """Del kortlisten op i bidder der sikkert holder sig under Firestores
    1 MB-grænse. Yield'er lister af kort."""
    buf: list[dict] = []
    size = 0
    for c in cards:
        n = len(json.dumps(c, ensure_ascii=False).encode("utf-8")) + 2
        if buf and (size + n > MAX_CHUNK_BYTES or len(buf) >= CHUNK):
            yield buf
            buf, size = [], 0
        buf.append(c)
        size += n
    if buf:
        yield buf


def main() -> int:
    sa_info = json.loads(os.environ["GCP_SA_KEY"])
    creds = service_account.Credentials.from_service_account_info(
        sa_info, scopes=SCOPES)
    db = firestore.Client(credentials=creds, project=sa_info["project_id"])

    users = load_users(db)
    if not users:
        print("Ingen brugere i Firestore endnu - log ind i appen først.")
        return 0

    now = datetime.now(timezone.utc).isoformat()
    collections, wants = {}, {}
    for u in users:
        uid = u["id"]
        process_imports(db, uid, now)   # flet evt. Archidekt/Moxfield-import ind
        enrich_wants(db, uid, now)      # giv navne-kun-wants et billede-ID
        wants[uid] = load_wants(db, uid)
        if not u["driveFolderId"]:
            print(f"[{uid}] mangler driveFolderId - springer samling over")
            continue
        try:
            got = fetch_drive.newest_file(creds, u["driveFolderId"])
            if not got:
                print(f"[{uid}] ingen filer i Drive-mappen")
                continue
            fname, raw = got
            cards = parse_manabox.parse(fname, raw)
            collections[uid] = cards
            print(f"[{uid}] {fname}: {len(cards)} kort")
        except NotImplementedError as e:
            print(f"[{uid}] {e}")
        except Exception as e:
            print(f"[{uid}] FEJL: {e}")

    matrix = match_wants.build_matrix(users, collections, wants)

    # Hent kun de Scryfall-kort vi faktisk har brug for. Bulk-filen er ~500 MB,
    # så filtreringen sparer både hukommelse og tid.
    need = {
        c["scryfallId"]
        for cards in collections.values()
        for c in cards
        if c.get("scryfallId")
    }
    try:
        cmap = prices.load_card_map(need)
        print(f"Scryfall: {len(cmap)}/{len(need)} kort beriget (pris + gameplay)")
    except Exception as e:
        print(f"Kunne ikke hente Scryfall-data: {e}")
        cmap = {}

    for u in users:
        uid = u["id"]
        if uid in collections:
            cards = [enrich_card(c, cmap) for c in collections[uid]]
            collections[uid] = cards
            ref = db.collection("collections").document(uid)
            for old in ref.collection("chunks").stream():
                old.reference.delete()
            n_chunks = 0
            for i, part in enumerate(chunk_cards(cards)):
                ref.collection("chunks").document(str(i)).set({"cards": part})
                n_chunks = i + 1
            # Distinkte binder-navne, så profilen kan tilbyde handel/låst-valg
            # uden at skulle læse hele samlingen.
            binders = sorted({c["binder"] for c in cards if c.get("binder")})
            ref.set({
                "name": u["name"],
                "cardCount": sum(c["qty"] for c in cards),
                "uniqueCount": len(cards),
                "chunks": n_chunks,
                "binders": binders,
                "updated": now,
            })

        match_doc = {}
        for oid, hits in matrix.get(uid, {}).items():
            enriched, total = [], 0.0
            for h in hits:
                h = enrich_card(h, cmap)
                h.pop("text", None)     # regeltekst fylder for meget i matches
                eur = h.get("eur")
                enriched.append(h)
                if eur:
                    total += eur * h.get("qty", 1)
            match_doc[oid] = {"cards": enriched, "totalEur": round(total, 2)}
        db.collection("matches").document(uid).set(match_doc)
        n_hits = sum(len(v["cards"]) for v in match_doc.values())
        print(f"[{uid}] matches: {n_hits} kort hos andre")

    return 0


if __name__ == "__main__":
    sys.exit(main())
