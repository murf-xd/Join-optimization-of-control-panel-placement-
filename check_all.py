"""check_all.py -- run geometry_v2.load_plan over ResPlan plans and report problems.

usage:  python3 check_all.py 300      (first 300 plans)
        python3 check_all.py          (all 17,000 plans, a few minutes)

"benchmark-like" = every eligible room is 2..100 m2 AND all eligible rooms lie in ONE connected piece of
(inner - wall - window)  (the organisers' own benchmark rule, problem statement slide 7).
"PROBLEM" = a benchmark-like plan where gate-connectivity (doors + open passages) still cannot reach
every eligible room from the others.
"""
import pickle
import sys
import time

import geometry_v2 as G


def benchmark_like(res):
    elig = [r for r in res["rooms"] if r["eligible"]]
    if not elig or any(r["area_m2"] > 100 or r["area_m2"] < 2 for r in elig):
        return False
    comps = G.polys(res["inner"].difference(res["walls"]).difference(res["windows"]))
    seen = set()
    for r in elig:
        p = r["poly"].representative_point()
        i = next((k for k, c in enumerate(comps) if c.contains(p)), None)
        if i is None:
            return False
        seen.add(i)
    return len(seen) == 1


def unreached(res):
    """Eligible rooms not connected, through gates, to the biggest group of eligible rooms."""
    adj = res["adjacency"]
    elig = [r["id"] for r in res["rooms"] if r["eligible"]]
    group, groups = {}, []
    for start in elig:
        if start in group:
            continue
        stack, members = [start], set()
        while stack:
            x = stack.pop()
            if x in members:
                continue
            members.add(x)
            stack.extend(adj.get(x, []))
        for m in members:
            group[m] = len(groups)
        groups.append({m for m in members if m in elig})
    if len(groups) <= 1:
        return []
    biggest = max(groups, key=len)
    return sorted(e for e in elig if e not in biggest)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else None
    with open("ResPlan.pkl", "rb") as f:
        data = pickle.load(f)
    data = data[:n] if n else data
    t0 = time.time()
    crashes, bench, problems = [], 0, []
    for i, raw in enumerate(data):
        try:
            res = G.load_plan(raw)
        except Exception as e:
            crashes.append((i, repr(e)))
            continue
        if benchmark_like(res):
            bench += 1
            u = unreached(res)
            if u:
                problems.append((i, u))
    print(f"MIN_OPEN_M={G.MIN_OPEN_M}  plans={len(data)}  crashes={len(crashes)} {crashes[:5]}  time={time.time()-t0:.0f}s")
    print(f"benchmark-like={bench}  skipped(not benchmark)={len(data)-bench-len(crashes)}")
    print(f"PROBLEM benchmark plans: {len(problems)}")
    for i, u in problems:
        print(f"  plan {i} unreached: {u}")
