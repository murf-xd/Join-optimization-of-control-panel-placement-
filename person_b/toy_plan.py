"""Toy houses for testing Person B's code without waiting for Person A.

build_plan() makes a Plan in exactly the shape the contract describes, from a
simple list of rooms and a list of doors. No shapely needed.
"""
from typing import Dict, List, Optional, Tuple

from contract_merged import Device, Plan, Room, XY


def build_plan(
    room_specs: List[Tuple[int, str, float]],      # (room_id, type, area_m2)
    edges: List[Tuple[int, int]],                  # (room_a, room_b) joined by a door
    xy: Optional[Dict[int, XY]] = None,            # device location per room id
    plan_id: str = "toy",
) -> Plan:
    rooms = [Room(id=i, type=t, polygon=None, area=a) for i, t, a in room_specs]

    adjacency: Dict[int, List[int]] = {r.id: [] for r in rooms}
    for a, b in edges:                              # keep it symmetric
        adjacency[a].append(b)
        adjacency[b].append(a)

    xy = xy or {}
    devices = [
        Device(id=100 + r.id, room_id=r.id, xy=xy.get(r.id, (4.0 * r.id, 0.0)))
        for r in rooms
        if r.eligible
    ]
    return Plan(rooms=rooms, devices=devices, free_space=None,
                adjacency=adjacency, plan_id=plan_id)


def make_toy_plan() -> Plan:
    """An 11-room house. Rooms 6 (hallway) and 7 (bathroom) get no device.

        2 - 1 - 8 - 9
            |   |
            6   10 - 11
          / | \\
         3  4  5       (7 = bathroom, hangs off the hallway 6)
    Eligible area = 158 m2, so at least 2 panels are needed.
    """
    specs = [
        (1, "living", 30), (2, "kitchen", 15), (3, "bedroom", 14),
        (4, "bedroom", 12), (5, "storage", 6), (6, "hallway", 8),
        (7, "bathroom", 5), (8, "living", 35), (9, "bedroom", 20),
        (10, "kitchen", 18), (11, "storage", 8),
    ]
    edges = [(1, 2), (1, 6), (6, 3), (6, 4), (6, 5), (6, 7),
             (1, 8), (8, 9), (8, 10), (10, 11)]
    xy = {1: (5, 5), 2: (12, 5), 3: (5, 12), 4: (9, 12), 5: (13, 12),
          8: (20, 5), 9: (27, 5), 10: (20, 12), 11: (27, 12)}
    return build_plan(specs, edges, xy, plan_id="toy_house")
