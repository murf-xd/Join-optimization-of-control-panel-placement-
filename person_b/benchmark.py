"""Batch benchmark: run many plans through the pipeline and print one summary.

    python benchmark.py --n 200 --seed 1 [--pass-through bathroom]

Until Person A's loader exists this uses random grid-style plans with at most 10 eligible
rooms (like ResPlan). Swap `random_plan` for real plans later and the report stays the same.
Validity is only meaningful once real free space and Person C's router are plugged in: the
stub router ignores walls, so today it mostly checks the assignment rules.
"""
import argparse
import math
import random
import time
from typing import List, Set

from assign import assign, eligible_graph
from contract_merged import MAX_PANEL_AREA, MAX_PANEL_DEVICES, Plan
from pipeline import solve
from stub_route import route
from toy_plan import build_plan
from validator import metrics

ELIGIBLE = ["living", "bedroom", "kitchen", "storage"]
OTHER = ["bathroom", "balcony"]


def random_plan(seed: int) -> Plan:
    """A small house on a grid: 3 to 10 eligible rooms plus up to 3 bathrooms/balconies."""
    rng = random.Random(seed)
    n_elig, n_other = rng.randint(3, 10), rng.randint(0, 3)
    n = n_elig + n_other
    types = [rng.choice(ELIGIBLE) for _ in range(n_elig)] + [rng.choice(OTHER) for _ in range(n_other)]
    rng.shuffle(types)
    cols = rng.choice([3, 4])
    cell = {i: (i % cols, i // cols) for i in range(n)}
    grid = [(a, b) for a in range(n) for b in range(a + 1, n)
            if abs(cell[a][0] - cell[b][0]) + abs(cell[a][1] - cell[b][1]) == 1]
    rng.shuffle(grid)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    edges = []
    for a, b in grid:                                   # random spanning forest + extra doors
        if find(a) != find(b):
            parent[find(a)] = find(b)
            edges.append((a, b))
        elif rng.random() < 0.3:
            edges.append((a, b))
    specs = [(i, types[i], round(rng.uniform(6, 45), 1)) for i in range(n)]
    xy = {i: (cell[i][0] * 6 + 3 + rng.uniform(-1.5, 1.5), cell[i][1] * 5 + 2.5 + rng.uniform(-1, 1))
          for i in range(n)}
    return build_plan(specs, edges, xy=xy, plan_id=f"bench_{seed}")


def lower_bound(plan: Plan, pass_through) -> int:
    """Fewest hubs any design could use: per connected piece, ceil(area/100) and ceil(nodes/5)."""
    graph = eligible_graph(plan, pass_through)
    area = {r.id: r.area for r in plan.rooms if r.eligible}
    seen: Set[int] = set()
    total = 0
    for s in graph:
        if s in seen:
            continue
        comp, stack = {s}, [s]
        while stack:
            for nb in graph[stack.pop()]:
                if nb not in comp:
                    comp.add(nb)
                    stack.append(nb)
        seen |= comp
        big = sum(1 for r in comp if area[r] > MAX_PANEL_AREA)
        total += max(1, big, math.ceil(sum(area[r] for r in comp) / MAX_PANEL_AREA),
                     math.ceil(len(comp) / MAX_PANEL_DEVICES))
    return total


def run(n: int, seed: int, pass_through) -> dict:
    stats = dict(plans=0, valid=0, hubs=0, at_bound=0, gap=0, j_base=0.0, j_best=0.0, secs=0.0, empty=0)
    for s in range(seed, seed + n):
        plan = random_plan(s)
        t = time.time()
        sol = solve(plan, route, pass_through=pass_through)
        stats["secs"] += time.time() - t
        if not sol.panels:
            stats["empty"] += 1
            continue
        base_panels = assign(plan, pass_through=pass_through)
        base = metrics(plan, base_panels, route(plan, base_panels))
        stats["plans"] += 1
        stats["valid"] += bool(sol.result["valid"])
        stats["hubs"] += sol.result["H"]
        lb = lower_bound(plan, pass_through)
        stats["at_bound"] += sol.result["H"] == lb
        stats["gap"] += sol.result["H"] - lb
        stats["j_base"] += base["J"]
        stats["j_best"] += sol.result["J"]
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--pass-through", default="", help="comma list of room types, e.g. bathroom")
    args = ap.parse_args()
    pt = tuple(t for t in args.pass_through.split(",") if t)
    st = run(args.n, args.seed, pt)
    p = max(st["plans"], 1)
    print(f"plans run          {st['plans']}  (skipped, no eligible rooms: {st['empty']})")
    print(f"valid              {st['valid']}/{st['plans']}  ({100 * st['valid'] / p:.1f}%)")
    print(f"avg hubs           {st['hubs'] / p:.2f}")
    print(f"hubs at lower bound {st['at_bound']}/{st['plans']}  "
          f"(avg gap {st['gap'] / p:.2f} hubs; gap > 0 comes from zones that must stay connected)")
    print(f"avg cost J         {st['j_base'] / p:.1f} first grouping, hub on default node  ->  "
          f"{st['j_best'] / p:.1f} after candidate search + hub refinement")
    print(f"avg time per plan  {1000 * st['secs'] / p:.0f} ms (stub router)")


if __name__ == "__main__":
    main()
