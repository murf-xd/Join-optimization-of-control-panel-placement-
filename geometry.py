"""geometry.py -- Person A.

load_plan(raw_plan) -> dict with rooms, gates, adjacency, free_space, diagnostics.
All geometry stays in DRAWING UNITS here. Use to_metres() once, at the output edge.

Facts this relies on (from the problem statement and plan 0's picture):
  * scale = sqrt(inner.area / area)  drawing units per metre (never use net_area)
  * every polygon is its own room; rooms are inset from the wall bands, so two
    neighbouring rooms are NOT touching: a door polygon sits inside the wall band
  * open passages (e.g. kitchen/living) have no door polygon and no wall between
"""
import math
import sys
from itertools import combinations

from shapely import affinity
from shapely.geometry import LineString, Point
from shapely.ops import unary_union
from shapely.validation import make_valid

ELIGIBLE = ("living", "bedroom", "kitchen", "storage")
PASS_THROUGH = ("bathroom", "stair")      # walkable, no node
EXTERNAL = ("balcony",)                   # never walkable
FALLBACK_SCALE = 18.1                     # median over ResPlan; only used with a warning
MIN_OPEN_M = 0.7                          # narrowest wall-free gap called an open passage (assumption)
MIN_ELIGIBLE_M2 = 2.0


# ---------------------------------------------------------------- helpers
def polys(g):
    """All non-empty Polygons inside any geometry, repaired, in a deterministic order."""
    if g is None or g.is_empty:
        return []
    out, stack = [], [make_valid(g)]
    while stack:
        x = stack.pop()
        if x.is_empty:
            continue
        if x.geom_type == "Polygon":
            out.append(x)
        elif hasattr(x, "geoms"):
            stack.extend(x.geoms)
    return sorted(out, key=lambda p: (round(p.bounds[0], 6), round(p.bounds[1], 6)))


def _mid(a, b):
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


def long_axis(poly):
    """(centreline along the LONG side, long length, short length) of the min rotated rectangle."""
    c = list(poly.minimum_rotated_rectangle.exterior.coords)[:4]
    e1, e2 = math.dist(c[0], c[1]), math.dist(c[1], c[2])
    if e1 >= e2:
        a, b, length, thick = _mid(c[1], c[2]), _mid(c[3], c[0]), e1, e2
    else:
        a, b, length, thick = _mid(c[0], c[1]), _mid(c[2], c[3]), e2, e1
    return LineString([a, b]), length, thick


def _room_at(pt, rooms, tol):
    for r in rooms:
        if r["poly"].contains(pt):
            return r
    best = min(rooms, key=lambda r: r["poly"].distance(pt), default=None)
    return best if best is not None and best["poly"].distance(pt) <= tol else None


# ---------------------------------------------------------------- loader
def load_plan(raw):
    warnings = []
    plan = dict(raw)
    if "balacony" in plan and "balcony" not in plan:          # dataset typo
        plan["balcony"] = plan.pop("balacony")

    inner = unary_union(polys(plan.get("inner")))
    walls = unary_union(polys(plan.get("wall")))
    windows = unary_union(polys(plan.get("window")))
    door_polys = polys(plan.get("door"))

    area = plan.get("area")
    if inner.is_empty or not area or area <= 0:
        scale = FALLBACK_SCALE
        warnings.append("missing inner/area: used fallback scale")
    else:
        scale = math.sqrt(inner.area / area)
    wd = float(plan.get("wall_depth") or 4.0)

    rooms = []
    for t in ELIGIBLE + PASS_THROUGH + EXTERNAL:
        for i, p in enumerate(polys(plan.get(t))):
            m2 = p.area / scale ** 2
            if t in ELIGIBLE and m2 < MIN_ELIGIBLE_M2:
                warnings.append(f"{t}_{i} is only {m2:.2f} m2")
            rooms.append(dict(id=f"{t}_{i}", type=t, poly=p, area_m2=m2,
                              eligible=t in ELIGIBLE, walkable=t not in EXTERNAL))

    gates = _door_gates(door_polys, rooms, wd, scale)
    gates += _open_passages(rooms, walls, door_polys, gates, wd, scale)
    adjacency = _adjacency(rooms, gates)
    free = _free_space(rooms, gates, windows, inner, wd)
    diag = _diagnostics(rooms, gates, adjacency, free, warnings, plan, scale)

    return dict(plan_id=plan.get("id"), scale=scale, wall_depth=wd, rooms=rooms, gates=gates,
                adjacency=adjacency, free_space=free, inner=inner, walls=walls,
                windows=windows, doors=door_polys, front_door=polys(plan.get("front_door")),
                diagnostics=diag, warnings=warnings)


# ---------------------------------------------------------------- gates
def _door_gates(door_polys, rooms, wd, scale):
    gates = []
    for d in door_polys:
        line, length, thick = long_axis(d)
        (x0, y0), (x1, y1) = line.coords
        dx, dy = x1 - x0, y1 - y0
        n = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / n, dx / n                              # crossing direction
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        reach = thick / 2 + 0.5 * wd
        sides = []
        for s in (1, -1):
            r = _room_at(Point(cx + s * nx * reach, cy + s * ny * reach), rooms, wd)
            sides.append(r)
        a, b = sides
        usable = bool(a and b and a["id"] != b["id"] and a["walkable"] and b["walkable"])
        gates.append(dict(id=f"G{len(gates)}", kind="door", segment=line, poly=d,
                          width_m=length / scale,
                          room_a=a["id"] if a else "EXTERIOR",
                          room_b=b["id"] if b else "EXTERIOR", usable=usable))
    return gates


