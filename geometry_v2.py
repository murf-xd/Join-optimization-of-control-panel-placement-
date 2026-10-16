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
from shapely.geometry.polygon import orient
from shapely.ops import split as shp_split
from shapely.ops import linemerge, unary_union
from shapely.validation import make_valid

ELIGIBLE = ("living", "bedroom", "kitchen", "storage")
PASS_THROUGH = ("bathroom", "stair")      # walkable, no node
EXTERNAL = ("balcony",)                   # never walkable
FALLBACK_SCALE = 18.1                     # median over ResPlan; only used with a warning
MIN_OPEN_M = 0.7                          # narrowest wall-free gap called an open passage (assumption)
RESCUE_MIN_OPEN_M = 0.4                   # narrower gaps count ONLY if they reconnect an otherwise cut-off room
MIN_ELIGIBLE_M2 = 2.0
MIN_CLEAR_M = 0.2                         # a gate whose free-space crossing is narrower than this is unusable (a window covers it)
RECT_FILL = 0.85                          # door polygon filling < 85% of its bounding rectangle gets split
MIN_DOOR_RUN_M = 0.3                      # a door polygon must support a room pair over this length to make its own gate
MAX_HUB_AREA_M2 = 100.0                    # per-hub capacity (problem statement)
MAX_NODES_PER_HUB = 5                     # per-hub capacity (PPTX; old text said 20)


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


def split_door_polygon(d, wd, depth=0):
    """Split a door polygon that is not rectangular (e.g. two adjacent doors merged into an L) into
    rectangular pieces by cutting through its inner (reflex) corners. A plain rectangle is returned as is."""
    mrr_area = d.minimum_rotated_rectangle.area
    if depth >= 4 or mrr_area <= 0 or d.area / mrr_area >= RECT_FILL:
        return [d]
    ring = list(orient(d, 1.0).exterior.coords)[:-1]
    big = math.hypot(d.bounds[2] - d.bounds[0], d.bounds[3] - d.bounds[1]) * 2
    n = len(ring)
    for i in range(n):
        p, c, q = ring[i - 1], ring[i], ring[(i + 1) % n]
        cross = (c[0] - p[0]) * (q[1] - c[1]) - (c[1] - p[1]) * (q[0] - c[0])
        if cross < -1e-9:                                     # reflex vertex (CCW ring turns right)
            ux, uy = c[0] - p[0], c[1] - p[1]
            L = math.hypot(ux, uy)
            if L < 1e-9:
                continue
            ux, uy = ux / L * big, uy / L * big
            try:
                parts = [g for g in shp_split(d, LineString([(c[0] - ux, c[1] - uy), (c[0] + ux, c[1] + uy)])).geoms
                         if g.geom_type == "Polygon" and g.area >= 0.25 * wd * wd]
            except Exception:
                continue
            if len(parts) >= 2:
                out = []
                for part in parts:
                    out.extend(split_door_polygon(part, wd, depth + 1))
                return out
    return [d]


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
    try:
        passages = _open_passages(rooms, walls, door_polys, gates, wd, scale, windows=windows)
        passages += _rescue_passages(rooms, walls, door_polys, gates, passages, wd, scale, windows=windows)
        for k, p in enumerate(passages):
            p["id"] = f"P{k}"
        gates += passages
    except Exception as e:                                    # never crash: report and continue
        warnings.append(f"open-passage detection failed: {e!r}")
    free = _free_space(rooms, gates, windows, inner, wd)
    if _apply_clear_width(gates, free, wd, scale):            # a window covered a "usable" gate: block it
        free = _free_space(rooms, gates, windows, inner, wd)
    adjacency = _adjacency(rooms, gates)
    diag = _diagnostics(rooms, gates, adjacency, free, warnings, plan, scale)

    return dict(plan_id=plan.get("id"), scale=scale, wall_depth=wd, rooms=rooms, gates=gates,
                adjacency=adjacency, free_space=free, inner=inner, walls=walls,
                windows=windows, doors=door_polys, front_door=polys(plan.get("front_door")),
                diagnostics=diag, warnings=warnings)


