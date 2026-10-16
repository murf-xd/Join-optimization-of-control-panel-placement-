"""adapter.py -- Person A.  to_plan(raw_resplan_dict) -> contract_v2.Plan   (everything in PLAN METRES)

    python3 adapter.py 0 1 2 202      # summary of those plans + writes sample_plans.pkl for B and C

sample_plans.pkl is small: B and C can load it WITHOUT the 300 MB ResPlan.pkl:
    import pickle; plans = pickle.load(open("sample_plans.pkl", "rb")); plan = plans[0]
(they need contract_v2.py and shapely installed).

Nodes are PLACEHOLDERS until the organisers' input JSON is read: one point per eligible room, taken as the
"deepest" point of its hub zone. When the real fixed points arrive, replace them with attach_nodes().
"""
import pickle
import sys

from shapely.ops import polylabel, unary_union
from shapely.validation import make_valid

import geometry_v2 as G
from contract_v2 import (HUB_CLEARANCE_M, Gate, Node, Plan, Room, point_problems)


def to_output_xy(xy, plan=None):
    """Plan metres -> organisers' output frame ('origin lower-left, y up').
    TODO: waiting on the organisers. Until then this is the identity, and it is the ONLY place to change."""
    return (float(xy[0]), float(xy[1]))


def _hub_zone(room_poly, obstacles, free):
    """Part of the room that is INSIDE free space and at least HUB_CLEARANCE_M from walls and windows
    (plan metres). Some ResPlan rooms stick out past the 'inner' boundary (plan 17: only 57% of the living
    room is inside it), and nodes/hubs must be inside it, so we intersect with free space first."""
    try:
        z = room_poly if free.is_empty else room_poly.intersection(free)
        if not obstacles.is_empty:
            z = z.difference(obstacles.buffer(HUB_CLEARANCE_M))
        return unary_union(G.polys(z))
    except Exception:                                         # never crash: shrink the room instead
        return unary_union(G.polys(room_poly.buffer(-HUB_CLEARANCE_M)))


def _placeholder_xy(room, warnings):
    pieces = G.polys(room.hub_zone)
    if pieces:
        best = max(pieces, key=lambda p: p.area)
        pt = polylabel(best, tolerance=0.01)
        return (pt.x, pt.y)
    warnings.append(f"{room.id}: no point 0.5 m from walls exists; placeholder node is closer to a wall")
    p = room.polygon.representative_point()
    return (p.x, p.y)


def _union_obstacles(walls, windows, warnings):
    """walls U windows, merged in DRAWING units (before scaling: rounding after scaling made a few real plans
    fail with 'unable to assign free hole to a shell'). Falls back step by step; never raises."""
    attempts = (
        lambda: unary_union([walls, windows]),
        lambda: unary_union([make_valid(walls).buffer(0), make_valid(windows).buffer(0)]),
        lambda: unary_union([walls.buffer(1e-6), windows.buffer(1e-6)]),
    )
    for k, attempt in enumerate(attempts):
        try:
            out = attempt()
            if k:
                warnings.append(f"walls/windows merged with fallback {k}")
            return out
        except Exception:
            continue
    warnings.append("could not merge walls and windows: clearance uses walls only")
    return walls


def to_plan(raw):
    res = G.load_plan(raw)
    s = res["scale"]
    m = lambda g: G.to_metres(g, s)
    warnings = list(res["warnings"])

    walls, windows = m(res["walls"]), m(res["windows"])
    obstacles = m(_union_obstacles(res["walls"], res["windows"], warnings))
    free = m(res["free_space"])

    rooms = []
    for r in res["rooms"]:
        poly = m(r["poly"])
        room = Room(id=r["id"], type=r["type"], polygon=poly, area_m2=r["area_m2"],
                    eligible=r["eligible"], walkable=r["walkable"])
        if room.eligible:
            room.hub_zone = _hub_zone(poly, obstacles, free)
        else:
            room.hub_zone = unary_union([])
        rooms.append(room)

    gates = [Gate(id=g["id"], kind=g["kind"], segment=m(g["segment"]), room_a=g["room_a"],
                  room_b=g["room_b"], width_m=g["width_m"], usable=g["usable"],
                  clear_width_m=g.get("clear_width_m"), blocked=bool(g.get("blocked"))) for g in res["gates"]]

    nodes = []
    for k, room in enumerate([r for r in rooms if r.eligible], start=1):
        nodes.append(Node(id=f"N{k}", room_id=room.id, xy=_placeholder_xy(room, warnings)))

    plan = Plan(plan_id=res["plan_id"], scale=s, rooms=rooms, nodes=nodes, gates=gates,
                adjacency=res["adjacency"], free_space=free, inner=m(res["inner"]),
                walls=walls, windows=windows, obstacles=obstacles,
                diagnostics=dict(res["diagnostics"]), warnings=warnings)

    for n in plan.nodes:                                      # never crash: report
        bad = point_problems(plan, n.xy)
        if bad:
            plan.warnings.append(f"node {n.id} in {n.room_id}: " + "; ".join(bad))
    return plan


def attach_nodes(plan, points):
    """Replace placeholder nodes with the organisers' fixed points.
    points: {room_id: (x, y)} in plan metres, already mapped to OUR room ids. Returns a list of problems."""
    problems = []
    nodes = []
    for k, room in enumerate(plan.eligible_rooms, start=1):
        if room.id not in points:
            problems.append(f"no fixed node supplied for {room.id}")
            continue
        n = Node(id=f"N{k}", room_id=room.id, xy=tuple(points[room.id]), source="organisers")
        bad = point_problems(plan, n.xy)
        if bad:
            problems.append(f"{n.id} in {room.id}: " + "; ".join(bad))
        nodes.append(n)
    plan.nodes = nodes
    plan.__post_init__()
    return problems


def summarize(plan):
    d = plan.diagnostics
    empty = [r.id for r in plan.eligible_rooms if r.hub_zone.is_empty]
    print(f"plan {plan.plan_id}: scale {plan.scale:.2f} | eligible rooms {d['eligible_rooms']} "
          f"({d['eligible_area_m2']} m2) | hub lower bound {d['hub_lower_bound']} | nodes {len(plan.nodes)}")
    print(f"   gates: {len(plan.routing_gates)} usable, {len(plan.gates) - len(plan.routing_gates)} to outside"
          f" | free space pieces {d['free_space_pieces']} | rooms with no hub zone: {empty or 'none'}")
    print(f"   rooms with no gate: {d['rooms_with_no_gate'] or 'none'} | warnings: {plan.warnings or 'none'}")


if __name__ == "__main__":
    idxs = [int(a) for a in sys.argv[1:]] or [0]
    with open("ResPlan.pkl", "rb") as f:
        data = pickle.load(f)
    out = {}
    for i in idxs:
        out[i] = to_plan(data[i])
        summarize(out[i])
    with open("sample_plans.pkl", "wb") as f:
        pickle.dump(out, f)
    print("saved sample_plans.pkl with plans", idxs)
