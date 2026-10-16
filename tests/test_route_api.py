"""route(plan, panels) -> list[Loop] on the SYNTHETIC demo layout (no shapely needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from demo_viz import ASSIGN, HUBS
from panel_routing.contract import PanelAssignment
from panel_routing.output import to_json
from routing_api import route
from tests.test_run import make_plan, router_factory


def panels(hubs=HUBS):
    return [PanelAssignment(k, hubs[k], r, n) for k, (r, n) in enumerate(ASSIGN)]


def test_route_returns_one_loop_per_panel_in_order():
    plan, ps = make_plan(), panels()
    loops = route(plan, ps, router_factory=router_factory)
    assert [l.panel_id for l in loops] == [p.panel_id for p in ps]
    for l, p in zip(loops, ps):
        assert sorted(l.order) == sorted(p.device_ids) and l.length > 0 and not l.warnings


def test_loops_feed_to_json_with_closed_rings():
    plan, ps = make_plan(), panels()
    data = to_json(plan, ps, route(plan, ps, router_factory=router_factory))
    for h in data["hubs"]:
        assert h["closed_sequence"][0] == h["closed_sequence"][-1] == h["hub_id"]


def test_missing_hub_point_is_an_error_not_a_guess():
    plan = make_plan()
    ps = panels([None, HUBS[1]])
    try:
        route(plan, ps, router_factory=router_factory)
    except ValueError as e:
        assert "panel_xy" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_no_panels_is_an_error():
    try:
        route(make_plan(), [], router_factory=router_factory)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