# ---------------------------------------------------------------- gates
def _door_gates(door_polys, rooms, wd, scale):
    """One gate per distinct pair of rooms a door polygon joins.

    The old version probed only the centre of the door, so a door sitting where three rooms meet, or a
    long door polygon spanning several rooms, joined just one pair. Now we probe along the whole long axis
    (every ~0.1 m) and make a gate for each pair that is supported by a stretch of >= MIN_DOOR_RUN_M
    (the pair found at the centre is always kept)."""
    gates = []
    step = 0.1 * scale
    pieces = []
    for dp in door_polys:
        pieces.extend(split_door_polygon(dp, wd))
    for d in pieces:
        line, length, thick = long_axis(d)
        (x0, y0), (x1, y1) = line.coords
        dx, dy = x1 - x0, y1 - y0
        n = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / n, dx / n                              # crossing direction
        reach = thick / 2 + 0.5 * wd
        k = max(int(length / step), 1)
        runs = {}                                             # pair key -> [sample indices], sides
        centre_key = None
        for i in range(k):
            t = (i + 0.5) / k
            cx, cy = x0 + dx * t, y0 + dy * t
            a = _room_at(Point(cx + nx * reach, cy + ny * reach), rooms, wd)
            b = _room_at(Point(cx - nx * reach, cy - ny * reach), rooms, wd)
            if a is None and b is None:
                continue
            ida = a["id"] if a else "EXTERIOR"
            idb = b["id"] if b else "EXTERIOR"
            key = frozenset((ida, idb)) if ida != idb else frozenset((ida,))
            runs.setdefault(key, dict(idx=[], a=a, b=b))["idx"].append(i)
            if i == k // 2:
                centre_key = key
        if not runs:
            runs[frozenset(("EXTERIOR",))] = dict(idx=[k // 2], a=None, b=None)
            centre_key = next(iter(runs))
        for key, info in sorted(runs.items(), key=lambda kv: kv[1]["idx"][0]):
            run_m = len(info["idx"]) * (length / k) / scale
            if key != centre_key and run_m < MIN_DOOR_RUN_M:
                continue
            i0, i1 = min(info["idx"]), max(info["idx"]) + 1
            seg = LineString([(x0 + dx * i0 / k, y0 + dy * i0 / k), (x0 + dx * i1 / k, y0 + dy * i1 / k)])
            a, b = info["a"], info["b"]
            usable = bool(a and b and a["id"] != b["id"] and a["walkable"] and b["walkable"])
            gates.append(dict(id=f"G{len(gates)}", kind="door", segment=seg, poly=d,
                              width_m=seg.length / scale,
                              room_a=a["id"] if a else "EXTERIOR",
                              room_b=b["id"] if b else "EXTERIOR", usable=usable))
    return gates


def _merge(a, b):
    """Union that never raises (falls back to the first geometry)."""
    if b is None or b.is_empty:
        return a
    try:
        return unary_union([a, b])
    except Exception:
        try:
            return unary_union([make_valid(a).buffer(0), make_valid(b).buffer(0)])
        except Exception:
            return a


def _open_passages(rooms, walls, door_polys, door_gates, wd, scale, min_m=None, windows=None):
    """A window is a barrier like a wall (cables may not pass it), so it is subtracted here too.
    Before this, a window drawn where two rooms meet the outer wall read as 'no wall' = a false passage."""
    walls = _merge(walls, windows)
    walk = [r for r in rooms if r["walkable"]]
    g = wd * 0.55
    min_open = (MIN_OPEN_M if min_m is None else min_m) * scale
    doors_u = unary_union([d.buffer(0.05 * wd) for d in door_polys]) if door_polys else None
    wall_near = walls.buffer(0.6 * wd) if not walls.is_empty else None   # a real opening has no wall beside it
    out = []
    for a, b in combinations(walk, 2):
        if a["poly"].distance(b["poly"]) > 2 * g:
            continue
        small = a if a["poly"].area <= b["poly"].area else b
        if a["poly"].intersection(b["poly"]).area > 0.5 * small["poly"].area:
            # one room's polygon lies inside the other's (e.g. storage inside living): the smaller
            # room is open to the bigger one wherever its own edge is not wall or door
            edge = small["poly"].boundary
            if wall_near is not None:
                edge = edge.difference(wall_near)
            if doors_u is not None:
                edge = edge.difference(doors_u)
            for seg in _line_runs(edge, min_open):
                out.append(dict(id=f"P{len(out)}", kind="open_passage", segment=seg,
                                poly=seg.buffer(0.5 * wd, cap_style="flat"),
                                width_m=seg.length / scale, room_a=a["id"], room_b=b["id"], usable=True))
            continue
        zone = a["poly"].buffer(g).intersection(b["poly"].buffer(g)).difference(walls)
        if doors_u is not None:
            zone = zone.difference(doors_u)
        for piece in polys(zone):
            for run in _straight_runs(piece, a["poly"], wd, min_open):
                # cut away every stretch that lies beside a wall; what is left is the real opening
                pieces = [run] if wall_near is None else _line_runs(run.difference(wall_near), min_open)
                for seg in pieces:
                    out.append(dict(id=f"P{len(out)}", kind="open_passage", segment=seg, poly=piece,
                                    width_m=seg.length / scale, room_a=a["id"], room_b=b["id"], usable=True))
    return out


def _rescue_passages(rooms, walls, door_polys, door_gates, passages, wd, scale, windows=None):
    """Narrow wall-free gaps (RESCUE_MIN_OPEN_M .. MIN_OPEN_M) are accepted only when they join two
    groups of rooms that are otherwise disconnected AND one of the groups holds an eligible room.
    Evidence: in benchmark plans every eligible room is reachable, yet 13 of 300 plans have a kitchen or
    storage whose only link is a 0.5-0.7 m opening."""
    parent = {r["id"]: r["id"] for r in rooms if r["walkable"]}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    for g in list(door_gates) + list(passages):
        if g["usable"]:
            union(g["room_a"], g["room_b"])
    elig = [r["id"] for r in rooms if r["eligible"]]
    if len({find(e) for e in elig}) <= 1:
        return []
    relaxed = _open_passages(rooms, walls, door_polys, door_gates, wd, scale, min_m=RESCUE_MIN_OPEN_M, windows=windows)
    relaxed.sort(key=lambda g: -g["width_m"])
    out = []
    for g in relaxed:
        ra, rb = find(g["room_a"]), find(g["room_b"])
        if ra == rb:
            continue
        if not any(find(e) in (ra, rb) for e in elig):
            continue
        union(g["room_a"], g["room_b"])
        g["rescue"] = True
        out.append(g)
    return out


def _straight_runs(piece, room_poly, wd, min_len):
    """Straight stretches of the room's boundary that lie along this piece."""
    return _line_runs(room_poly.boundary.intersection(piece.buffer(0.1 * wd)), min_len)


def _line_runs(geom, min_len):
    """Merge the LineStrings inside geom and return straight stretches of at least min_len."""
    parts, stack = [], [geom]
    while stack:                                              # collect non-empty LineStrings only
        x = stack.pop()
        if x.is_empty:
            continue
        if x.geom_type == "LineString":
            parts.append(x)
        elif hasattr(x, "geoms"):
            stack.extend(x.geoms)
    if not parts:
        return []
    merged = linemerge(parts)
    lines = list(merged.geoms) if hasattr(merged, "geoms") else [merged]
    runs = []
    for ln in lines:
        c = list(ln.simplify(0.01).coords)
        for p, q in zip(c, c[1:]):
            if math.dist(p, q) >= min_len:
                runs.append(LineString([p, q]))
    return runs


def _apply_clear_width(gates, free, wd, scale):
    """Measure how much of each usable gate's crossing line is actually free space (windows removed).
    Gates narrower than MIN_CLEAR_M are marked unusable + blocked, so B/C never rely on a gate that the
    router and the validator cannot cross. Returns True when any gate was blocked."""
    if free.is_empty:
        return False
    fb = free.buffer(0.05 * wd)
    changed = False
    for g in gates:
        if not g["usable"]:
            continue
        clear = g["segment"].intersection(fb).length / scale
        g["clear_width_m"] = clear
        if clear < MIN_CLEAR_M:
            g["usable"], g["blocked"], changed = False, True, True
    return changed


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
    # a piece holding no eligible room (e.g. an isolated stair) can never be routed through
    pts = [r["poly"].representative_point() for r in rooms if r["eligible"]]
    comps = polys(free)
    keep = [c for c in comps if any(c.contains(p) for p in pts)]
    if keep and len(keep) < len(comps):
        free = unary_union(keep)
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
    elig_ids = {r["id"] for r in elig}
    main = max({v for k, v in comp_of.items() if k in elig_ids and v is not None},
               key=lambda i: sum(1 for k, v in comp_of.items() if k in elig_ids and v == i), default=None)
    return dict(
        scale=round(scale, 3),
        eligible_rooms=len(elig),
        eligible_area_m2=round(area, 2),
        hub_lower_bound=max(math.ceil(area / MAX_HUB_AREA_M2), math.ceil(len(elig) / MAX_NODES_PER_HUB)) if elig else 0,
        oversized_rooms=[r["id"] for r in elig if r["area_m2"] > MAX_HUB_AREA_M2],
        door_gates=sum(1 for g in gates if g["kind"] == "door" and g["usable"]),
        open_passages=sum(1 for g in gates if g["kind"] == "open_passage"),
        exterior_doors=sum(1 for g in gates if g["kind"] == "door" and not g["usable"] and not g.get("blocked")),
        blocked_gates=[g["id"] for g in gates if g.get("blocked")],
        rooms_with_no_gate=sorted(k for k, v in adjacency.items() if not v and k in elig_ids),
        other_rooms_with_no_gate=sorted(k for k, v in adjacency.items() if not v and k not in elig_ids),
        free_space_pieces=len(comps),
        rooms_outside_main_free_space=sorted(k for k in elig_ids if comp_of.get(k) != main),
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
