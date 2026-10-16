"""Shared data contract between Person A (geometry), B (assignment) and C (routing).

Keep this file identical across the team. Coordinates are plain (x, y) float tuples
in the same units as the ResPlan geometry (metres).

    A produces  -> Plan
    B consumes Plan, produces -> List[PanelAssignment]
    C consumes Plan + assignments, produces -> List[Loop]
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

XY = Tuple[float, float]

# Problem rules, kept here so every module uses the same numbers.
MAX_PANEL_AREA = 100.0      # m^2 of assigned eligible-room area per panel
MAX_PANEL_DEVICES = 5       # nodes per hub (problem statement slide 1: was 20, now 5)
ELIGIBLE_TYPES = {"living", "bedroom", "kitchen", "storage"}


@dataclass
class Room:
    id: int
    type: str            # living, bedroom, kitchen, storage, hallway, bathroom, ...
    polygon: Any         # shapely Polygon
    area: float          # m^2

    @property
    def eligible(self) -> bool:
        """Eligible rooms get a device and count toward panel capacity."""
        return self.type in ELIGIBLE_TYPES


@dataclass
class Device:
    id: int
    room_id: int
    xy: XY


@dataclass
class Plan:
    rooms: List[Room]
    devices: List[Device]
    free_space: Any                                   # shapely (Multi)Polygon: where a cable may run
    # room_id -> ids of rooms joined by a door/opening. Includes pass-through rooms
    # (hallway, bathroom). Always a dict, never None, so B and C need no None checks.
    adjacency: Dict[int, List[int]] = field(default_factory=dict)
    plan_id: str = "unknown"

    def __post_init__(self):
        self._rooms = {r.id: r for r in self.rooms}
        self._devices = {d.id: d for d in self.devices}

    def room_by_id(self, room_id: int) -> Room:
        return self._rooms[room_id]

    def device_by_id(self, device_id: int) -> Device:
        return self._devices[device_id]

    @property
    def eligible_rooms(self) -> List[Room]:
        return [r for r in self.rooms if r.eligible]


@dataclass
class PanelAssignment:
    panel_id: int
    panel_xy: XY
    room_ids: List[int]                               # eligible rooms only
    device_ids: List[int]
    warnings: List[str] = field(default_factory=list)  # e.g. "room 7 exceeds 100 m2"


@dataclass
class Loop:
    panel_id: int
    order: List[int]                 # device ids in visit order (panel excluded)
    route_coords: List[XY]           # closed polyline: panel -> ... -> panel
    length: float = 0.0
    bends: int = 0
    crossings: int = 0               # crossings with other panels' loops
    warnings: List[str] = field(default_factory=list)


# Conventions (agreed in hour 0-1):
#   1. adjacency includes pass-through rooms; PanelAssignment.room_ids does not.
#   2. adjacency is a plain dict of lists, symmetric (if a lists b, b lists a).
#   3. ids are ints, as in ResPlan; panel_id starts at 0.
#   4. Any failure is reported through `warnings`, never by crashing.
