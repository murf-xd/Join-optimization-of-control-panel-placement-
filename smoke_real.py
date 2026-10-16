#!/usr/bin/env python3
"""smoke_real.py -- DEV ONLY router smoke test on real ResPlan geometry. Read-only: changes no code.

    python smoke_real.py --n 50 [--start 0] [--adapter adapter] [--step 0.1] [--full]

Probe nodes are made up (one pole-of-inaccessibility point per eligible room). Every output is
DEV_ONLY_NOT_OFFICIAL and says nothing about official results.

Per plan it checks:
  probe_outside_free  probe point not inside free_space                    (adapter/geometry issue)
  door_unreached      rooms adjacent in the plan but probe-to-probe unreachable on the routing grid
                      (door too narrow on the 0.1 m grid, or not in free_space)
  unreachable_pairs   any probe pair with no route
  --full also runs B's assign + hub placement + routing + validator and records crashes/violations.
"""
import argparse
import csv
import importlib
import os
import pickle
import sys
import time
import traceback

sys.path.insert(0, os.getcwd())
STAMP = "DEV_ONLY_NOT_OFFICIAL"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pkl", default="ResPlan.pkl")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--adapter", default="adapter")
    ap.add_argument("--step", type=float, default=0.1)
    ap.add_argument("--full", action="store_true")
    a = ap.parse_args()

    import geometry
    adapter = importlib.import_module(a.adapter)
    from panel_routing.route import make_router
    from run import attach_devices, dev_probe_devices, make_hooks, solve, PipelineError
    if a.full:
        import assign

    with open(a.pkl, "rb") as f:
        data = pickle.load(f)
    rows = []
    print(f"{STAMP}: probe nodes are made up; nothing below is an official result\n")
    for i in range(a.start, min(a.start + a.n, len(data))):
        row = dict(index=i, status="ok", rooms="", probes="", outside="", door_unreached="",
                   unreachable_pairs="", seconds="", detail="")
        t0 = time.time()
        try:
            g = geometry.load_plan(data[i])
            plan = adapter.make_plan(g)
            attach_devices(plan, dev_probe_devices(plan), "DEV_PROBE")
            pts = [tuple(d.xy) for d in plan.devices]
            row["rooms"], row["probes"] = len(plan.rooms), len(pts)
            hooks = make_hooks(plan)
            row["outside"] = sum(not bool(hooks["inside"]([x], [y])[0]) for x, y in pts)
            router = make_router(plan, [], step=a.step)
            D = router.distance_matrix(pts)
            ok = lambda v: v < 1e8
            idx = {d.room_id: k for k, d in enumerate(plan.devices)}
            n = len(pts)
            row["unreachable_pairs"] = sum(not ok(D[p][q]) for p in range(n) for q in range(p + 1, n))
            bad = []
            for r, nbrs in plan.adjacency.items():
                for s in nbrs:
                    if r < s and r in idx and s in idx and not ok(D[idx[r]][idx[s]]):
                        bad.append((r, s))
            row["door_unreached"] = len(bad)
            if bad:
                row["detail"] = "adjacent but unreachable room ids: " + str(bad[:5])
            if a.full:
                res = solve(plan, assign.assign, hooks, step=a.step)
                rep = res["report"]
                row["status"] = "valid" if rep["valid"] else "invalid"
                if not rep["valid"]:
                    row["detail"] += " | " + "; ".join(f"[{v['rule']}] {v['message'][:80]}" for v in rep["violations"][:3])
            elif row["outside"] or row["door_unreached"] or row["unreachable_pairs"]:
                row["status"] = "issue"
        except PipelineError as e:
            row["status"], row["detail"] = "pipeline_error", str(e)
        except Exception as e:
            row["status"] = "CRASH"
            row["detail"] = f"{type(e).__name__}: {e} @ " + traceback.format_exc().strip().splitlines()[-3].strip()
        row["seconds"] = round(time.time() - t0, 1)
        rows.append(row)
        print(f"plan {i:5d}  {row['status']:<14} rooms={row['rooms']} probes={row['probes']} "
              f"outside={row['outside']} door_unreached={row['door_unreached']} "
              f"unreach_pairs={row['unreachable_pairs']} {row['seconds']}s  {row['detail'][:110]}")

    os.makedirs("out_dev", exist_ok=True)
    path = f"out_dev/{STAMP}_smoke.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    print(f"\n{STAMP} summary over {len(rows)} plans:", dict(Counter(r['status'] for r in rows)))
    print("wrote", path)


if __name__ == "__main__":
    main()
