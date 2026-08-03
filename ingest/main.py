"""Nightly ingest: Firestore(users,wants) + Drive -> parse -> match -> Firestore.

Kilder er nu 100% i Firestore - ingen friends.json / wants-txt mere:
  users/{uid}    {name, driveFolderId, ...}   (brugeren skriver selv i appen)
  wants/{uid}    {cards: [{name, scryfallId, ...}]}

Skriver:
  collections/{uid}             meta: navn, kortantal, chunks, bindere, updated
  collections/{uid}/chunks/{n}  fuld kortliste, opdelt efter byte-størrelse
  collections/{uid}/index/names kompakt navneindeks til matching i browseren

Matching sker i frontenden ud fra navneindekset, ikke her. Det gør at nye wants
slår igennem med det samme i stedet for at vente på næste nattekørsel.
"""
import json
import os
import sys
from datetime import datetime, timezone

from google.cloud import firestore
from google.oauth2 import service_account

import fetch_drive
import import_lists
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
        modes = dict(d.get("binderMode") or {})
        for b in (d.get("lockedBinders") or []):      # v1.1-arv
            modes.setdefault(b, "deck")
        users.append({
            "id": doc.id,
            "name": d.get("name") or doc.id,
            "driveFolderId": d.get("driveFolderId", ""),
            "binderMode": modes,
        })
    return users


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


def auto_mode(binder_type: str) -> str:
    """Udled binder-status af ManaBox' 'Binder Type'.

    ManaBox eksporterer bade den fysiske samling OG lister/wishlists i samme CSV.
    Et kort i en liste er en *reference* til et kort — ikke et ekstra fysisk
    eksemplar — og ma derfor ikke taelle med i samlingen eller i matches.
      trade = fysisk, til handel
      deck  = fysisk, men bundet i et deck
      list  = ikke fysisk
    Ejeren kan overstyre pr. binder i appen (users/{uid}.binderMode)."""
    t = (binder_type or "").lower()
    if "list" in t or "wish" in t:
        return "list"
    if "deck" in t:
        return "deck"
    return "trade"


def binder_summary(cards: list[dict]) -> list[dict]:
    """Distinkte bindere med type og antal, så profilen kan tilbyde
    handel/deck/liste-valg uden at læse hele samlingen."""
    agg: dict[str, dict] = {}
    for c in cards:
        b = c.get("binder") or ""
        if not b:
            continue
        e = agg.setdefault(b, {"name": b, "type": c.get("binderType", ""),
                               "mode": auto_mode(c.get("binderType", "")),
                               "unique": 0, "qty": 0})
        e["unique"] += 1
        e["qty"] += c.get("qty", 1)
    return sorted(agg.values(), key=lambda e: e["name"])


MODE_CHAR = {"trade": "t", "deck": "d", "list": "l"}
MODE_RANK = {"trade": 0, "deck": 1, "list": 2}


def name_index(cards: list[dict], modes: dict) -> list[list]:
    """Kompakt navneindeks: [navn, mode, bedste pris, antal] pr. unikt kortnavn.

    Frontenden bruger det til at matche wants mod alles samlinger i browseren.
    Et fuldt chunk-sæt fylder flere MB pr. person (regeltekst m.m.) og ville være
    urimeligt at hente for hele gruppen på en telefon; det her er ~100 kB.
    Fulde kortdata hentes først når en konkret handel åbnes.

    Har man flere eksemplarer, vinder den mest handelsvenlige tilstand — ejer man
    både et løst og et deck-bundet eksemplar, er kortet reelt til handel."""
    best: dict[str, list] = {}
    for c in cards:
        binder = c.get("binder") or ""
        mode = modes.get(binder) or auto_mode(c.get("binderType", ""))
        n = (c.get("name") or "").lower().strip()
        if not n:
            continue
        eur, qty = c.get("eur"), c.get("qty", 1)
        cur = best.get(n)
        if cur is None:
            best[n] = [mode, eur, qty]
        elif MODE_RANK[mode] < MODE_RANK[cur[0]]:
            best[n] = [mode, eur, qty + (cur[2] if MODE_RANK[cur[0]] != 2 else 0)]
        elif MODE_RANK[mode] == MODE_RANK[cur[0]]:
            cur[2] += qty
            if eur and (cur[1] is None or eur > cur[1]):
                cur[1] = eur
    return [[n, MODE_CHAR[v[0]], v[1], v[2]] for n, v in sorted(best.items())]


def pack_index(idx: list[list], max_bytes: int = 900_000) -> list[str]:
    """Pak navneindekset til tab-separerede linjer, samlet i tekstblokke.

    Firestore tillader IKKE arrays inde i arrays, så indekset kan ikke gemmes
    som [[navn, mode, ...], ...]. En liste af strenge er tilladt, og tekst er
    samtidig mere kompakt end JSON-objekter, hvor feltnavnene gentages pr. kort.
    Blokkene holdes under dokumentgrænsen på 1 MB.

    Linjeformat: navn \t mode \t pris \t antal   (pris tom hvis ukendt)
    Kortnavne kan ikke indeholde tab eller linjeskift, så formatet er entydigt."""
    rows = [
        "\t".join([n, ch, "" if eur is None else f"{eur:.2f}", str(qty)])
        for n, ch, eur, qty in idx
    ]
    out: list[str] = []
    buf: list[str] = []
    size = 0
    for r in rows:
        b = len(r.encode("utf-8")) + 1
        if buf and size + b > max_bytes:
            out.append("\n".join(buf))
            buf, size = [], 0
        buf.append(r)
        size += b
    if buf:
        out.append("\n".join(buf))
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
    collections = {}
    for u in users:
        uid = u["id"]
        process_imports(db, uid, now)   # flet evt. Archidekt/Moxfield-import ind
        enrich_wants(db, uid, now)      # giv navne-kun-wants et billede-ID
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
            # Tællerne skal vise den FYSISKE samling. Kort der kun ligger i en
            # ManaBox-liste er referencer til kort man ejer i forvejen — tælles
            # de med, ser man dubletter (fx "2 Roaming Throne" når man har én).
            phys = [c for c in cards if auto_mode(c.get("binderType", "")) != "list"]
            n_list = len(cards) - len(phys)
            ref.set({
                "name": u["name"],
                "cardCount": sum(c["qty"] for c in phys),
                "uniqueCount": len(phys),
                "listCount": n_list,
                "chunks": n_chunks,
                "binders": binder_summary(cards),
                "updated": now,
            })
            if n_list:
                print(f"[{uid}] {n_list} kort ligger i lister (ikke talt som fysiske)")

            # Kompakt navneindeks — frontenden matcher wants mod det i browseren,
            # så nye wants slår igennem med det samme i stedet for at vente et døgn.
            idx = name_index(cards, u.get("binderMode") or {})
            rows = pack_index(idx)
            ref.collection("index").document("names").set({
                "rows": rows,
                "count": len(idx),
                "updated": now,
            })
            kb = sum(len(r.encode("utf-8")) for r in rows) / 1024
            print(f"[{uid}] navneindeks: {len(idx)} unikke navne "
                  f"({kb:.0f} kB i {len(rows)} blok(ke))")

    return 0


if __name__ == "__main__":
    sys.exit(main())
