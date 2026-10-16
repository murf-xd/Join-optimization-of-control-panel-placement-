"""Tests for run.py's pipeline core on the SYNTHETIC demo layout (no shapely, no ResPlan)."""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from demo_viz import (ADJACENCY, ASSIGN, HUBS, NODE_ROOM, NODES, ROOMS, inside, room_contains,
                      wall_distance)
from panel_routing.contract import Device, Plan, Room
from panel_routing.grid_router import GridRouter
from run import PipelineError, check_nodes, official_devices, solve

HOOKS = dict(inside=inside, wall_distance=wall_distance, room_contains=room_contains)


class Box:
    """Stand-in polygon: only .bounds is needed by hub placement."""

    def __init__(self, x0, y0, x1, y1):
        self.bounds = (x0, y0, x1, y1)


def router_factory(plan, hub_points, step=0.1):
    pts = [tuple(d.xy) for d in plan.devices] + list(hub_points)
    return GridRouter(inside, (0.0, 0.0, 17.0, 11.2), pts, step=step)


def make_plan(with_devices=True):
    rooms = [Room(i, t, Box(x0, y0, x1, y1), (x1 - x0) * (y1 - y0)) for i, (t, x0, x1, y0, y1) in ROOMS.items()]
    devices = [Device(i, NODE_ROOM[i], xy) for i, xy in NODES.items()] if with_devices else []
    return Plan(rooms, devices, None, adjacency=ADJACENCY, plan_id="SYNTHETIC_TEST")


def assign_fn(hubs):
    def f(plan):
        return [SimpleNamespace(panel_id=k, panel_xy=hubs[k], room_ids=r, device_ids=n)
                for k, (r, n) in enumerate(ASSIGN)]
    return f


def test_hub_placement_fills_missing_hubs_and_design_validates():
    plan = make_plan()
    res = solve(plan, assign_fn([None, None]), HOOKS, router_factory)
    assert res["report"]["valid"], res["report"]["violations"]
    for a in res["assignments"]:
        assert wall_distance(a.panel_xy) >= 0.5
        assert any(room_contains(r, a.panel_xy) for r in a.room_ids)
        assert all(abs(a.panel_xy[0] - plan.device_by_id(d).xy[0]) + abs(a.panel_xy[1] - plan.device_by_id(d).xy[1]) >= 0.5
                   for d in a.device_ids)
        assert any("hub point set by run.py" in w for w in a.warnings)


def test_valid_hubs_from_assignment_are_kept():
    plan = make_plan()
    res = solve(plan, assign_fn(HUBS), HOOKS, router_factory)
    assert [tuple(a.panel_xy) for a in res["assignments"]] == [tuple(h) for h in HUBS]
    assert res["report"]["valid"]


def test_hub_too_close_to_a_wall_is_replaced():
    plan = make_plan()
    res = solve(plan, assign_fn([(0.2, 3.0), HUBS[1]]), HOOKS, router_factory)
    assert wall_distance(res["assignments"][0].panel_xy) >= 0.5
    assert tuple(res["assignments"][1].panel_xy) == tuple(HUBS[1])


def test_empty_devices_stop_before_assignment():
    plan = make_plan(with_devices=False)

    def must_not_run(_):
        raise AssertionError("assign() must not be called for a plan without nodes")

    try:
        solve(plan, must_not_run, HOOKS, router_factory)
    except PipelineError as e:
        assert "no devices" in str(e)
    else:
        raise AssertionError("expected PipelineError")


def test_room_without_a_node_is_an_error():
    plan = make_plan()
    plan.devices.pop()
    plan.__post_init__()
    try:
        check_nodes(plan)
    except PipelineError as e:
        assert "R05" in str(e)
    else:
        raise AssertionError("expected PipelineError")


def test_official_mode_refuses_to_invent_nodes():
    try:
        official_devices(make_plan(with_devices=False))
    except PipelineError as e:
        assert "not available" in str(e) and "--dev-probe-nodes" in str(e)
    else:
        raise AssertionError("expected PipelineError")


def test_bad_assignment_output_is_a_clear_error():
    plan = make_plan()
    for bad in (None, [], [SimpleNamespace(panel_id=0)]):
        try:
            solve(plan, lambda p, b=bad: b, HOOKS, router_factory)
        except PipelineError:
            continue
        raise AssertionError(f"expected PipelineError for {bad!r}")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