def _open_passages(rooms, walls, door_polys, door_gates, wd, scale):
    walk = [r for r in rooms if r["walkable"]]
    g = wd * 0.55
    min_open = MIN_OPEN_M * scale
    doors_u = unary_union([d.buffer(0.05 * wd) for d in door_polys]) if door_polys else None
    out = []
    for a, b in combinations(walk, 2):
        if a["poly"].distance(b["poly"]) > 2 * g:
            continue
        zone = a["poly"].buffer(g).intersection(b["poly"].buffer(g)).difference(walls)
        if doors_u is not None:
            zone = zone.difference(doors_u)
        for piece in polys(zone):
            line, length, thick = long_axis(piece)
            if length >= min_open:
                out.append(dict(id=f"P{len(out)}", kind="open_passage", segment=line, poly=piece,
                                width_m=length / scale, room_a=a["id"], room_b=b["id"], usable=True))
    return out


def _adjacency(rooms, gates):
    adj = {r["id"]: [] for r in rooms if r["walkable"]}
    for g in gates:
        if g["usable"]:
            adj[g["room_a"]].append(g["room_b"])
            adj[g["room_b"]].append(g["room_a"])
    return {k: sorted(set(v)) for k, v in adj.items()}


# ---------------------------------------------------------------- free space
def _free_space(rooms, gates, windows, inner, wd):
    eps = 0.15 * wd                                           # bridges tiny gaps between door and room
    parts = [r["poly"] for r in rooms if r["walkable"]]
    parts += [g["poly"].buffer(eps) for g in gates if g["usable"]]
    free = unary_union(parts)
    if not windows.is_empty:
        free = free.difference(windows)
    if not inner.is_empty:
        free = free.intersection(inner)
    return free


# ---------------------------------------------------------------- diagnostics ("Plan Doctor")
def _diagnostics(rooms, gates, adjacency, free, warnings, plan, scale):
    elig = [r for r in rooms if r["eligible"]]
    area = sum(r["area_m2"] for r in elig)
    comps = list(free.geoms) if hasattr(free, "geoms") else ([free] if not free.is_empty else [])
    comp_of = {}
    for r in rooms:
        if r["walkable"]:
            p = r["poly"].representative_point()
            comp_of[r["id"]] = next((i for i, c in enumerate(comps) if c.contains(p)), None)
    main = max(set(comp_of.values()) - {None},
               key=lambda i: sum(1 for v in comp_of.values() if v == i), default=None)
    unreachable = sorted(k for k, v in comp_of.items() if v != main)
    return dict(
        scale=round(scale, 3),
        eligible_rooms=len(elig),
        eligible_area_m2=round(area, 2),
        hub_lower_bound=max(math.ceil(area / 100.0), math.ceil(len(elig) / 5)) if elig else 0,
        oversized_rooms=[r["id"] for r in elig if r["area_m2"] > 100],
        door_gates=sum(1 for g in gates if g["kind"] == "door" and g["usable"]),
        open_passages=sum(1 for g in gates if g["kind"] == "open_passage"),
        exterior_doors=sum(1 for g in gates if g["kind"] == "door" and not g["usable"]),
        rooms_with_no_gate=sorted(k for k, v in adjacency.items() if not v),
        free_space_pieces=len(comps),
        rooms_outside_main_free_space=unreachable,
        single_door_rooms=sorted(k for k, v in adjacency.items() if len(v) == 1),
    )


def to_metres(geom, scale):
    """Drawing units -> metres. TODO: origin / y-flip rule pending organisers' answer."""
    return affinity.scale(geom, 1 / scale, 1 / scale, origin=(0, 0))


# ---------------------------------------------------------------- check plot
def plot_check(res, path="gates_check.png"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    col = dict(living="#d9d9d9", bedroom="#66c2a5", kitchen="#8da0cb", storage="#FF8C69",
               bathroom="#fc8d62", stair="#9e9ac8", balcony="#eeeeee")
    fig, ax = plt.subplots(figsize=(10, 10))
    for r in res["rooms"]:
        x, y = r["poly"].exterior.xy
        ax.fill(x, y, color=col.get(r["type"], "#cccccc"), alpha=0.7, ec="black", lw=0.4)
        c = r["poly"].representative_point()
        ax.text(c.x, c.y, r["id"], ha="center", fontsize=7)
    for p in polys(res["walls"]):
        x, y = p.exterior.xy
        ax.fill(x, y, color="#444444", alpha=0.8, lw=0)
    for p in polys(res["windows"]):
        x, y = p.exterior.xy
        ax.fill(x, y, color="#2060ff", alpha=0.8, lw=0)
    for g in res["gates"]:
        x, y = g["segment"].xy
        if g["kind"] == "open_passage":
            ax.plot(x, y, color="lime", lw=4)
        elif g["usable"]:
            ax.plot(x, y, color="red", lw=3)
        else:
            ax.plot(x, y, color="black", lw=2, ls="--")
    ax.set_aspect("equal")
    ax.set_title("red = door gate, green = open passage, dashed = door to outside (not routable)")
    plt.savefig(path, dpi=140)
    plt.close(fig)


if __name__ == "__main__":
    import pickle
    idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    with open("ResPlan.pkl", "rb") as f:
        data = pickle.load(f)
    res = load_plan(data[idx])
    for k, v in res["diagnostics"].items():
        print(k, ":", v)
    print("warnings:", res["warnings"])
    print("adjacency:")
    for k, v in res["adjacency"].items():
        print("  ", k, "->", v)
    print("gates:")
    for g in res["gates"]:
        print("  ", g["id"], g["kind"], g["room_a"], "<->", g["room_b"], "usable" if g["usable"] else "NOT usable",
              "width %.2f m" % g["width_m"])
    plot_check(res)
    print("saved gates_check.png")
