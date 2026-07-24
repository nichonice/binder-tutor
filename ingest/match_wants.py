"""Cross-matcher alles wants mod alles samlinger.
Wants-format: én kortnavn pr. linje, '#' er kommentar."""


def load_wants(path: str) -> list[str]:
    wants = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split("#")[0].strip()
            if line:
                wants.append(line)
    return wants


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
