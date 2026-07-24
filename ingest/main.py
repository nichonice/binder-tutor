"""Nightly ingest: Drive -> parse -> match -> Firestore.

Firestore-model:
  friends/{id}                 meta: navn, kortantal, sidst opdateret
  friends/{id}/chunks/{n}      kortliste i bidder a 800 (holder os under 1 MB/doc)
  wants/{id}                   {cards: [...]}
  matches/{seekerId}           {ownerId: [kort...], ...}
"""
import json
import os
import sys
from datetime import datetime, timezone

from google.cloud import firestore
from google.oauth2 import service_account

import fetch_drive
import match_wants
import parse_manabox
import prices

CHUNK = 800
SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/datastore",
]


def main() -> int:
    sa_info = json.loads(os.environ["GCP_SA_KEY"])
    creds = service_account.Credentials.from_service_account_info(
        sa_info, scopes=SCOPES)
    db = firestore.Client(credentials=creds, project=sa_info["project_id"])

    cfg = json.load(open("friends.json", encoding="utf-8"))
    friends = cfg["friends"]

    collections, wants = {}, {}
    for f in friends:
        fid = f["id"]
        try:
            got = fetch_drive.newest_file(creds, f["driveFolderId"])
            if not got:
                print(f"[{fid}] ingen filer i Drive-mappen - springer over")
                continue
            fname, raw = got
            cards = parse_manabox.parse(fname, raw)
            collections[fid] = cards
            print(f"[{fid}] {fname}: {len(cards)} kort")
        except NotImplementedError as e:
            print(f"[{fid}] {e}")
        except Exception as e:  # én vens fejl må ikke vælte natkørslen
            print(f"[{fid}] FEJL: {e}")

        if os.path.exists(f["wantsFile"]):
            wants[fid] = match_wants.load_wants(f["wantsFile"])

    matrix = match_wants.build_matrix(friends, collections, wants)

    try:
        pmap = prices.load_price_map()
        print(f"Priser: {len(pmap)} kort fra Scryfall")
    except Exception as e:
        print(f"Kunne ikke hente priser: {e}")
        pmap = {}

    now = datetime.now(timezone.utc).isoformat()
    for f in friends:
        fid = f["id"]
        if fid in collections:
            cards = collections[fid]
            ref = db.collection("friends").document(fid)
            # slet gamle chunks før skrivning
            for old in ref.collection("chunks").stream():
                old.reference.delete()
            for i in range(0, len(cards), CHUNK):
                ref.collection("chunks").document(str(i // CHUNK)).set(
                    {"cards": cards[i:i + CHUNK]})
            ref.set({
                "name": f["name"],
                "cardCount": sum(c["qty"] for c in cards),
                "uniqueCount": len(cards),
                "chunks": (len(cards) + CHUNK - 1) // CHUNK,
                "updated": now,
            })
        if fid in wants:
            db.collection("wants").document(fid).set(
                {"cards": wants[fid], "updated": now})
        match_doc = {}
        for oid, hits in matrix.get(fid, {}).items():
            enriched = []
            total = 0.0
            for h in hits:
                eur = prices.price_of(h, pmap)
                enriched.append({**h, "eur": round(eur, 2) if eur else None})
                if eur:
                    total += eur * h.get("qty", 1)
            match_doc[oid] = {"cards": enriched, "totalEur": round(total, 2)}
        db.collection("matches").document(fid).set(match_doc)
        n_hits = sum(len(v["cards"]) for v in match_doc.values())
        print(f"[{fid}] matches: {n_hits} kort hos andre")

    return 0


if __name__ == "__main__":
    sys.exit(main())
