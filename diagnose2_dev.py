#!/usr/bin/env python3
"""diagnose2_dev.py -- DEV_ONLY_NOT_OFFICIAL read-only follow-up for plan 6 (leg leaves free space)
and plan 25 (adjacent rooms unreachable despite usable gates).

    python diagnose2_dev.py [6] [25] > out_dev/DEV_ONLY_NOT_OFFICIAL_diag2.txt ; cat out_dev/DEV_ONLY_NOT_OFFICIAL_diag2.txt
Plan ids on the command line select what runs (default: 6 and 25). Changes no code. Probe nodes are made up (dev only).
"""
import os
import pickle
import re
import sys

sys.path.insert(0, os.getcwd())
import geometry
from shapely import contains_xy
from shapely.geometry import LineString, Point

import assign
from diagnose_dev import STAMP, gates_near, load
from panel_routing.output import room_name
from panel_routing.route import make_router
from run import make_hooks, solve


def spans(line, fs, n_per_m=200):
    n = max(int(line.length * n_per_m), 2)
    bad = [i / n * line.length for i in range(n + 1)
           if not contains_xy(fs, *line.interpolate(i / n, normalized=True).coords[0])]
    return (round(bad[0], 3), round(bad[-1], 3), len(bad), n + 1) if bad else None


def plan6(data):
    print(f"\n=== plan 6 {STAMP} ===")
    g, plan = load(6, data)
    made = {}

    def factory(p, hubs, step=0.1):
        made["r"] = make_router(p, hubs, step=step)
        return made["r"]

    hooks = make_hooks(plan)
    res = solve(plan, assign.assign, hooks, router_factory=factory)
    router, fs = made["r"], plan.free_space
    print("hubs:", [(a.panel_id, a.panel_xy) for a in res["assignments"]])
    for loop, h in zip(res["loops"], res["data"]["hubs"]):
        for j, (raw, seg) in enumerate(zip(loop.legs, h["route_segments"])):
            rl, jl = LineString(raw), LineString(seg["polyline"])
            sr, sj = spans(rl, fs), spans(jl, fs)
            if sr or sj:
                print(f"hub {h['hub_id']} leg {j + 1} {seg['from']}->{seg['to']}")
                print(f"  RAW router polyline : {raw}")
                print(f"  JSON polyline       : {seg['polyline']}")
                print(f"  raw outside span (start m, end m, n_out, n)  : {sr}")
                print(f"  JSON outside span                          : {sj}")
                print(f"  min distance of the leg to free_space boundary: {rl.distance(fs.boundary):.7f} m "
                      f"(0 => leg runs ON the boundary; contains_xy treats boundary as outside)")
                print(f"  max |raw - JSON| coordinate difference: "
                      f"{max(abs(a - b) for p, q in zip(raw, seg['polyline']) for a, b in zip(p, q)):.6f} m")
                ys = sorted({round(p[1], 6) for p in raw}); xs = sorted({round(p[0], 6) for p in raw})
                print(f"  leg x values {xs}  y values {ys}")
                print(f"  grid lines: on 0.1 multiple? x:{[abs(round((x - router.xs[0]) / 0.1) * 0.1 + router.xs[0] - x) < 1e-6 for x in xs]}"
                      f" y:{[abs(round((y - router.ys[0]) / 0.1) * 0.1 + router.ys[0] - y) < 1e-6 for y in ys]}")
                pts = [(x, y) for x in router.xs for y in router.ys]
    print("terminals:", [tuple(d.xy) for d in plan.devices] + [a.panel_xy for a in res["assignments"]])


def plan25_zoom(g, plan, seg, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7, 7))
    def draw(geom, **kw):
        for part in getattr(geom, "geoms", [geom]):
            if part.geom_type == "Polygon":
                ax.fill(*part.exterior.xy, **kw)
    box = seg.buffer(1.2)
    draw(plan.free_space.intersection(box), fc="#9ecae1", ec="#08519c", alpha=0.6, label="free_space")
    draw(plan.geo["windows"].intersection(box), fc="#fdae6b", ec="#d94801", alpha=0.7, label="windows")
    draw(plan.geo["walls"].intersection(box), fc="#bbbbbb", ec="#555555", alpha=0.4, label="walls")
    ax.plot(*seg.xy, color="red", lw=3, label="usable gate segment")
    ax.set_aspect("equal"); ax.legend(); ax.set_title(f"{STAMP}: plan 25 gate zoom (metres)")
    fig.savefig(path, dpi=130); plt.close(fig)


def plan25(data):
    print(f"\n=== plan 25 {STAMP} ===")
    g, plan = load(25, data)
    fs = plan.free_space
    print("scale:", getattr(plan, "scale", None), " gates:", len(g["gates"]))
    r, s = 0, 3
    print("adjacency[0]:", plan.adjacency.get(r), " adjacency[3]:", plan.adjacency.get(s))
    for k, gate in enumerate(g["gates"]):
        seg = geometry.to_metres(gate["segment"], g["scale"])
        a = plan.room_by_id(r).polygon.buffer(0.4).distance(seg)
        b = plan.room_by_id(s).polygon.buffer(0.4).distance(seg)
        if a < 0.05 and b < 0.05:
            cov = fs.intersection(seg.buffer(0.05)).area / max(seg.buffer(0.05).area, 1e-9)
            win = plan.geo["windows"].intersection(seg.buffer(0.1)).area
            print(f"  gate {k}: usable={gate.get('usable')} len={seg.length:.3f} m "
                  f"free_space coverage of gate strip={cov:.2f} window overlap(m2)={win:.4f} "
                  f"other keys={sorted(x for x in gate if x != 'segment')}")
            print(f"    gate segment bounds (m): {tuple(round(v, 3) for v in seg.bounds)}")
            wins = plan.geo["windows"].intersection(seg.buffer(0.3))
            for w in getattr(wins, "geoms", [wins]):
                if not w.is_empty:
                    print(f"    window part near gate: bounds={tuple(round(v, 3) for v in w.bounds)} "
                          f"area={w.area:.4f} area_within_0.1m_of_gate={w.intersection(seg.buffer(0.1)).area:.4f}")
            sl = fs.intersection(seg.buffer(0.02))
            print(f"    free_space left on the gate line (area {sl.area:.5f} m2; mean width "
                  f"{sl.area / max(seg.length * 0.04, 1e-9) * 0.04:.4f} m of 0.04 m probe strip)")
            os.makedirs("out_dev", exist_ok=True)
            plan25_zoom(g, plan, seg, f"out_dev/{STAMP}_plan25_gate{k}.png")
            print(f"    wrote out_dev/{STAMP}_plan25_gate{k}.png")
    comps = list(fs.geoms) if fs.geom_type == "MultiPolygon" else [fs]
    for rid in (r, s):
        cov = [round(c.intersection(plan.room_by_id(rid).polygon).area, 2) for c in comps]
        print(f"  room {room_name(rid)}: area inside each free_space component {cov}")
    print("  components (m2):", [round(c.area, 2) for c in comps])


if __name__ == "__main__":
    with open("ResPlan.pkl", "rb") as f:
        data = pickle.load(f)
    print(f"{STAMP}: probe nodes are made up; nothing here is an official result")
    ids = [int(a) for a in sys.argv[1:]] or [6, 25]
    for pid, fn in ((6, plan6), (25, plan25)):
        if pid not in ids:
            continue
        try:
            fn(data)
        except Exception as e:
            import traceback; traceback.print_exc()
