"""check_adapter.py -- run adapter.to_plan over ResPlan plans and report what could go wrong downstream.

usage:  python3 check_adapter.py 300      (first 300 plans)
        python3 check_adapter.py          (all 17,000 plans, a few minutes)

Counts, over benchmark-like plans only (same rule as check_all.py):
  crashes            to_plan raised an exception (must be 0)
  no hub zone        eligible rooms with no point 0.5 m from walls/windows (B cannot put a hub there)
  node problems      placeholder nodes outside free space or too close to a wall
"""
import pickle
import sys
import time
from collections import Counter

import adapter as A
import geometry_v2 as G
from check_all import benchmark_like

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else None
    with open("ResPlan.pkl", "rb") as f:
        data = pickle.load(f)
    data = data[:n] if n else data
    t0 = time.time()
    crashes, bench = [], 0
    no_zone, node_bad = [], []
    hubs = Counter()
    for i, raw in enumerate(data):
        try:
            plan = A.to_plan(raw)
            if not benchmark_like(G.load_plan(raw)):
                continue
        except Exception as e:
            crashes.append((i, repr(e)[:120]))
            continue
        bench += 1
        hubs[plan.diagnostics["hub_lower_bound"]] += 1
        empty = [r.id for r in plan.eligible_rooms if r.hub_zone.is_empty]
        if empty:
            no_zone.append((i, empty))
        bad = [w for w in plan.warnings if w.startswith("node ")]
        if bad:
            node_bad.append((i, bad[0]))
    print(f"plans={len(data)}  crashes={len(crashes)} {crashes[:5]}  time={time.time()-t0:.0f}s")
    print(f"benchmark-like={bench}  hub lower bound counts={dict(sorted(hubs.items()))}")
    print(f"benchmark plans with a room that has NO hub zone: {len(no_zone)}   {no_zone[:5]}")
    print(f"benchmark plans with a placeholder-node problem: {len(node_bad)}   {node_bad[:5]}")
