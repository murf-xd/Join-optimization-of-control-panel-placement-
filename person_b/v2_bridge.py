"""ID-preserving bridge: v2 public API, legacy search/metric implementation internally."""
from dataclasses import dataclass, field
from typing import List
from shapely.geometry import Point
from contract_v2 import point_problems
import contract_merged as old

@dataclass
class PanelAssignment:
    panel_id: str
    panel_xy: tuple
    room_ids: List[str]
    node_ids: List[str]
    warnings: List[str] = field(default_factory=list)
    @property
    def device_ids(self):
        return self.node_ids
    @property
    def hub_id(self):
        return self.panel_id
    @property
    def assigned_rooms(self):
        return self.room_ids
    @property
    def assigned_nodes(self):
        return self.node_ids

@dataclass
class Loop:
    panel_id: str
    order: list
    route_coords: list
    warnings: list = field(default_factory=list)

def convert(plan):
    rooms = {r.id: i for i,r in enumerate(plan.rooms)}
    nodes = {n.id: i for i,n in enumerate(plan.nodes)}
    rev_rooms = {i:k for k,i in rooms.items()}
    rev_nodes = {i:k for k,i in nodes.items()}
    op = old.Plan(rooms=[old.Room(rooms[r.id], r.type if r.eligible else 'excluded', r.polygon, r.area_m2) for r in plan.rooms],
                  devices=[old.Device(nodes[n.id], rooms[n.room_id], n.xy) for n in plan.nodes],
                  free_space=plan.free_space,
                  adjacency={rooms[k]:[rooms[v] for v in vs if v in rooms] for k,vs in plan.adjacency.items() if k in rooms},plan_id=str(plan.plan_id))
    return op, rooms, nodes, rev_rooms, rev_nodes

def to_public(p, rr, rn):
    return PanelAssignment('H'+str(p.panel_id+1),tuple(p.panel_xy),[rr[x] for x in p.room_ids], [rn[x] for x in p.device_ids],list(p.warnings))

def to_old(p, rooms, nodes):
    return old.PanelAssignment(int(str(p.panel_id)[1:])-1 if str(p.panel_id).startswith('H') else int(p.panel_id),p.panel_xy,[rooms[x] for x in p.room_ids],[nodes[x] for x in p.node_ids],list(p.warnings))

def valid_hub(plan, panel, xy):
    point=Point(xy)
    return (any(plan.room(r).polygon.covers(point) and plan.room(r).hub_zone is not None and not plan.room(r).hub_zone.is_empty and plan.room(r).hub_zone.buffer(1e-6).covers(point) for r in panel.room_ids)
            and not point_problems(plan,xy))

def hub_options(plan, panel):
    choices=[]
    for nid in panel.node_ids:
        xy=plan.node(nid).xy
        if valid_hub(plan,panel,xy): choices.append(tuple(xy))
    for rid in panel.room_ids:
        z=plan.room(rid).hub_zone
        if z is not None and not z.is_empty:
            pt=z.representative_point()
            xy=(pt.x,pt.y)
            if valid_hub(plan,panel,xy): choices.append(xy)
    return sorted(set(choices))
