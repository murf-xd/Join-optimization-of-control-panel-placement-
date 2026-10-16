"""Output JSON in the organisers' format (slide 8). Units: metres, origin lower-left, y up.

The checker ignores reported values and recomputes everything from the polylines.
Names follow the slide example (H1, N1, R05); change the three name functions below once
the organisers' input JSON shows its own room and node ids.
"""
import json
import math

from .metrics import TOL


def hub_name(panel_id):
    return f"H{panel_id + 1}"


def node_name(device_id):
    return f"N{device_id}"


def room_name(room_id):
    return f"R{int(room_id):02d}" if str(room_id).lstrip("-").isdigit() else str(room_id)


def _pt(p):
    return [round(float(p[0]), 4), round(float(p[1]), 4)]


def _poly_length(poly):
    return sum(math.dist(poly[i], poly[i + 1]) for i in range(len(poly) - 1))


def _legs_of(loop, hub_xy, plan):
    legs = getattr(loop, "legs", None)
    if legs:
        return legs
    # Fallback: cut the closed polyline at the node points, in visiting order.
    seq = [hub_xy] + [tuple(plan.device_by_id(d).xy) for d in loop.order] + [hub_xy]
    coords, legs, start = list(loop.route_coords), [], 0
    for target in seq[1:]:
        end = next((i for i in range(start + 1, len(coords))
                    if math.dist(coords[i], target) <= TOL), len(coords) - 1)
        legs.append(coords[start:end + 1])
        start = end
    return legs


def _room_of_hub(plan, a):
    try:
        from shapely.geometry import Point
        p = Point(a.panel_xy)
        for rid in a.room_ids:
            if plan.room_by_id(rid).polygon.covers(p):
                return rid
    except Exception:
        pass
    return a.room_ids[0] if a.room_ids else None


def to_json(plan, assignments, loops):
    by_panel = {l.panel_id: l for l in loops}
    hubs, total = [], 0.0
    for a in assignments:
        loop = by_panel[a.panel_id]
        hid = hub_name(a.panel_id)
        hub_xy = (float(a.panel_xy[0]), float(a.panel_xy[1]))
        legs = _legs_of(loop, hub_xy, plan) if loop.order else []
        names = [hid] + [node_name(d) for d in loop.order] + [hid]
        segments = []
        for k, leg in enumerate(legs):
            segments.append({
                "from": names[k], "to": names[k + 1],
                "length_m": round(_poly_length(leg), 4),
                "polyline": [_pt(p) for p in leg],
            })
        ring_len = round(sum(s["length_m"] for s in segments), 4)
        total += ring_len
        rid = _room_of_hub(plan, a)
        hubs.append({
            "hub_id": hid,
            "room_id": room_name(rid) if rid is not None else None,
            "location": {"x": round(hub_xy[0], 4), "y": round(hub_xy[1], 4)},
            "assigned_rooms": [room_name(r) for r in a.room_ids],
            "assigned_nodes": [node_name(d) for d in a.device_ids],
            "closed_sequence": names,
            "route_segments": segments,
            "ring_length_m": ring_len,
        })
    return {
        "plan_id": plan.plan_id,
        "units": "m",
        "hubs": hubs,
        "reported_metrics": {"hub_count": len(hubs), "total_length_m": round(total, 4)},
    }


def debug_info(assignments, loops):
    """Warnings and per-ring metrics; kept out of the official JSON on purpose."""
    return [{"hub_id": hub_name(l.panel_id), "warnings": list(l.warnings),
             "bends": l.bends, "crossings": l.crossings, "length_m": round(l.length, 4)}
            for l in loops]


def write_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
