"""Run with:  python3 tests/test_all.py   (no shapely needed; rooms are plain rectangles)."""
import json
import math
import random
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from panel_routing.contract import Device, PanelAssignment, Plan, Room
from panel_routing.grid_router import GridRouter
from panel_routing.metrics import score, score_json
from panel_routing.output import to_json
from panel_routing.route import route_all
from panel_routing.tsp import solve_tour, tour_length


# ------------------------------------------------------------------ TSP
def dist_matrix(pts):
    return np.array([[math.dist(a, b) for b in pts] for a in pts])


def held_karp(D):
    n = len(D)
    full = 1 << (n - 1)
    dp = [[math.inf] * (n - 1) for _ in range(full)]
    for j in range(n - 1):
        dp[1 << j][j] = D[0][j + 1]
    for mask in range(full):
        for j in range(n - 1):
            if dp[mask][j] == math.inf:
                continue
            for k in range(n - 1):
                if not mask & (1 << k):
                    v = dp[mask][j] + D[j + 1][k + 1]
                    if v < dp[mask | (1 << k)][k]:
                        dp[mask | (1 << k)][k] = v
    return min(dp[full - 1][j] + D[j + 1][0] for j in range(n - 1))


def test_tsp():
    rng = random.Random(1)
    for n in (2, 3, 5, 6, 8, 10, 12):
        for _ in range(4):
            D = dist_matrix([(rng.uniform(0, 20), rng.uniform(0, 15)) for _ in range(n)])
            order = solve_tour(D)
            assert order[0] == 0 and sorted(order) == list(range(n))
            if n >= 4:
                assert tour_length(order, D) <= held_karp(D) * 1.02 + 1e-9


# ------------------------------------------------------------------ metrics (slide 7 definitions)
def test_metrics_square_ring():
    legs = [[(0, 0), (4, 0)], [(4, 0), (4, 3)], [(4, 3), (0, 3), (0, 0)]]
    s = score([legs])
    assert abs(s["L"] - 14) < 1e-9 and s["B"] == 4 and s["O"] == 0 and s["X"] == 0
    assert abs(s["J"] - 16) < 1e-9


def test_metrics_retrace_counts_as_overlap_parallel_does_not():
    retrace = [[(0, 0), (3, 0)], [(3, 0), (0, 0)]]
    s = score([retrace])
    assert abs(s["L"] - 6) < 1e-9 and abs(s["O"] - 3) < 1e-9 and s["B"] == 2
    lanes = [[(0, 0), (3, 0)], [(3, 0), (3, 0.1), (0, 0.1), (0, 0)]]
    s = score([lanes])
    assert s["O"] == 0 and abs(s["L"] - 6.2) < 1e-9


def test_metrics_crossings_counted_once_per_point_and_not_at_nodes():
    square = [[(0, 0), (4, 0)], [(4, 0), (4, 4)], [(4, 4), (0, 4), (0, 0)]]
    spoke = [[(2, -1), (2, 5)], [(2, 5), (2, -1)]]
    assert score([square, spoke])["X"] == 2           # crosses y=0 and y=4 at x=2
    touching = [[(2, 0), (2, 5)], [(2, 5), (2, 0)]]    # ring has a node ON the square's edge
    assert score([square, touching], [(2, 0), (2, 5)])["X"] == 1  # only the y=4 crossing


# ------------------------------------------------------------------ grid router
# Two rooms and a door:  A = [0,5]x[0,4],  B = [5.2,10]x[0,4],  door = [5,5.2]x[1.5,2.5]
def inside(x, y):
    a = (x >= 0) & (x <= 5) & (y >= 0) & (y <= 4)
    b = (x >= 5.2) & (x <= 10) & (y >= 0) & (y <= 4)
    d = (x >= 5) & (x <= 5.2) & (y >= 1.5) & (y <= 2.5)
    return a | b | d


HUB = (1.0, 1.0)
NODES = {1: (8.03, 3.07), 2: (2.5, 3.5), 3: (9.0, 0.5)}


