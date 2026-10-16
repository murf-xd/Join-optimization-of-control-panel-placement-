"""contract_v2.py -- shared data contract for Person A (geometry), B (assignment) and C (routing).

Replaces contract_merged.py. Keep this file IDENTICAL across the team; change it only by agreement.

    A produces  -> Plan                       (adapter.to_plan)
    B consumes Plan, produces -> hub assignments (zones, hub points)
    C consumes Plan + assignments, produces -> rings (polylines)

UNITS: every geometry in a Plan is in "PLAN METRES": ResPlan drawing units divided by the plan's scale
(scale = sqrt(inner.area / area)). Origin is the drawing origin, y is NOT flipped. The conversion to the
organisers' output frame ("origin lower-left, y up") is ONE function at the output edge (see adapter.py,
to_output_xy) and is still waiting on the organisers' answer. Nobody else should shift or flip anything.

IDS: strings. Rooms like "bedroom_0", nodes "N1".., gates "G0"/"P0". The organisers' own ids (e.g. "R05")
go into Room.source_id once their input JSON is loaded.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from shapely.geometry import Point

XY = Tuple[float, float]

# Problem rules, kept here so every module uses the same numbers (PPTX statement).
MAX_HUB_AREA_M2 = 100.0        # m^2 of assigned eligible-room area per hub
MAX_NODES_PER_HUB = 5          # nodes per hub (the OLD text said 20; keep this a single constant)
HUB_CLEARANCE_M = 0.5          # hubs and nodes must be >= 0.5 m from walls
ELIGIBLE_TYPES = ("living", "bedroom", "kitchen", "storage")


@dataclass
class Room:
    id: str
    type: str                  # living, bedroom, kitchen, storage, bathroom, stair, balcony
    polygon: Any               # shapely Polygon, plan metres
    area_m2: float
    eligible: bool             # gets a node and counts toward hub capacity
    walkable: bool             # False only for balcony (external)
    hub_zone: Any = None       # shapely (Multi)Polygon where a hub may sit (>= 0.5 m from walls); EMPTY if none
    source_id: Optional[str] = None


@dataclass
class Gate:
    id: str
    kind: str                  # "door" or "open_passage"
    segment: Any               # shapely LineString across the opening (plan metres)
    room_a: str                # room id, or "EXTERIOR"
    room_b: str
    width_m: float
    usable: bool = True        # False = leads outside (balcony / front door): never route through it
    clear_width_m: Optional[float] = None   # width of the crossing that is really free space (None = not measured)
    blocked: bool = False      # True = a window/obstacle covers the gate, so it was switched off


@dataclass
class Node:
    id: str                    # "N1", ...
    room_id: str
    xy: XY                     # plan metres
    source: str = "placeholder"   # "placeholder" until the organisers' fixed points are loaded


@dataclass
class Plan:
    plan_id: Any
    scale: float                       # drawing units per metre (for reference only)
    rooms: List[Room]
    nodes: List[Node]
    gates: List[Gate]
    # room_id -> ids of rooms joined by a USABLE gate. Includes pass-through rooms (bathroom, stair).
    # Plain dict of lists, symmetric, never None. Balconies are not in it.
    adjacency: Dict[str, List[str]]
    free_space: Any                    # shapely (Multi)Polygon: where a cable may run (EMPTY polygon on failure)
    inner: Any                         # building interior boundary
    walls: Any
    windows: Any
    obstacles: Any                     # walls U windows (for clearance checks)
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def __post_init__(self):
        self._rooms = {r.id: r for r in self.rooms}
        self._nodes = {n.id: n for n in self.nodes}

    def room(self, room_id: str) -> Room:
        return self._rooms[room_id]

    def node(self, node_id: str) -> Node:
        return self._nodes[node_id]

    @property
    def eligible_rooms(self) -> List[Room]:
        return [r for r in self.rooms if r.eligible]

    @property
    def routing_gates(self) -> List[Gate]:
        return [g for g in self.gates if g.usable]

    def node_of_room(self, room_id: str) -> Optional[Node]:
        return next((n for n in self.nodes if n.room_id == room_id), None)

    def gates_between(self, a: str, b: str) -> List[Gate]:
        return [g for g in self.routing_gates if {g.room_a, g.room_b} == {a, b}]


def is_contiguous(plan: Plan, room_ids, via_passthrough: bool = False) -> bool:
    """Are these rooms connected through usable gates?

    via_passthrough=False (strict): the path may only use the listed rooms.
    via_passthrough=True: the path may also cross bathrooms/stairs (pass-through rooms).
    Which one the organisers mean is an OPEN QUESTION; B should make it one switch."""
    ids = set(room_ids)
    if len(ids) <= 1:
        return True
    allowed = set(ids)
    if via_passthrough:
        allowed |= {r.id for r in plan.rooms if r.walkable and not r.eligible}
    seen, stack = set(), [sorted(ids)[0]]
    while stack:
        x = stack.pop()
        if x in seen:
            continue
        seen.add(x)
        stack.extend(n for n in plan.adjacency.get(x, []) if n in allowed)
    return ids <= seen


def point_problems(plan: Plan, xy: XY, tol: float = 1e-6) -> List[str]:
    """Why a node/hub point is NOT allowed (empty list = fine): outside free space, or < 0.5 m from walls."""
    p = Point(xy)
    out = []
    if plan.free_space.is_empty or not plan.free_space.buffer(tol).contains(p):
        out.append("outside free space")
    if not plan.obstacles.is_empty and plan.obstacles.distance(p) < HUB_CLEARANCE_M - tol:
        out.append(f"closer than {HUB_CLEARANCE_M} m to a wall or window")
    return out
