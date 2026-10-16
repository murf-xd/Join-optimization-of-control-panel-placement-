"""Person B: validator and scorer.

Three entry points:

    assignment_problems(plan, panels)       rule violations in the room assignment
    loop_problems(plan, panels, loops)      rule violations in the cable rings
    score(plan, panels, loops)              valid? + the checker's metrics L, X, O, B, J

Metric definitions follow slides 6-7 of the problem statement. Tolerance 1 mm: points
closer than that are the same point, lines closer than that are the same line.
Coordinates are metres (see contract_merged.py).

    J = L + 5*X + O + 0.5*B
    L  cable length, every leg of every ring, return legs included (1 per m)
    X  crossings: points where two cables meet away from a node or hub (5 each)
    O  overlap: length on the same line; a stretch covered by k legs counts (k-1) times
    B  bends: direction changes along each closed ring, nodes and hub included; a
       reversal counts once (0.5 each)

Interpretation notes (check them against the organisers' checker when it is released):
  * Rings are treated as cyclic: the turn at the hub, where the last leg meets the first,
    counts as a bend like any other vertex.
  * Two consecutive segments of the same ring never count as crossing each other.
  * Collinear pieces are overlap, never crossing.
"""
import math
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from legacy_assign import PASS_THROUGH_TYPES, eligible_graph, is_connected
from contract_merged import (MAX_PANEL_AREA, MAX_PANEL_DEVICES, Loop, PanelAssignment,
                             Plan, XY)

try:                                              # shapely is only needed for polygon checks
    from shapely.geometry import LineString, Point
except ImportError:                               # pragma: no cover
    LineString = Point = None

TOL = 1e-3                                        # 1 mm
HUB_WALL_CLEARANCE = 0.5                          # metres, slide 3 rule 6
W_CROSSING, W_OVERLAP, W_BEND = 5.0, 1.0, 0.5

Segment = Tuple[XY, XY]


# ------------------------------------------------------------------ small geometry
def _same(p: XY, q: XY) -> bool:
    return abs(p[0] - q[0]) <= TOL and abs(p[1] - q[1]) <= TOL


def _clean(poly: Sequence[XY]) -> List[XY]:
    """Drop repeated consecutive points."""
    out: List[XY] = []
    for p in poly:
        p = (float(p[0]), float(p[1]))
        if not out or not _same(out[-1], p):
            out.append(p)
    return out


def _segments(poly: Sequence[XY]) -> List[Segment]:
    pts = _clean(poly)
    return [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]


def _is_horizontal(s: Segment) -> bool:
    return abs(s[0][1] - s[1][1]) <= TOL and abs(s[0][0] - s[1][0]) > TOL


def _is_vertical(s: Segment) -> bool:
    return abs(s[0][0] - s[1][0]) <= TOL and abs(s[0][1] - s[1][1]) > TOL


def _seg_len(s: Segment) -> float:
    return math.hypot(s[1][0] - s[0][0], s[1][1] - s[0][1])


# -------------------------------------------------------------------------- metrics
def polyline_length(poly: Sequence[XY]) -> float:
    return sum(_seg_len(s) for s in _segments(poly))


def ring_bends(poly: Sequence[XY]) -> int:
    """Direction changes along a closed ring (cyclic; the vertex at the hub counts)."""
    pts = _clean(poly)
    if len(pts) > 1 and _same(pts[0], pts[-1]):
        pts = pts[:-1]
    n = len(pts)
    if n < 2:
        return 0
    dirs = []
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        dirs.append(((b[0] - a[0]) / d, (b[1] - a[1]) / d) if d > 0 else None)
    bends = 0
    for i in range(n):
        d0, d1 = dirs[i - 1], dirs[i]
        if d0 is None or d1 is None:
            continue
        cross = d0[0] * d1[1] - d0[1] * d1[0]
        dot = d0[0] * d1[0] + d0[1] * d1[1]
        if abs(cross) > 1e-6 or dot < 0:          # a turn, or a reversal (counts once)
            bends += 1
    return bends


