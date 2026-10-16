"""Person B: glue between grouping (assign.py), routing (Person C) and scoring (validator.py).

    solve(plan, route) -> Solution

`route` is any function with the signature route(plan, panels) -> List[Loop]. Today that is
stub_route.route; swap in Person C's router and nothing else changes.

What it does that assign() alone cannot:
  1. Route EVERY candidate grouping (all with the fewest hubs) and keep the cheapest.
  2. Try every node of a group as the hub spot and keep the cheapest ring.
Final choice follows the ranking in the problem statement: fewest hubs, then lowest J,
then the smaller area gap between hubs. Invalid designs always lose to valid ones.
"""
from dataclasses import dataclass, field, replace
from typing import Callable, Dict, Iterable, List, Optional, Sequence

from legacy_assign import PASS_THROUGH_TYPES, assign_candidates
from contract_merged import Loop, PanelAssignment, Plan
from legacy_validator import metrics, score

RouteFn = Callable[[Plan, Sequence[PanelAssignment]], List[Loop]]


@dataclass
class Solution:
    panels: List[PanelAssignment]
    loops: List[Loop] = field(default_factory=list)
    result: Dict[str, object] = field(default_factory=dict)      # score(): valid, problems, H, L, X, O, B, J


def _ring_cost(plan: Plan, panel: PanelAssignment, route: RouteFn) -> float:
    """J of this hub's ring on its own (crossings with other rings are not known yet)."""
    return metrics(plan, [panel], route(plan, [panel]))["J"]


def refine_hubs(plan: Plan, panels: Sequence[PanelAssignment], route: RouteFn) -> List[PanelAssignment]:
    """Move each hub to whichever of its group's node points gives the cheapest ring.

    Staying on a node keeps the hub inside one of its rooms, away from walls (nodes sit
    0.5 m from walls), so the hub-point rule keeps holding."""
    out: List[PanelAssignment] = []
    for p in panels:
        options = sorted({(plan.device_by_id(d).xy, d) for d in p.device_ids}, key=lambda t: t[1])
        best = min(((_ring_cost(plan, replace(p, panel_xy=xy), route), d, xy) for xy, d in options),
                   default=None)
        out.append(replace(p, panel_xy=best[2]) if best else p)
    return out


def solve(plan: Plan, route: Optional[RouteFn] = None, limit: int = 20,
          pass_through: Iterable[str] = PASS_THROUGH_TYPES, refine: bool = True,
          n_restarts: int = 30, seed: int = 0) -> Solution:
    """Best design found. With route=None only the grouping is returned (no rings, no score)."""
    pass_through = tuple(pass_through)
    candidates = assign_candidates(plan, limit=limit, n_restarts=n_restarts, seed=seed,
                                   pass_through=pass_through)
    if not candidates:
        return Solution(panels=[], loops=[], result={"valid": True, "problems": [], "H": 0, "L": 0.0,
                                                     "X": 0, "O": 0.0, "B": 0, "J": 0.0, "area_gap": 0.0})
    if route is None:
        return Solution(panels=candidates[0])

    best_key, best = None, None
    for panels in candidates:
        if refine:
            panels = refine_hubs(plan, panels, route)
        loops = route(plan, panels)
        result = score(plan, panels, loops, pass_through)
        key = (not result["valid"], result["H"], round(result["J"], 6), round(result["area_gap"], 6))
        if best_key is None or key < best_key:
            best_key, best = key, Solution(panels=panels, loops=loops, result=result)
    return best
