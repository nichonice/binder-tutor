"""Cross-matcher alles wants mod alles samlinger.

Wants læses fra Firestore i main.py — den gamle txt-baserede load_wants()
er fjernet sammen med resten af v1-filerne."""


def _norm(name: str) -> str:
    return name.lower().strip()


def _front(name: str) -> str:
    return _norm(name).split(" // ")[0]


def match(wants: list[str], collection: list[dict]) -> list[dict]:
    """Returnér kort fra collection der matcher wants (inkl. DFC-frontfaces)."""
    wset = {_norm(w) for w in wants}
    wfront = {_front(w) for w in wants}
    hits = []
    for card in collection:
        n = _norm(card["name"])
        if n in wset or (_front(card["name"]) in wfront and len(_front(card["name"])) > 3):
            hits.append(card)
    return hits


def build_matrix(friends: list[dict], collections: dict, wants: dict) -> dict:
    """matches[seeker][owner] = liste af owner's kort som seeker ønsker."""
    out = {}
    for seeker in friends:
        sid = seeker["id"]
        out[sid] = {}
        for owner in friends:
            oid = owner["id"]
            if oid == sid or oid not in collections:
                continue
            hits = match(wants.get(sid, []), collections[oid])
            if hits:
                out[sid][oid] = hits
    return out
