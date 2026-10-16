"""Convert Person A's geometry output into the shared routing Plan, in METRES.

Scale-only conversion (drawing units / scale). No origin shift and no y-flip: the
organisers' frame is still unknown, and length, bends, crossings and overlap do not
depend on it. The frame is applied later, in one place, once the sample JSON arrives.
"""
from geometry import to_metres
from panel_routing.contract import Plan, Room


def make_plan(geometry_result, plan_id=None):
    g = geometry_result
    s = g["scale"]

    rooms, new_of = [], {}
    for new_id, r in enumerate(g["rooms"]):
        new_of[r["id"]] = new_id
        rooms.append(Room(id=new_id, type=r["type"],
                          polygon=to_metres(r["poly"], s),
                          area=r["area_m2"]))            # already m2: NOT converted again

    adjacency = {new_of[a]: [new_of[b] for b in nbrs if b in new_of]
                 for a, nbrs in g["adjacency"].items() if a in new_of}

    pid = plan_id if plan_id is not None else g.get("plan_id")
    plan = Plan(rooms=rooms, devices=[],                 # nodes wait for the official input
                free_space=to_metres(g["free_space"], s),
                adjacency=adjacency,
                plan_id=str(pid) if pid is not None else "unknown")

    plan.scale = s
    plan.room_names = {v: k for k, v in new_of.items()}  # int id -> geometry id ("living_0")
    plan.geo = {k: to_metres(g[k], s) for k in ("inner", "walls", "windows")}  # for validator hooks
    return plan