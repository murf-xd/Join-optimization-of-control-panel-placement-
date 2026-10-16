#!/usr/bin/env python3
"""diagnose_dev.py -- DEV_ONLY_NOT_OFFICIAL read-only diagnostics for failed smoke-test plans.

    python diagnose_dev.py 5 6 24 25 > out_dev/DEV_ONLY_NOT_OFFICIAL_diag.txt ; cat that file

Changes no code. Probe nodes are made up (dev only). Prints facts, not verdicts.
"""
import importlib
import itertools
import math
import os
import pickle
import re
import sys

sys.path.insert(0, os.getcwd())
import geometry
from shapely import contains_xy
from shapely.geometry import LineString, Point

adapter = importlib.import_module("adapter")
import assign
from panel_routing.output import room_name
from panel_routing.route import make_router
from run import attach_devices, dev_probe_devices, make_hooks, solve

STAMP = "DEV_ONLY_NOT_OFFICIAL"


def load(i, data):
    g = geometry.load_plan(data[i])
    plan = adapter.make_plan(g)
    attach_devices(plan, dev_probe_devices(plan), "DEV_PROBE")
    return g, plan


def gates_near(g, p, r=1.5):
    out = []
    for k, gate in enumerate(g["gates"]):
        try:
            seg = geometry.to_metres(gate["segment"], g["scale"])
        except Exception as e:
            out.append((k, f"to_metres failed: {e}"))
            continue
        d = seg.distance(Point(p))
        if d <= r:
            out.append((k, f"usable={gate.get('usable')} len={seg.length:.3f} m dist={d:.2f} "
                           f"keys={sorted(k2 for k2 in gate if k2 != 'segment')}"))
    return out


def components(plan):
    fs = plan.free_space
    parts = list(fs.geoms) if fs.geom_type == "MultiPolygon" else [fs]
    return sorted(((p.area, p) for p in parts), key=lambda t: -t[0])


def smoke_issue(i, data):
    g, plan = load(i, data)
    print(f"\n=== plan {i} (smoke issue) {STAMP} ===")
    print(f"rooms={len(plan.rooms)} eligible={len(plan.eligible_rooms)} scale={getattr(plan, 'scale', None)}")
    comps = components(plan)
    print(f"free_space components: {len(comps)}  areas(m2)={[round(a, 2) for a, _ in comps[:6]]}")
    hooks = make_hooks(plan)
    for d in plan.devices:
        r = plan.room_by_id(d.room_id)
        inside = bool(hooks["inside"]([d.xy[0]], [d.xy[1]])[0])
        comp = next((k for k, (_, c) in enumerate(comps) if c.covers(Point(d.xy))), None)
        cov = r.polygon.intersection(plan.free_space).area / max(r.polygon.area, 1e-9)
        print(f"  probe {d.id} room {room_name(d.room_id)} type={r.type} area={r.area:.2f} "
              f"free_cov={cov:.2f} inside_free={inside} component={comp}")
    router = make_router(plan, [], step=0.1)
    pts = [tuple(d.xy) for d in plan.devices]
    D = router.distance_matrix(pts)
    idx = {d.room_id: k for k, d in enumerate(plan.devices)}
    for r, nbrs in plan.adjacency.items():
        for s in nbrs:
            if r < s and r in idx and s in idx and not D[idx[r]][idx[s]] < 1e8:
                pa, pb = pts[idx[r]], pts[idx[s]]
                shared = plan.room_by_id(r).polygon.buffer(0.5).intersection(plan.room_by_id(s).polygon.buffer(0.5))
                c = shared.centroid
                print(f"  UNREACHABLE adjacent {room_name(r)}-{room_name(s)}; "
                      f"types={plan.room_by_id(r).type}/{plan.room_by_id(s).type}; contact area={shared.area:.2f}")
                for k, txt in gates_near(g, (c.x, c.y), 2.0):
                    print(f"      gate {k}: {txt}")


