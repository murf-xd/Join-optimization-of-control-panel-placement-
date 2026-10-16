"""Glue: hub assignments -> node order (TSP) -> closed axis-aligned rings."""
import math

import numpy as np

from .contract import Loop, PanelAssignment, Plan
from .grid_router import GridRouter, inside_from_shapely
from .metrics import ring_bends, ring_length, ring_vertices, score
from .tsp import solve_tour


def make_router(plan: Plan, hub_points=(), step=0.1, **kw):
    """Grid router over plan.free_space (shapely). Hubs and nodes become exact grid points."""
    x0, y0, x1, y1 = plan.free_space.bounds
    terminals = [tuple(d.xy) for d in plan.devices] + [tuple(p) for p in hub_points]
    return GridRouter(inside_from_shapely(plan.free_space), (x0, y0, x1, y1),
                      terminals, step=step, **kw)


def _empty(a, hub, warnings):
    return Loop(a.panel_id, [], [hub], 0.0, 0, 0, warnings)


def route_hub(router, a: PanelAssignment, plan: Plan, usage, seed=0) -> Loop:
    """One closed ring per hub. Never raises: problems go to Loop.warnings (convention 4)."""
    hub = (float(a.panel_xy[0]), float(a.panel_xy[1]))
    warnings = []
    if not router.is_free(hub):
        return _empty(a, hub, [f"hub {a.panel_id} at {hub} is not inside the free space"])

    devices = []
    for did in a.device_ids:
        d = plan.device_by_id(did)
        if router.is_free(d.xy):
            devices.append(d)
        else:
            warnings.append(f"node {d.id} at {tuple(d.xy)} is outside the free space; skipped")
    if not devices:
        return _empty(a, hub, warnings)

    pts = [hub] + [(float(d.xy[0]), float(d.xy[1])) for d in devices]
    D = router.distance_matrix(pts)
    keep = [0] + [k for k in range(1, len(pts)) if math.isfinite(D[0, k])]
    for k in range(1, len(pts)):
        if k not in keep:
            warnings.append(f"node {devices[k - 1].id} is not reachable from hub {a.panel_id} "
                            f"through doors/openings; skipped")
    if len(keep) == 1:
        return _empty(a, hub, warnings)
    pts = [pts[k] for k in keep]
    devices = [devices[k - 1] for k in keep[1:]]
    D = D[np.ix_(keep, keep)]

    tour = solve_tour(D, seed=seed)        # indices into pts, starts at 0
    try:
        legs = router.route_ring(pts, tour, usage)
    except ValueError as e:
        warnings.append(f"routing failed: {e}")
        return _empty(a, hub, warnings)

    coords = list(legs[0])
    for leg in legs[1:]:
        coords.extend(leg[1:])
    verts = ring_vertices(legs)
    loop = Loop(
        panel_id=a.panel_id,
        order=[devices[i - 1].id for i in tour[1:]],
        route_coords=coords,
        length=ring_length(verts),
        bends=ring_bends(verts),
        warnings=warnings,
    )
    loop.legs = legs                       # per-leg polylines, used by output.py
    return loop


def route_all(plan: Plan, assignments, router=None, step=0.1, seed=0):
    """Route every hub's ring, sharing one cable record so rings avoid each other."""
    if router is None:
        router = make_router(plan, [a.panel_xy for a in assignments], step=step)
    usage = router.new_usage()
    loops = [route_hub(router, a, plan, usage, seed) for a in assignments]
    rings = [getattr(l, "legs", [l.route_coords]) for l in loops]
    s = score(rings)
    for l, r in zip(loops, s["per_ring"]):
        l.crossings = r["X"]
    return loops
