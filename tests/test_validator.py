"""Break each hard rule on purpose and check the validator catches exactly that."""
import copy
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from panel_routing.contract import Device, PanelAssignment, Plan, Room
from panel_routing.output import to_json
from panel_routing.route import route_all
from panel_routing.validator import validate
from test_all import HUB, NODES, inside, make_router   # helpers only (no test_ names)

# Three eligible rooms, one node each: A = living, B1 = bedroom (top), B2 = storage (bottom).
RECT = {1: (0, 5, 0, 4), 2: (5.2, 10, 2, 4), 3: (5.2, 10, 0, 2)}   # x0, x1, y0, y1


def room_contains(rid, p):
    x0, x1, y0, y1 = RECT[rid]
    return x0 <= p[0] <= x1 and y0 <= p[1] <= y1


def wall_distance(p):
    for x0, x1, y0, y1 in RECT.values():
        if x0 <= p[0] <= x1 and y0 <= p[1] <= y1:
            return min(p[0] - x0, x1 - p[0], p[1] - y0, y1 - p[1])
    return 0.0


def setup():
    rooms = [Room(1, "living", None, 20.0), Room(2, "bedroom", None, 9.6), Room(3, "storage", None, 9.6)]
    devices = [Device(1, 2, NODES[1]), Device(2, 1, NODES[2]), Device(3, 3, NODES[3])]
    plan = Plan(rooms, devices, None, adjacency={1: [2, 3], 2: [1, 3], 3: [1, 2]}, plan_id="synthetic")
    hub_b = (6.0, 3.0)
    a0 = PanelAssignment(0, HUB, [1], [2])
    a1 = PanelAssignment(1, hub_b, [2, 3], [1, 3])
    loops = route_all(plan, [a0, a1], router=make_router(extra=[hub_b]))
    return plan, to_json(plan, [a0, a1], loops)


def check(data, plan, **kw):
    kw.setdefault("inside", inside)
    kw.setdefault("wall_distance", wall_distance)
    kw.setdefault("room_contains", room_contains)
    return validate(data, plan, **kw)


def rules(report):
    return {v["rule"] for v in report["violations"]}


def test_valid_design_passes_with_no_unchecked_rules():
    plan, data = setup()
    r = check(data, plan)
    assert r["valid"], r["violations"]
    assert r["unchecked"] == [] and r["hub_count"] == 2 and r["hub_lower_bound"] == 1
    assert r["metrics"]["J"] > 0


def test_missing_hooks_are_reported_not_silently_passed():
    plan, data = setup()
    r = validate(data, plan)
    assert r["valid"] and len(r["unchecked"]) == 3


def test_coverage_missing_and_duplicated_node():
    plan, data = setup()
    d = copy.deepcopy(data)
    d["hubs"][1]["assigned_nodes"].remove("N3")
    assert "coverage" in rules(check(d, plan))
    d = copy.deepcopy(data)
    d["hubs"][0]["assigned_rooms"].append("R02")          # room 2 now assigned twice
    assert "coverage" in rules(check(d, plan))


def test_capacity_nodes_and_area():
    plan, data = setup()
    d = copy.deepcopy(data)
    d["hubs"][1]["assigned_nodes"] = ["N1", "N3", "N1", "N3", "N1", "N3"]
    assert "capacity" in rules(check(d, plan))
    plan2, data2 = setup()
    plan2.rooms[1].area = 120.0                            # room 2 alone exceeds 100 m2
    assert "capacity" in rules(check(data2, plan2))


def test_zone_must_be_connected_through_doors():
    plan, data = setup()
    one = copy.deepcopy(data["hubs"][0])
    one["assigned_rooms"] = ["R01", "R02", "R03"]
    one["assigned_nodes"] = ["N2", "N1", "N3"]
    d = {**data, "hubs": [one]}
    d["hubs"][0]["closed_sequence"] = ["H1", "N2", "N1", "N3", "H1"]
    assert "zone" not in rules(check(d, plan))             # connected while the doors exist
    plan.adjacency = {1: [], 2: [], 3: []}                 # now remove every door/opening
    assert "zone" in rules(check(d, plan))


def test_ring_not_closed_or_wrong_stop():
    plan, data = setup()
    d = copy.deepcopy(data)
    d["hubs"][0]["closed_sequence"][-1] = "H2"             # ends at another hub
    assert "ring" in rules(check(d, plan))


def test_moved_node_is_caught():
    plan, data = setup()
    d = copy.deepcopy(data)
    seg = d["hubs"][0]["route_segments"][0]
    seg["polyline"][-1][0] += 0.2                          # cable no longer ends on the fixed node
    assert "node_fixed" in rules(check(d, plan))


def test_diagonal_segment_is_caught():
    plan, data = setup()
    d = copy.deepcopy(data)
    poly = d["hubs"][0]["route_segments"][0]["polyline"]
    poly.insert(1, [poly[0][0] + 0.5, poly[0][1] + 0.5])
    assert "axis_aligned" in rules(check(d, plan))


def test_cable_through_a_wall_is_caught():
    plan, data = setup()
    walled = lambda x, y: inside(x, y) & ~((x >= 7) & (x <= 7.5))   # a solid strip across room B
    r = check(data, plan, inside=walled)
    assert "free_space" in rules(r)


def test_hub_too_close_to_wall():
    plan, data = setup()
    d = copy.deepcopy(data)
    d["hubs"][0]["location"] = {"x": 0.2, "y": 1.0}
    assert "hub" in rules(check(d, plan))


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
