"""Independent validator for an output JSON (slide 8 format) against a Plan.

It deliberately does NOT trust the router: it re-derives every hard rule of slide 3
from the JSON alone, and re-computes J with metrics.score_json (reported values are
ignored, as the organisers' checker does).

    report = validate(data, plan, inside=..., wall_distance=..., room_contains=...)
    report["valid"], report["violations"], report["metrics"]

Optional geometry hooks (so the validator needs no shapely itself):
    inside(xs, ys)                -> bool array, True where cable may run (free space)
    wall_distance((x, y))         -> metres from the point to the nearest wall
    room_contains(room_id, (x,y)) -> bool, point lies inside that Plan room
A rule whose hook is missing is listed under report["unchecked"], never silently passed.
"""
import math
from collections import Counter

import numpy as np

from .metrics import TOL, score_json
from .output import node_name, room_name

# Official numbers (slide 2/3), kept separate from contract.py on purpose.
MAX_AREA_M2 = 100.0
MAX_NODES = 5
MIN_HUB_CLEARANCE_M = 0.5


def _seg_len(poly):
    return sum(math.dist(poly[i], poly[i + 1]) for i in range(len(poly) - 1))


def validate(data, plan, inside=None, wall_distance=None, room_contains=None,
             allow_passthrough=False, sample_step=0.02):
    violations, unchecked = [], []

    def bad(rule, msg, hub=None):
        violations.append({"rule": rule, "hub": hub, "message": msg})

    # ---- schema ------------------------------------------------------------
    for k in ("plan_id", "units", "hubs", "reported_metrics"):
        if k not in data:
            bad("schema", f"missing top-level key '{k}'")
    if violations:
        return {"valid": False, "violations": violations, "unchecked": unchecked, "metrics": None}
    if data["units"] != "m":
        bad("schema", f"units must be 'm', got {data['units']!r}")
    hub_keys = ("hub_id", "room_id", "location", "assigned_rooms", "assigned_nodes",
                "closed_sequence", "route_segments", "ring_length_m")
    hubs = data["hubs"]
    for h in hubs:
        for k in hub_keys:
            if k not in h:
                bad("schema", f"hub is missing '{k}'", h.get("hub_id"))
    if violations:
        return {"valid": False, "violations": violations, "unchecked": unchecked, "metrics": None}
    if len({h["hub_id"] for h in hubs}) != len(hubs):
        bad("schema", "duplicate hub_id")

    # ---- plan lookups ------------------------------------------------------
    rooms = {room_name(r.id): r for r in plan.rooms}
    eligible = {n for n, r in rooms.items() if r.eligible}
    node_xy = {node_name(d.id): (float(d.xy[0]), float(d.xy[1])) for d in plan.devices}
    node_room = {node_name(d.id): room_name(d.room_id) for d in plan.devices}
    adj = {room_name(k): [room_name(n) for n in v] for k, v in (plan.adjacency or {}).items()}

    per_room = Counter(node_room.values())
    for n in eligible:
        if per_room[n] != 1:
            bad("input", f"eligible room {n} has {per_room[n]} nodes in the plan (expected 1)")

    # ---- 1. coverage -------------------------------------------------------
    room_count = Counter(r for h in hubs for r in h["assigned_rooms"])
    node_count = Counter(n for h in hubs for n in h["assigned_nodes"])
    for n in sorted(eligible):
        if room_count[n] != 1:
            bad("coverage", f"eligible room {n} is assigned {room_count[n]} times (must be exactly 1)")
    for n in sorted(node_xy):
        if node_count[n] != 1:
            bad("coverage", f"node {n} is assigned {node_count[n]} times (must be exactly 1)")
    for n in room_count:
        if n not in eligible:
            bad("coverage", f"assigned room {n} is not an eligible room of this plan")
    for n in node_count:
        if n not in node_xy:
            bad("coverage", f"assigned node {n} does not exist in this plan")

    for h in hubs:
        hid = h["hub_id"]
        ar, an = h["assigned_rooms"], h["assigned_nodes"]

        # ---- 2. capacity ---------------------------------------------------
        area = sum(rooms[r].area for r in ar if r in rooms)
        if area > MAX_AREA_M2 + 1e-6:
            bad("capacity", f"{area:.2f} m2 assigned, limit {MAX_AREA_M2:g}", hid)
        if len(an) > MAX_NODES:
            bad("capacity", f"{len(an)} nodes assigned, limit {MAX_NODES}", hid)
        for n in an:
            if n in node_room and node_room[n] not in ar:
                bad("coverage", f"node {n} is in room {node_room[n]}, which is not assigned to this hub", hid)

        # ---- 3. zone: connected through doors / open passages only ----------
        ok_rooms = set(ar)
        if allow_passthrough:
            ok_rooms |= {n for n in rooms if n not in eligible}
        if ar and all(r in ok_rooms for r in ar):
            seen, stack = {ar[0]}, [ar[0]]
            while stack:
                for nb in adj.get(stack.pop(), []):
                    if nb in ok_rooms and nb not in seen:
                        seen.add(nb)
                        stack.append(nb)
            lost = [r for r in ar if r not in seen]
            if lost:
                bad("zone", f"rooms {lost} are not connected to {ar[0]} through doors/openings", hid)

        # ---- 6. hub point ---------------------------------------------------
        loc = (float(h["location"]["x"]), float(h["location"]["y"]))
        if h["room_id"] not in ar:
            bad("hub", f"hub room {h['room_id']} is not one of the hub's assigned rooms", hid)
        elif h["room_id"] not in eligible:
            bad("hub", f"hub room {h['room_id']} is not an eligible room", hid)
        if room_contains is None:
            unchecked.append("hub point inside its room (no room_contains hook)")
        else:
            rid = next((r.id for r in plan.rooms if room_name(r.id) == h["room_id"]), None)
            if rid is None or not room_contains(rid, loc):
                bad("hub", f"hub point {loc} is not inside room {h['room_id']}", hid)
        if wall_distance is None:
            unchecked.append("hub >= 0.5 m from walls (no wall_distance hook)")
        elif wall_distance(loc) < MIN_HUB_CLEARANCE_M - TOL:
            bad("hub", f"hub point {loc} is {wall_distance(loc):.3f} m from a wall (< {MIN_HUB_CLEARANCE_M} m)", hid)

        # ---- 4. ring --------------------------------------------------------
        seq, segs = h["closed_sequence"], h["route_segments"]
        if len(seq) < 2 or seq[0] != hid or seq[-1] != hid:
            bad("ring", f"closed_sequence must start and end at {hid}: {seq}", hid)
        if sorted(seq[1:-1]) != sorted(an) or len(set(seq[1:-1])) != len(seq[1:-1]):
            bad("ring", f"ring must visit every assigned node exactly once: {seq[1:-1]} vs {an}", hid)
        if len(segs) != len(seq) - 1:
            bad("ring", f"{len(segs)} route_segments for a sequence of {len(seq)} stops", hid)
            continue
        where = lambda name: loc if name == hid else node_xy.get(name)
        prev_end, total = None, 0.0
        for k, s in enumerate(segs):
            poly = [(float(p[0]), float(p[1])) for p in s["polyline"]]
            if len(poly) < 2 and not (s["from"] == s["to"]):
                bad("ring", f"segment {k} has no polyline", hid)
                continue
            if s["from"] != seq[k] or s["to"] != seq[k + 1]:
                bad("ring", f"segment {k} is {s['from']}->{s['to']}, sequence says {seq[k]}->{seq[k + 1]}", hid)
            for end, name in ((poly[0], s["from"]), (poly[-1], s["to"])):
                target = where(name)
                if target is None:
                    bad("ring", f"unknown stop {name}", hid)
                elif math.dist(end, target) > TOL:
                    rule = "node_fixed" if name != hid else "ring"
                    bad(rule, f"segment {k} should touch {name} at {target} but ends at {end}", hid)
            if prev_end is not None and math.dist(prev_end, poly[0]) > TOL:
                bad("ring", f"segment {k} does not start where segment {k - 1} ended", hid)
            prev_end = poly[-1]
            length = _seg_len(poly)
            total += length
            if abs(length - float(s["length_m"])) > 2 * TOL:
                bad("ring", f"segment {k} length_m {s['length_m']} != polyline length {length:.4f}", hid)

            # ---- 5. free space: axis-aligned, inside the free space ----------
            for a, b in zip(poly, poly[1:]):
                if abs(a[0] - b[0]) > TOL and abs(a[1] - b[1]) > TOL:
                    bad("axis_aligned", f"segment {k}: {a}->{b} is neither horizontal nor vertical", hid)
                elif inside is not None:
                    n = max(2, int(math.dist(a, b) / sample_step) + 1)
                    xs, ys = np.linspace(a[0], b[0], n), np.linspace(a[1], b[1], n)
                    ok = np.asarray(inside(xs, ys), dtype=bool)
                    if not ok.all():
                        i = int(np.argmin(ok))
                        bad("free_space", f"segment {k}: cable at ({xs[i]:.3f}, {ys[i]:.3f}) is outside "
                            f"the free space (wall, window, exterior or a gap that is not a door)", hid)
                        break
        if abs(total - float(h["ring_length_m"])) > 4 * TOL * max(1, len(segs)):
            bad("ring", f"ring_length_m {h['ring_length_m']} != sum of segments {total:.4f}", hid)
    if inside is None:
        unchecked.append("cable inside free space / doors only (no inside hook)")

    try:
        metrics = score_json(data)
    except Exception as e:                      # malformed polylines already reported above
        metrics = None
        bad("schema", f"could not recompute metrics: {e}")
    elig_area = sum(rooms[n].area for n in eligible)
    lb = max(math.ceil(elig_area / MAX_AREA_M2 - 1e-9), math.ceil(len(node_xy) / MAX_NODES)) if node_xy else 0
    return {
        "valid": not violations,
        "violations": violations,
        "unchecked": sorted(set(unchecked)),
        "metrics": metrics,
        "hub_count": len(hubs),
        "hub_lower_bound": lb,
    }