def _cluster(values: List[float]) -> Dict[int, float]:
    """Map each value's index to a representative so values within TOL share one line."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    rep: Dict[int, float] = {}
    current = None
    for i in order:
        if current is None or values[i] - current > TOL:
            current = values[i]
        rep[i] = current
    return rep


def overlap_length(segments: Iterable[Segment]) -> float:
    """Length covered more than once on the same line; depth k counts (k - 1) times."""
    segs = list(segments)
    total = 0.0
    for horizontal in (True, False):
        subset = [s for s in segs if (_is_horizontal(s) if horizontal else _is_vertical(s))]
        if not subset:
            continue
        axis = 1 if horizontal else 0             # coordinate that is constant on a line
        run = 0 if horizontal else 1              # coordinate that varies along the line
        rep = _cluster([(s[0][axis] + s[1][axis]) / 2 for s in subset])
        lines: Dict[float, List[Tuple[float, float]]] = defaultdict(list)
        for i, s in enumerate(subset):
            a, b = sorted((s[0][run], s[1][run]))
            lines[rep[i]].append((a, b))
        for intervals in lines.values():
            events = sorted([(a, 1) for a, _ in intervals] + [(b, -1) for _, b in intervals],
                            key=lambda e: (e[0], e[1]))
            depth, prev = 0, None
            for x, step in events:
                if prev is not None and depth > 1:
                    total += (depth - 1) * (x - prev)
                depth += step
                prev = x
    return total


def count_crossings(rings: Sequence[Sequence[XY]], special: Iterable[XY]) -> int:
    """Distinct points where two cables meet away from a node or hub."""
    special = list(special)
    tagged: List[Tuple[int, int, int, Segment]] = []        # (ring, index, ring_len, seg)
    for r, poly in enumerate(rings):
        segs = _segments(poly)
        for i, s in enumerate(segs):
            tagged.append((r, i, len(segs), s))
    found: Set[Tuple[int, int]] = set()
    for a in range(len(tagged)):
        ra, ia, na, sa = tagged[a]
        for b in range(a + 1, len(tagged)):
            rb, ib, nb, sb = tagged[b]
            if ra == rb:
                gap = abs(ia - ib)
                if gap == 1 or gap == na - 1:       # consecutive segments of one ring
                    continue
            if _is_horizontal(sa) and _is_vertical(sb):
                h, v = sa, sb
            elif _is_vertical(sa) and _is_horizontal(sb):
                h, v = sb, sa
            else:
                continue                            # parallel/collinear: overlap, not crossing
            x, y = v[0][0], h[0][1]
            if (min(h[0][0], h[1][0]) - TOL <= x <= max(h[0][0], h[1][0]) + TOL
                    and min(v[0][1], v[1][1]) - TOL <= y <= max(v[0][1], v[1][1]) + TOL):
                if any(_same((x, y), sp) for sp in special):
                    continue
                found.add((round(x / TOL), round(y / TOL)))
    return len(found)


def _area_gap(plan: Plan, panels: Sequence[PanelAssignment]) -> float:
    totals = [sum(plan.room_by_id(r).area for r in p.room_ids) for p in panels]
    return max(totals) - min(totals) if totals else 0.0


def metrics(plan: Plan, panels: Sequence[PanelAssignment], loops: Sequence[Loop]) -> Dict[str, float]:
    """H, L, X, O, B and J recomputed from the polylines (reported values are ignored)."""
    rings = [l.route_coords for l in loops]
    special = [d.xy for d in plan.devices] + [p.panel_xy for p in panels]
    all_segments = [s for ring in rings for s in _segments(ring)]
    L = sum(polyline_length(r) for r in rings)
    X = count_crossings(rings, special)
    O = overlap_length(all_segments)
    B = sum(ring_bends(r) for r in rings)
    return {
        "H": len(panels), "L": L, "X": X, "O": O, "B": B,
        "J": L + W_CROSSING * X + W_OVERLAP * O + W_BEND * B,
        "area_gap": _area_gap(plan, panels),
    }


# ------------------------------------------------------------------- rule checks
def assignment_problems(plan: Plan, panels: Sequence[PanelAssignment],
                        pass_through: Iterable[str] = PASS_THROUGH_TYPES) -> List[str]:
    """Rule violations in the room assignment (empty list = all good)."""
    out: List[str] = []
    graph = eligible_graph(plan, pass_through)
    eligible = {r.id for r in plan.rooms if r.eligible}

    if len({p.panel_id for p in panels}) != len(panels):
        out.append("panel ids must be unique")

    rooms_seen = [r for p in panels for r in p.room_ids]
    if sorted(rooms_seen) != sorted(eligible):
        out.append("every eligible room must be assigned exactly once")

    dev_seen = [d for p in panels for d in p.device_ids]
    if sorted(dev_seen) != sorted(d.id for d in plan.devices):
        out.append("every device must be assigned exactly once")

    for p in panels:
        area = sum(plan.room_by_id(r).area for r in p.room_ids)
        if (area > MAX_PANEL_AREA or len(p.device_ids) > MAX_PANEL_DEVICES) and not p.warnings:
            out.append(f"panel {p.panel_id} over capacity with no warning")
        if not set(p.room_ids) <= set(graph):
            out.append(f"panel {p.panel_id} has rooms that are not eligible")
        elif not is_connected(set(p.room_ids), graph):
            out.append(f"panel {p.panel_id} rooms are not contiguous")
        for d in p.device_ids:                       # node must sit in one of the hub's rooms
            if plan.device_by_id(d).room_id not in p.room_ids:
                out.append(f"panel {p.panel_id} has device {d} outside its rooms")
    return out


def _vertex_index(poly: Sequence[XY], point: XY, start: int) -> Optional[int]:
    for i in range(start, len(poly)):
        if _same(poly[i], point):
            return i
    return None


def loop_problems(plan: Plan, panels: Sequence[PanelAssignment], loops: Sequence[Loop]) -> List[str]:
    """Rule violations in the cable rings (empty list = all good)."""
    out: List[str] = []
    by_panel = {l.panel_id: l for l in loops}
    if len(by_panel) != len(loops):
        out.append("more than one ring for the same panel")
    for l in loops:
        if l.panel_id not in {p.panel_id for p in panels}:
            out.append(f"ring for unknown panel {l.panel_id}")

    free = None
    if plan.free_space is not None and LineString is not None:
        free = plan.free_space.buffer(TOL)

    for p in panels:
        loop = by_panel.get(p.panel_id)
        if loop is None:
            out.append(f"panel {p.panel_id} has no ring")
            continue
        tag = f"panel {p.panel_id}"
        poly = _clean(loop.route_coords)

        if sorted(loop.order) != sorted(p.device_ids):
            out.append(f"{tag}: ring must visit every assigned node exactly once")
        if len(poly) < 2:
            # A zero-length ring is only possible when the hub sits exactly on every node it
            # serves (typically a one-room hub with the hub on its node). Accepted here;
            # whether the organisers' checker accepts it is the "hub on a node?" question.
            if any(not _same(plan.device_by_id(d).xy, p.panel_xy)
                   for d in p.device_ids if d in {x.id for x in plan.devices}):
                out.append(f"{tag}: ring has no route")
                continue

        if poly:
            if not _same(poly[0], p.panel_xy) or not _same(poly[-1], p.panel_xy):
                out.append(f"{tag}: ring must start and end at its own hub")
        idx = 0                                       # nodes must be visited in `order`
        for d in loop.order:
            if d not in {x.id for x in plan.devices}:
                out.append(f"{tag}: unknown node {d}")
                continue
            xy = plan.device_by_id(d).xy
            found = _vertex_index(poly, xy, idx)
            if found is None:
                out.append(f"{tag}: node {d} is not reached in order (needs to be a route vertex)")
            else:
                idx = found

        for s in _segments(poly):
            if not (_is_horizontal(s) or _is_vertical(s)):
                out.append(f"{tag}: segment {s[0]} -> {s[1]} is not horizontal or vertical")
            elif free is not None and not free.covers(LineString(s)):
                out.append(f"{tag}: segment {s[0]} -> {s[1]} leaves the free space")

        if Point is not None:                         # hub point rule (slide 3, rule 6)
            hub = Point(p.panel_xy)
            polys = [plan.room_by_id(r).polygon for r in p.room_ids]
            polys = [g for g in polys if g is not None]
            if polys:
                ok = any(g.contains(hub) and g.boundary.distance(hub) >= HUB_WALL_CLEARANCE - TOL
                         for g in polys)
                if not ok:
                    out.append(f"{tag}: hub must be inside one of its rooms, "
                               f"{HUB_WALL_CLEARANCE} m from walls")
    return out


def score(plan: Plan, panels: Sequence[PanelAssignment], loops: Sequence[Loop],
          pass_through: Iterable[str] = PASS_THROUGH_TYPES) -> Dict[str, object]:
    """Valid? plus the metrics. Ranking: fewest H, then lowest J, then smaller area_gap."""
    problems = assignment_problems(plan, panels, pass_through) + loop_problems(plan, panels, loops)
    return {"valid": not problems, "problems": problems, **metrics(plan, panels, loops)}
