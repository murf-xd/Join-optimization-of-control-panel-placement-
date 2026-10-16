"""Export one v2 development sample to JSON and a floor-plan PNG."""
import json
import math
import pickle
import sys
from pathlib import Path

B_PACKAGE = Path.home() / "Downloads/person_b_staging/person_b_new"
sys.path.insert(0, str(B_PACKAGE))

from pipeline import solve
import routing_v2
from visualize import draw

OUT = Path("out_v2")
OUT.mkdir(exist_ok=True)

with open(B_PACKAGE / "sample_plans.pkl", "rb") as f:
    data = pickle.load(f)

plans = list(data.values()) if isinstance(data, dict) else list(data)
plan = next((p for p in plans if str(p.plan_id) == "14433"), plans[0])

solution = solve(
    plan, route=routing_v2.route,
    limit=1, refine=False, n_restarts=2, seed=0
)

if not solution.result.get("valid"):
    raise SystemExit("INVALID solution; not exporting as valid: "
                     + repr(solution.result.get("problems")))

def pt(xy):
    return [round(float(xy[0]), 4), round(float(xy[1]), 4)]

def close(a, b, tol=1e-3):
    return math.dist(a, b) <= tol

by_panel = {loop.panel_id: loop for loop in solution.loops}
hubs = []
room_shapes = {}

for room in plan.rooms:
    poly = room.polygon
    if poly is not None and not poly.is_empty and poly.geom_type == "Polygon":
        room_shapes[room.id] = [pt(xy) for xy in list(poly.exterior.coords)[:-1]]

for panel in solution.panels:
    loop = by_panel[panel.panel_id]
    coords = [tuple(map(float, xy)) for xy in loop.route_coords]
    hub_xy = tuple(map(float, panel.panel_xy))

    # Split the closed route at each assigned node, in visit order.
    targets = [tuple(plan.node(n).xy) for n in loop.order] + [hub_xy]
    legs, start = [], 0
    for target in targets:
        end = next(
            (i for i in range(start + 1, len(coords))
             if close(coords[i], target)),
            None
        )
        if end is None:
            raise RuntimeError(
                f"Cannot split {panel.panel_id} route at {target}; "
                "refusing to export incomplete segments."
            )
        legs.append(coords[start:end + 1])
        start = end

    names = [panel.panel_id] + list(loop.order) + [panel.panel_id]
    segments = []
    for i, leg in enumerate(legs):
        length = sum(math.dist(a, b) for a, b in zip(leg, leg[1:]))
        segments.append({
            "from": names[i],
            "to": names[i + 1],
            "length_m": round(length, 4),
            "polyline": [pt(xy) for xy in leg],
        })

    hub_room = next(
        (rid for rid in panel.room_ids
         if plan.room(rid).polygon.covers(
             __import__("shapely.geometry", fromlist=["Point"]).Point(hub_xy)
         )),
        panel.room_ids[0] if panel.room_ids else None
    )
    hubs.append({
        "hub_id": panel.panel_id,
        "room_id": hub_room,
        "location": {"x": round(hub_xy[0], 4), "y": round(hub_xy[1], 4)},
        "assigned_rooms": list(panel.room_ids),
        "assigned_nodes": list(panel.node_ids),
        "closed_sequence": names,
        "route_segments": segments,
        "ring_length_m": round(sum(s["length_m"] for s in segments), 4),
    })

result = {
    "plan_id": plan.plan_id,
    "units": "m",
    "development_sample": True,
    "validation": solution.result,
    "hubs": hubs,
    "reported_metrics": {
        "hub_count": solution.result["H"],
        "total_length_m": round(solution.result["L"], 4),
        "X": solution.result["X"],
        "O": solution.result["O"],
        "B": solution.result["B"],
        "J": solution.result["J"],
    },
}

json_path = OUT / "plan_14433.json"
json_path.write_text(json.dumps(result, indent=2))

report = {
    "valid": True,
    "violations": [],
    "metrics": solution.result,
}
png_path = OUT / "plan_14433.png"
draw(
    result, room_shapes, str(png_path),
    report=report,
    title=f"Development sample {plan.plan_id}",
    banner="DEVELOPMENT SAMPLE — NOT OFFICIAL",
)

print("VALID:", solution.result["valid"])
print("HUBS:", len(hubs))
print("JSON:", json_path.resolve())
print("IMAGE:", png_path.resolve())
print("METRICS:", result["reported_metrics"])
