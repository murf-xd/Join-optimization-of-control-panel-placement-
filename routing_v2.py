"""Adapter between Person B's v2 contract and Person C's existing grid router."""
import sys
from pathlib import Path

B_PACKAGE = Path.home() / "Downloads" / "person_b_staging" / "person_b_new"
sys.path.insert(0, str(B_PACKAGE))

from v2_bridge import convert, to_old, Loop as V2Loop
from panel_routing.contract import (
    Plan as CPlan,
    Room as CRoom,
    Device as CDevice,
    PanelAssignment as CPanelAssignment,
)
from panel_routing.route import route_all


def route(plan, panels, step=0.1, seed=0):
    """Route v2 assignments with C's grid router; preserve public string IDs."""
    old_plan, room_map, node_map, reverse_rooms, reverse_nodes = convert(plan)

    rooms = [
        CRoom(id=r.id, type=r.type, polygon=r.polygon, area=r.area)
        for r in old_plan.rooms
    ]
    devices = [
        CDevice(id=d.id, room_id=d.room_id, xy=tuple(d.xy))
        for d in old_plan.devices
    ]
    c_plan = CPlan(
        rooms=rooms,
        devices=devices,
        free_space=old_plan.free_space,
        adjacency=old_plan.adjacency,
        plan_id=str(old_plan.plan_id),
    )

    old_panels = [to_old(p, room_map, node_map) for p in panels]
    c_panels = [
        CPanelAssignment(
            panel_id=p.panel_id,
            panel_xy=tuple(p.panel_xy),
            room_ids=list(p.room_ids),
            device_ids=list(p.device_ids),
            warnings=list(p.warnings),
        )
        for p in old_panels
    ]

    loops = route_all(c_plan, c_panels, step=step, seed=seed)

    return [
        V2Loop(
            panel_id="H" + str(loop.panel_id + 1),
            order=[reverse_nodes[n] for n in loop.order],
            route_coords=list(loop.route_coords),
            warnings=list(loop.warnings),
        )
        for loop in loops
    ]
