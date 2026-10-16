"""routing_api.py -- the function Person B asked for:  route(plan, panels) -> list[Loop]

A thin wrapper over panel_routing.route (no existing routing file is changed).

    from routing_api import route
    loops = route(plan, panels)          # one Loop per panel/hub, in the same order as `panels`

`plan`   : panel_routing.contract.Plan produced by the adapter (needs plan.free_space, in metres)
`panels` : list of PanelAssignment (panel_id, panel_xy, room_ids, device_ids), panel_xy already set
Loop     : panel_id, order, route_coords, length, bends, crossings, warnings (+ .legs, used by output.to_json)

Never guesses a hub point: a panel without panel_xy raises ValueError. Nodes that cannot be routed are
reported in Loop.warnings (never silently dropped from the JSON validator's view).
Then:  data = panel_routing.output.to_json(plan, panels, loops)
"""
from panel_routing.route import make_router, route_all


def route(plan, panels, step=0.1, seed=0, router_factory=make_router):
    panels = list(panels)
    if not panels:
        raise ValueError("route(): no panels given")
    missing = [getattr(p, "panel_id", i) for i, p in enumerate(panels) if getattr(p, "panel_xy", None) is None]
    if missing:
        raise ValueError(f"route(): panels without a hub point (panel_xy): {missing}")
    router = router_factory(plan, [tuple(p.panel_xy) for p in panels], step=step)
    return route_all(plan, panels, router=router, seed=seed)
