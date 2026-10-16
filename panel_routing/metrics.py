"""Cost metrics exactly as the organisers' checker defines them (slides 6 and 7).

    J = L + 5*X + O + 0.5*B     (metres; fewest hubs is compared before J)

A ring is a list of legs; a leg is a polyline [(x, y), ...] in metres. A ring is
closed: the last leg ends where the first leg starts (the hub).

    L  total polyline length, every leg, return legs included
    X  points where two cables meet away from a node or hub (once per point)
    O  length lying on the same line as other cable; a stretch covered by k legs
       counts (k - 1) times. A retrace on the same line counts, parallel runs do not
    B  direction changes along each closed ring (nodes and hub included);
       a reversal counts once

Tolerance 1 mm: points closer than that are one point, lines closer are one line.
"""
import math

TOL = 1e-3
W_L, W_X, W_O, W_B = 1.0, 5.0, 1.0, 0.5


def ring_vertices(legs):
    """Closed vertex list of a ring (consecutive duplicates and the closing repeat removed)."""
    pts = []
    for leg in legs:
        for p in leg:
            p = (float(p[0]), float(p[1]))
            if not pts or math.dist(p, pts[-1]) > TOL:
                pts.append(p)
    if len(pts) > 1 and math.dist(pts[0], pts[-1]) <= TOL:
        pts.pop()
    return pts


def _segments(verts):
    n = len(verts)
    if n < 2:
        return []
    return [(verts[k], verts[(k + 1) % n]) for k in range(n)]


def ring_length(verts):
    return sum(math.dist(a, b) for a, b in _segments(verts))


def ring_bends(verts):
    n = len(verts)
    if n < 2:
        return 0
    bends = 0
    for k in range(n):
        p, q, r = verts[k - 1], verts[k], verts[(k + 1) % n]
        u = (q[0] - p[0], q[1] - p[1])
        v = (r[0] - q[0], r[1] - q[1])
        cross = u[0] * v[1] - u[1] * v[0]
        dot = u[0] * v[0] + u[1] * v[1]
        norm = math.hypot(*u) * math.hypot(*v)
        if norm == 0:
            continue
        if abs(cross) > 1e-6 * norm or dot < 0:   # a turn, or a reversal (counts once)
            bends += 1
    return bends


def _axis_segments(rings_verts):
    """[(axis, fixed, lo, hi, ring, idx)] with axis 0 = horizontal (y fixed), 1 = vertical."""
    out, non_axis = [], 0
    for r, verts in enumerate(rings_verts):
        for k, (a, b) in enumerate(_segments(verts)):
            if abs(a[1] - b[1]) <= TOL:
                out.append((0, (a[1] + b[1]) / 2, min(a[0], b[0]), max(a[0], b[0]), r, k))
            elif abs(a[0] - b[0]) <= TOL:
                out.append((1, (a[0] + b[0]) / 2, min(a[1], b[1]), max(a[1], b[1]), r, k))
            else:
                non_axis += 1
    return out, non_axis


def _overlap(segs):
    total = 0.0
    for axis in (0, 1):
        group = sorted((s for s in segs if s[0] == axis), key=lambda s: s[1])
        clusters, cur = [], []
        for s in group:
            if cur and s[1] - cur[-1][1] > TOL:
                clusters.append(cur)
                cur = []
            cur.append(s)
        if cur:
            clusters.append(cur)
        for cl in clusters:
            events = sorted([(s[2], 1) for s in cl] + [(s[3], -1) for s in cl])
            count, prev = 0, None
            for pos, delta in events:
                if prev is not None and pos > prev:
                    total += (pos - prev) * max(count - 1, 0)
                count += delta
                prev = pos
    return total


def _crossings(segs, rings_verts, node_pts):
    sizes = [len(v) for v in rings_verts]
    points = {}
    for h in (s for s in segs if s[0] == 0):
        for v in (s for s in segs if s[0] == 1):
            px, py = v[1], h[1]
            if not (h[2] - TOL <= px <= h[3] + TOL and v[2] - TOL <= py <= v[3] + TOL):
                continue
            if h[4] == v[4]:                       # consecutive segments of one ring meet at a vertex
                n = sizes[h[4]]
                if (v[5] - h[5]) % n in (1, n - 1):
                    continue
            if any(math.hypot(px - nx, py - ny) <= TOL for nx, ny in node_pts):
                continue
            key = (round(px * 1000), round(py * 1000))
            points.setdefault(key, set()).update((h[4], v[4]))
    return points


def score(rings, node_points=None):
    """rings: list of rings, each a list of legs, each a list of (x, y) in metres."""
    verts = [ring_vertices(legs) for legs in rings]
    if node_points is None:
        node_points = [p for legs in rings for leg in legs if leg for p in (leg[0], leg[-1])]
    segs, non_axis = _axis_segments(verts)
    L = sum(ring_length(v) for v in verts)
    B = sum(ring_bends(v) for v in verts)
    O = _overlap(segs)
    pts = _crossings(segs, verts, node_points)
    per_ring_x = [sum(1 for rs in pts.values() if r in rs) for r in range(len(rings))]
    return {
        "L": L, "X": len(pts), "O": O, "B": B,
        "J": W_L * L + W_X * len(pts) + W_O * O + W_B * B,
        "per_ring": [{"L": ring_length(v), "B": ring_bends(v), "X": x}
                     for v, x in zip(verts, per_ring_x)],
        "non_axis_segments": non_axis,
    }


def score_json(data):
    """Recompute everything from an output JSON (slide 8 format), ignoring reported values."""
    rings = [[seg["polyline"] for seg in hub["route_segments"]] for hub in data["hubs"]]
    nodes = [(h["location"]["x"], h["location"]["y"]) for h in data["hubs"]]
    for legs in rings:
        for leg in legs:
            if leg:
                nodes.extend((leg[0], leg[-1]))
    s = score(rings, nodes)
    s["H"] = len(data["hubs"])
    return s
