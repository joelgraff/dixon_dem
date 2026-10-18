"""Routes: OSM ways chained into the streets a designer would station (roadway_control_plan.md §1).

OSM splits a street into many ways (at name changes, tag changes, bridges, or for no reason).
A route follows a street through those splits: through a node where it simply continues, and
through a junction where the same street carries on across it. Names are compared without their
leading direction word, since "West 1st Street" becomes "East 1st Street" where it crosses
Galena, and North Galena Avenue becomes South Galena Avenue on the bridge.

Stationing runs west to east, or south to north for a mostly north-south route, from 0 at the
start, so a route's stations do not depend on how OSM happened to draw its ways.
"""
import math
from collections import defaultdict

DIRECTION_WORDS = {"north", "south", "east", "west", "n", "s", "e", "w", "n.", "s.", "e.", "w."}
CONTINUE_DEG = 60.0         # the most a named street may bend at a junction and still continue
UNNAMED_CONTINUE_DEG = 30.0  # the same for unnamed ways at a plain (two-way) node
LEG_M = 15.0                # how far along a way its direction at a node is measured


def street_name(name):
    """The name without its leading direction word, lower case: 'West 1st Street' -> '1st street'."""
    if not name:
        return None
    words = name.split()
    if len(words) > 1 and words[0].lower() in DIRECTION_WORDS:
        words = words[1:]
    return " ".join(words).lower()


def split_at_nodes(ways, node_ids):
    """Each way cut at every interior vertex whose node is in node_ids: [(way, i0, i1), ...]."""
    out = []
    for w in ways:
        vs = w["vertices"]
        cut = [0] + [i for i in range(1, len(vs) - 1) if vs[i].get("node_id") in node_ids] + [len(vs) - 1]
        for a, b in zip(cut, cut[1:]):
            if b > a:
                out.append((w, a, b))
    return out


def _leg_direction(points):
    """Unit direction of a polyline leaving its first point, over its first LEG_M."""
    x0, z0 = points[0]
    acc = 0.0
    px, pz = x0, z0
    for x, z in points[1:]:
        acc += math.hypot(x - px, z - pz)
        px, pz = x, z
        if acc >= LEG_M:
            break
    d = math.hypot(px - x0, pz - z0)
    return ((px - x0) / d, (pz - z0) / d) if d > 1e-9 else (0.0, 0.0)


def build_routes(ways, rank):
    """Chains ways into routes.

    `ways` are roads.json ways; `rank(highway)` orders classes (higher continues first) and
    returns None for a way that is not part of any route. Returns a list of routes, each
    {"pieces": [(way, i0, i1, reversed), ...], "closed": bool}, pieces in travel order."""
    ways = [w for w in ways if rank(w["tags"].get("highway")) is not None]
    use = defaultdict(int)
    for w in ways:
        for v in w["vertices"]:
            if v.get("node_id") is not None:
                use[v["node_id"]] += 1
    shared = {n for n, c in use.items() if c > 1}
    pieces = split_at_nodes(ways, shared)

    # each piece end at a node: (piece index, which end, direction leaving the node)
    ends = defaultdict(list)
    for k, (w, a, b) in enumerate(pieces):
        vs = w["vertices"][a:b + 1]
        pts = [(v["x"], v["z"]) for v in vs]
        for end, node, leg in ((0, vs[0].get("node_id"), pts), (1, vs[-1].get("node_id"), pts[::-1])):
            if node is not None:
                ends[node].append((k, end, _leg_direction(leg)))

    # pair piece ends at each node: the best continuation first
    partner = {}
    for node, items in ends.items():
        cands = []
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                (ka, ea, da), (kb, eb, db) = items[i], items[j]
                if ka == kb:
                    continue
                wa, wb = pieces[ka][0], pieces[kb][0]
                # deflection: leaving along a then along b is straight when they point opposite ways
                cosang = max(-1.0, min(1.0, -(da[0] * db[0] + da[1] * db[1])))
                bend = math.degrees(math.acos(cosang))
                na, nb = street_name(wa["tags"].get("name")), street_name(wb["tags"].get("name"))
                ha, hb = wa["tags"].get("highway"), wb["tags"].get("highway")
                if wa["id"] == wb["id"]:
                    ok = bend <= CONTINUE_DEG or len(items) == 2   # one OSM way, cut only here
                elif na and na == nb:
                    ok = bend <= CONTINUE_DEG
                elif na is None and nb is None:
                    ok = ha == hb and bend <= UNNAMED_CONTINUE_DEG
                else:
                    ok = False
                if ok:
                    score = (-(rank(ha) + rank(hb)), bend)
                    cands.append((score, (ka, ea), (kb, eb)))
        for _, a, b in sorted(cands):
            if a not in partner and b not in partner:
                partner[a] = b
                partner[b] = a

    # walk the chains
    seen = set()
    routes = []
    for k in range(len(pieces)):
        if k in seen:
            continue
        # walk back from end 0 to the chain's start
        cur, cur_end = k, 0
        closed = False
        visited = {k}
        while (cur, cur_end) in partner:
            nk, ne = partner[(cur, cur_end)]
            if nk in visited:
                closed = nk == k
                break
            visited.add(nk)
            cur, cur_end = nk, 1 - ne
        # cur's end `cur_end` is the chain's start
        chain = []
        piece, entry = cur, cur_end
        while True:
            seen.add(piece)
            w, a, b = pieces[piece]
            chain.append((w, a, b, entry == 1))
            exit_end = 1 - entry
            nxt = partner.get((piece, exit_end))
            if nxt is None or nxt[0] in seen:
                break
            piece, entry = nxt
        routes.append({"pieces": chain, "closed": closed})
    return routes


def route_polyline(route):
    """The route's vertices in travel order: [(x, z, node_id, way_id), ...]."""
    out = []
    for w, a, b, rev in route["pieces"]:
        vs = w["vertices"][a:b + 1]
        if rev:
            vs = vs[::-1]
        for v in (vs if not out else vs[1:]):
            out.append((v["x"], v["z"], v.get("node_id"), w["id"]))
    return out


def orient(points):
    """True when the route should be reversed so it is stationed west->east or south->north."""
    (x0, z0), (x1, z1) = points[0][:2], points[-1][:2]
    dx, dz = x1 - x0, z1 - z0
    if abs(dx) >= abs(dz):
        return dx < 0
    return dz > 0           # z is south: stationing northward means z decreasing


def reverse_route(route):
    return {"pieces": [(w, a, b, not rev) for w, a, b, rev in reversed(route["pieces"])],
            "closed": route["closed"]}
