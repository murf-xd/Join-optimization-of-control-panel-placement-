#!/usr/bin/env python3
"""demo_viz.py -- visualization demo on a HAND-MADE SYNTHETIC floor plan.

Nothing here is ResPlan data and the nodes are made up: the output is a demo of the
overlay only, never an official or research result.

    python demo_viz.py            # writes demo_out/demo_valid.png and demo_out/demo_violation.png
    python demo_viz.py --show     # also opens the windows

Layout (metres): 5 eligible rooms joined by 5 doors, 2 hubs, 5 nodes. Total eligible area
is 165.8 m2, so at least 2 hubs are needed (ceil(165.8 / 100) = 2).
"""
import copy
import math
import os
import sys

import numpy as np

from panel_routing.contract import Device, PanelAssignment, Plan, Room
from panel_routing.grid_router import GridRouter
from panel_routing.output import room_name, to_json
from panel_routing.route import route_all
from panel_routing.validator import validate
from visualize import draw

BANNER = "SYNTHETIC DEMO DATA: hand-made layout and nodes, not a ResPlan plan, not official"

# id: (type, x0, x1, y0, y1)
ROOMS = {
    1: ("living",  0.0, 8.0, 0.0, 6.0),
    2: ("kitchen", 8.2, 14.0, 0.0, 6.0),
    3: ("bedroom", 0.0, 6.0, 6.2, 11.0),
    4: ("bedroom", 6.2, 14.0, 6.2, 11.0),
    5: ("storage", 14.2, 17.0, 0.0, 6.0),
}
# door gaps (x0, x1, y0, y1) that connect two rooms through the wall band
DOOR_RECTS = [(8.0, 8.2, 2.0, 3.0), (2.0, 3.0, 6.0, 6.2), (6.0, 6.2, 8.0, 9.0),
              (11.0, 12.0, 6.0, 6.2), (14.0, 14.2, 2.0, 3.0)]
ADJACENCY = {1: [2, 3], 2: [1, 4, 5], 3: [1, 4], 4: [2, 3], 5: [2]}
# Made-up node positions. N2 sits mid-door-width (x=2.5, door is x 2..3). With N2 at the door
# edge (x=3.0) the current greedy router retraced 3 m of cable instead of using a parallel lane.
NODES = {1: (6.5, 1.0), 2: (2.5, 9.0), 3: (12.5, 1.0), 4: (9.5, 9.5), 5: (15.6, 3.0)}
NODE_ROOM = {1: 1, 2: 3, 3: 2, 4: 4, 5: 5}
HUBS = [(4.0, 3.0), (10.0, 3.0)]                       # made up, >= 0.5 m from walls
ASSIGN = [([1, 3], [1, 2]), ([2, 4, 5], [3, 4, 5])]    # (rooms, nodes) per hub


def _in(x, y, x0, x1, y0, y1):
    return (x >= x0) & (x <= x1) & (y >= y0) & (y <= y1)


def inside(x, y):
    ok = np.zeros(np.shape(x), dtype=bool)
    for _, x0, x1, y0, y1 in ROOMS.values():
        ok |= _in(x, y, x0, x1, y0, y1)
    for d in DOOR_RECTS:
        ok |= _in(x, y, *d)
    return ok


def room_contains(rid, p):
    _, x0, x1, y0, y1 = ROOMS[rid]
    return bool(_in(p[0], p[1], x0, x1, y0, y1))


def wall_distance(p):
    for _, x0, x1, y0, y1 in ROOMS.values():
        if _in(p[0], p[1], x0, x1, y0, y1):
            return min(p[0] - x0, x1 - p[0], p[1] - y0, y1 - p[1])
    return 0.0


def build():
    rooms = [Room(i, t, None, (x1 - x0) * (y1 - y0)) for i, (t, x0, x1, y0, y1) in ROOMS.items()]
    devices = [Device(i, NODE_ROOM[i], xy) for i, xy in NODES.items()]
    plan = Plan(rooms, devices, None, adjacency=ADJACENCY, plan_id="SYNTHETIC_DEMO")
    assignments = [PanelAssignment(k, HUBS[k], r, n) for k, (r, n) in enumerate(ASSIGN)]
    router = GridRouter(inside, (0.0, 0.0, 17.0, 11.2), list(NODES.values()) + HUBS, step=0.1)
    loops = route_all(plan, assignments, router=router)
    return plan, to_json(plan, assignments, loops)


def shapes_and_labels():
    shapes, labels = {}, {}
    for i, (t, x0, x1, y0, y1) in ROOMS.items():
        shapes[room_name(i)] = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        labels[room_name(i)] = f"{room_name(i)} {t}  {(x1 - x0) * (y1 - y0):.1f} m2"
    return shapes, labels


def doors_for_drawing():
    out = []
    for x0, x1, y0, y1 in DOOR_RECTS:
        out.append(((x0, (y0 + y1) / 2), (x1, (y0 + y1) / 2)) if (x1 - x0) > (y1 - y0)
                   else (((x0 + x1) / 2, y0), ((x0 + x1) / 2, y1)))
    return out


def tamper(data):
    """Deliberately break one leg: route it straight through a wall (for the red-violation picture)."""
    bad = copy.deepcopy(data)
    hub = bad["hubs"][1]
    seg = max(hub["route_segments"], key=lambda s: abs(s["polyline"][-1][1] - s["polyline"][0][1]))
    p0, p1 = seg["polyline"][0], seg["polyline"][-1]
    seg["polyline"] = [p0, [p0[0], p1[1]], p1]
    seg["length_m"] = round(sum(math.dist(a, b) for a, b in zip(seg["polyline"], seg["polyline"][1:])), 4)
    hub["ring_length_m"] = round(sum(s["length_m"] for s in hub["route_segments"]), 4)
    return bad


def main():
    show = "--show" in sys.argv
    os.makedirs("demo_out", exist_ok=True)
    plan, data = build()
    shapes, labels = shapes_and_labels()
    doors = doors_for_drawing()
    hooks = dict(inside=inside, wall_distance=wall_distance, room_contains=room_contains)

    report = validate(data, plan, **hooks)
    p1 = draw(data, shapes, "demo_out/demo_valid.png", doors=doors, report=report, room_labels=labels,
              title="Synthetic demo: routed design", banner=BANNER, show=show)
    print(f"valid design      : valid={report['valid']}  hubs={len(data['hubs'])} "
          f"(lower bound {report['hub_lower_bound']})  J={report['metrics']['J']:.2f}  -> {p1}")
    for v in report["violations"]:
        print("   ", v["rule"], v["message"])

    bad = tamper(data)
    bad_report = validate(bad, plan, **hooks)
    p2 = draw(bad, shapes, "demo_out/demo_violation.png", doors=doors, report=bad_report, room_labels=labels,
              title="Synthetic demo: same design with one leg deliberately routed through a wall",
              banner=BANNER, show=show)
    print(f"tampered design   : valid={bad_report['valid']}  violations={[v['rule'] for v in bad_report['violations']]}"
          f"  -> {p2}")
    if bad_report["valid"]:
        sys.exit("demo bug: the tampered design should have been flagged")


if __name__ == "__main__":
    main()
