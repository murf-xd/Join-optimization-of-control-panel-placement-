"""STUB router (Person C replaces this).

Lets the rest of the pipeline run end to end before the real router exists. It ignores
walls, doors and windows completely: it orders each hub's nodes with nearest-neighbour +
2-opt on Manhattan distance and joins them with L-shaped legs (horizontal first).

    route(plan, panels) -> List[Loop]        <- the signature Person C's router must keep
"""
from typing import List, Sequence

from contract_merged import Loop, PanelAssignment, Plan, XY
from legacy_validator import polyline_length, ring_bends


def _manhattan(a: XY, b: XY) -> float:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _leg(a: XY, b: XY) -> List[XY]:
    """Axis-aligned path from a to b (one elbow at most), including both ends."""
    if a[0] == b[0] or a[1] == b[1]:
        return [a, b]
    return [a, (b[0], a[1]), b]


def _tour_cost(hub: XY, pts: Sequence[XY]) -> float:
    stops = [hub, *pts, hub]
    return sum(_manhattan(a, b) for a, b in zip(stops, stops[1:]))


def _order(hub: XY, ids: List[int], xy) -> List[int]:
    """Nearest neighbour from the hub, then 2-opt until no swap helps."""
    todo = sorted(ids)
    tour: List[int] = []
    here = hub
    while todo:
        nxt = min(todo, key=lambda d: (_manhattan(here, xy[d]), d))
        tour.append(nxt)
        todo.remove(nxt)
        here = xy[nxt]
    improved = True
    while improved:
        improved = False
        for i in range(len(tour) - 1):
            for j in range(i + 1, len(tour)):
                cand = tour[:i] + tour[i:j + 1][::-1] + tour[j + 1:]
                if (_tour_cost(hub, [xy[d] for d in cand]) + 1e-9
                        < _tour_cost(hub, [xy[d] for d in tour])):
                    tour, improved = cand, True
    return tour


def route(plan: Plan, panels: Sequence[PanelAssignment]) -> List[Loop]:
    loops: List[Loop] = []
    for p in panels:
        xy = {d: plan.device_by_id(d).xy for d in p.device_ids}
        order = _order(p.panel_xy, list(p.device_ids), xy)
        stops = [p.panel_xy] + [xy[d] for d in order] + [p.panel_xy]
        coords: List[XY] = [stops[0]]
        for a, b in zip(stops, stops[1:]):
            coords += _leg(a, b)[1:]
        loops.append(Loop(panel_id=p.panel_id, order=order, route_coords=coords,
                          length=polyline_length(coords), bends=ring_bends(coords),
                          warnings=["stub router: walls and doors ignored"]))
    return loops