def capacity_issue(i, data):
    g, plan = load(i, data)
    print(f"\n=== plan {i} (capacity) {STAMP} ===")
    el = plan.eligible_rooms
    tot = sum(r.area for r in el)
    print(f"eligible rooms={len(el)} total={tot:.2f} m2  lower bound hubs={math.ceil(tot / 100)}")
    print("room areas:", {room_name(r.id): round(r.area, 2) for r in el})
    print("adjacency (eligible only):",
          {room_name(r): [room_name(s) for s in plan.adjacency.get(r, []) if any(s == e.id for e in el)]
           for r in (e.id for e in el)})
    raw = assign.assign(plan)
    for a in raw:
        area = sum(plan.room_by_id(r).area for r in a.room_ids)
        print(f"  B hub {a.panel_id}: rooms={[room_name(r) for r in a.room_ids]} area={area:.2f} "
              f"nodes={list(a.device_ids)} warnings={getattr(a, 'warnings', None)}")
    big = [room_name(r.id) for r in el if r.area > 100]
    print("single rooms > 100 m2 (cannot fit any hub):", big)
    if len(el) <= 12:
        ids = [r.id for r in el]
        area = {r.id: r.area for r in el}
        adj = {r: {s for s in plan.adjacency.get(r, []) if s in area} for r in ids}

        def connected(sub):
            sub = set(sub)
            seen, stack = set(), [next(iter(sub))]
            while stack:
                u = stack.pop()
                if u in seen:
                    continue
                seen.add(u)
                stack += [v for v in adj[u] if v in sub]
            return seen == sub

        best = None
        for k in range(1, len(ids) + 1):
            for labels in itertools.product(range(k), repeat=len(ids)):
                if len(set(labels)) != k or labels[0] != 0:
                    continue
                groups = [[ids[j] for j in range(len(ids)) if labels[j] == g_] for g_ in range(k)]
                if all(sum(area[r] for r in grp) <= 100 + 1e-9 and connected(grp) for grp in groups):
                    best = (k, groups)
                    break
            if best:
                break
        print("brute force min feasible hubs (connected, <=100 m2, adjacency as given):",
              best[0] if best else "none", [[room_name(r) for r in g_] for g_ in best[1]] if best else "")


def free_space_violation(i, data):
    g, plan = load(i, data)
    print(f"\n=== plan {i} (free_space violation) {STAMP} ===")
    hooks = make_hooks(plan)
    res = solve(plan, assign.assign, hooks)
    for v in res["report"]["violations"]:
        print(f"  [{v['rule']}] hub={v.get('hub')}: {v['message']}")
        m = re.search(r"\(\s*(-?[\d.]+),\s*(-?[\d.]+)\)", v["message"])
        if v["rule"] != "free_space" or not m:
            continue
        p = (float(m.group(1)), float(m.group(2)))
        print(f"    nearest free_space distance: {plan.free_space.distance(Point(p)):.4f} m")
        for rr in plan.rooms:
            if rr.polygon.distance(Point(p)) < 0.3:
                print(f"    near room {room_name(rr.id)} type={rr.type} dist={rr.polygon.distance(Point(p)):.3f}")
        for k, txt in gates_near(g, p):
            print(f"    gate {k}: {txt}")
        h = next(h for h in res["data"]["hubs"] if h["hub_id"] == v.get("hub"))
        for j, seg in enumerate(h["route_segments"]):
            line = LineString(seg["polyline"])
            if line.distance(Point(p)) < 1e-3:
                print(f"    leg {j + 1} {seg['from']}->{seg['to']} polyline={seg['polyline']}")
                n = max(int(line.length / 0.005), 2)
                outside = []
                for t in range(n + 1):
                    q = line.interpolate(t / n, normalized=True)
                    if not contains_xy(plan.free_space, q.x, q.y):
                        outside.append(round(t / n * line.length, 3))
                if outside:
                    print(f"    outside free_space along leg from {outside[0]} to {outside[-1]} m "
                          f"({len(outside)} samples of {n + 1}); leg length {line.length:.3f}")
                for a, b in zip(seg["polyline"], seg["polyline"][1:]):
                    for name, q in (("start", a), ("end", b)):
                        print(f"    corner {name} {q} inside_free="
                              f"{bool(contains_xy(plan.free_space, q[0], q[1]))}")
        probes = [d.xy for d in plan.devices]
        print("    violation x/y equals a probe coordinate?:",
              [("x", d) for d in probes if abs(d[0] - p[0]) < 2e-3] + [("y", d) for d in probes if abs(d[1] - p[1]) < 2e-3])


if __name__ == "__main__":
    with open("ResPlan.pkl", "rb") as f:
        data = pickle.load(f)
    print(f"{STAMP}: probe nodes are made up; nothing here is an official result")
    for i in map(int, sys.argv[1:]):
        for fn in (smoke_issue, capacity_issue, free_space_violation):
            try:
                fn(i, data)
            except Exception as e:
                print(f"  ({fn.__name__} on plan {i}: {type(e).__name__}: {e})")
