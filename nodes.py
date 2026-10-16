"""nodes.py -- node (device) generation, one node per eligible room.

Organiser clarification: teams generate node coordinates themselves, inside eligible rooms and at least
0.5 m from adjacent walls. Our assumption (to be confirmed):

    node = pole of inaccessibility of the part of the room that is (a) inside free_space and
           (b) at least `clearance_m` from walls and windows.

Why: inside the room by construction, the largest clearance, deterministic (same plan, same node),
not biased towards doors. A room with no such point is REPORTED (NodeGenerationError), never forced
or silently dropped; what to do with it (small-room rule) is a team/organiser decision.

Needs shapely and a plan from the adapter (metres): plan.free_space, plan.geo["walls"], plan.geo["windows"].
"""
from panel_routing.contract import Device

CLEARANCE_M = 0.5
SAFETY_M = 0.02          # search for points slightly beyond the limit so the result passes the check with margin
MIN_PART_AREA_M2 = 1e-4


class NodeGenerationError(Exception):
    def __init__(self, failures):
        self.failures = failures        # list of (room_id, reason)
        super().__init__("; ".join(f"room {r}: {why}" for r, why in failures))


def _polygons(geom):
    return [g for g in getattr(geom, "geoms", [geom]) if g.geom_type == "Polygon" and g.area > MIN_PART_AREA_M2]


def generate_nodes(plan, clearance_m=CLEARANCE_M):
    """Return (devices, report). Raises NodeGenerationError listing every room that has no valid point."""
    from shapely.geometry import Point
    from shapely.ops import polylabel

    free = plan.free_space
    blocked = plan.geo["walls"].union(plan.geo["windows"])
    limit = blocked.buffer(clearance_m + SAFETY_M)
    devices, report, failures = [], [], []
    for k, room in enumerate(plan.eligible_rooms, start=1):
        region = room.polygon.intersection(free)
        if region.is_empty:
            failures.append((room.id, "room has no free space"))
            continue
        allowed = region.difference(limit)
        parts = _polygons(allowed)
        if not parts:
            best = max((p.area for p in _polygons(region)), default=0.0)
            failures.append((room.id, f"no point at least {clearance_m} m from walls and windows "
                                      f"(free-space area {best:.2f} m2)"))
            continue
        part = max(parts, key=lambda g: (g.area, g.bounds))     # deterministic tie-break
        p = polylabel(part, tolerance=0.01)
        d = blocked.distance(Point(p.x, p.y))
        if d < clearance_m - 1e-6 or not free.covers(Point(p.x, p.y)) or not room.polygon.covers(Point(p.x, p.y)):
            failures.append((room.id, f"generated point failed its own check (clearance {d:.3f} m)"))
            continue
        devices.append(Device(k, room.id, (float(p.x), float(p.y))))
        report.append({"room_id": room.id, "node_id": k, "clearance_m": round(d, 3)})
    if failures:
        raise NodeGenerationError(failures)
    return devices, report