def make_plan():
    rooms = [Room(1, "living", None, 20.0), Room(2, "bedroom", None, 19.2)]
    devices = [Device(i, 2 if i != 2 else 1, xy) for i, xy in NODES.items()]
    return Plan(rooms, devices, None, plan_id="synthetic")


def make_router(extra=()):
    pts = list(NODES.values()) + [HUB] + list(extra)
    return GridRouter(inside, (0, 0, 10, 4), pts, step=0.1)


def assert_valid_polyline(poly):
    for a, b in zip(poly, poly[1:]):
        assert abs(a[0] - b[0]) < 1e-9 or abs(a[1] - b[1]) < 1e-9, f"diagonal {a}->{b}"
        n = max(2, int(math.dist(a, b) / 0.01))
        xs = np.linspace(a[0], b[0], n)
        ys = np.linspace(a[1], b[1], n)
        assert inside(xs, ys).all(), f"segment {a}->{b} leaves the free space"


def test_ring_is_valid_closed_axis_aligned_and_uses_the_door():
    plan = make_plan()
    a = PanelAssignment(0, HUB, [1, 2], [1, 2, 3])
    (loop,) = route_all(plan, [a], router=make_router())
    assert not loop.warnings, loop.warnings
    assert sorted(loop.order) == [1, 2, 3]                       # every node exactly once
    assert loop.route_coords[0] == loop.route_coords[-1] == HUB  # closed at its own hub
    assert_valid_polyline(loop.route_coords)                     # never leaves free space, no diagonals
    crossed_wall = [(p, q) for p, q in zip(loop.route_coords, loop.route_coords[1:])
                    if min(p[0], q[0]) < 5.1 < max(p[0], q[0])]
    assert crossed_wall and all(1.5 <= p[1] <= 2.5 for p, q in crossed_wall)  # only through the door


def test_single_door_room_uses_parallel_lanes_not_a_retrace():
    plan = make_plan()
    a = PanelAssignment(0, HUB, [2], [3])                        # only the far node in room B
    (loop,) = route_all(plan, [a], router=make_router())
    assert_valid_polyline(loop.route_coords)
    s = score([loop.legs])
    assert s["O"] == 0, s                                        # out and back on different lines
    one_way = 8.0 + 0.5 + 1.0              # 8 m across, 0.5 m up to the door row, 1.0 m down to the node
    assert 2 * one_way <= s["L"] < 2 * one_way + 1.0             # lanes cost under 1 m extra


def test_unreachable_node_gives_warning_not_crash():
    plan = make_plan()
    plan.devices.append(Device(9, 1, (50.0, 50.0)))
    plan.__post_init__()
    a = PanelAssignment(0, HUB, [1], [1, 2, 9])
    (loop,) = route_all(plan, [a], router=make_router(extra=[(50.0, 50.0)]))
    assert sorted(loop.order) == [1, 2] and any("node 9" in w for w in loop.warnings)


def test_two_hubs_and_json_roundtrip():
    plan = make_plan()
    hub_b = (6.0, 1.0)
    a0 = PanelAssignment(0, HUB, [1], [2])
    a1 = PanelAssignment(1, hub_b, [2], [1, 3])
    loops = route_all(plan, [a0, a1], router=make_router(extra=[hub_b]))
    data = to_json(plan, [a0, a1], loops)
    json.dumps(data)
    assert [h["hub_id"] for h in data["hubs"]] == ["H1", "H2"]
    assert data["hubs"][0]["closed_sequence"] == ["H1", "N2", "H1"]
    for h in data["hubs"]:
        assert h["closed_sequence"][0] == h["closed_sequence"][-1] == h["hub_id"]
        assert len(h["route_segments"]) == len(h["closed_sequence"]) - 1
        for seg in h["route_segments"]:
            assert_valid_polyline([tuple(p) for p in seg["polyline"]])
    s = score_json(data)                                         # what the organisers' checker does
    assert s["H"] == 2 and s["J"] > 0 and s["non_axis_segments"] == 0
    assert abs(s["L"] - data["reported_metrics"]["total_length_m"]) < 1e-3


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
