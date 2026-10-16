"""Person B: decide how many panels, which rooms each panel looks after, and where it sits.

    assign(plan) -> List[PanelAssignment]

Method:
  1. Build a "neighbour map" of eligible rooms. Rooms are neighbours when a door joins
     them directly, or through a chain of rooms whose type is in `pass_through`
     (EMPTY by default: no pass-through until the organisers confirm the rule).
  2. If the plan has at most EXACT_LIMIT eligible rooms: try EVERY valid grouping and keep
     the fewest hubs, then the tightest groups, then the smallest area gap (exact).
  3. Otherwise (fallback) greedy region growing + dissolve + compactness moves,
     repeated with a fixed seed.
  4. Put each hub at the node with the smallest total distance to its group's nodes.
     Pass dist=... to use real routing distance once Person C's routing exists.

assign_candidates() returns several best groupings so Person C can route each one and
keep the lowest true cost J. assign() returns the first (best) one.
"""
import math
import random
from collections import defaultdict, deque
from typing import Callable, Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

from contract_merged import MAX_PANEL_AREA, MAX_PANEL_DEVICES, PanelAssignment, Plan, XY

Graph = Dict[int, Set[int]]
DistFn = Callable[[XY, XY], float]

# Room types a zone may be joined through. Empty = only direct door links between eligible
# rooms count. Open question for the organisers (does a route through a bathroom count?).
# Never put outdoor types (balcony, garden, land...) here: cable may not cross them.
PASS_THROUGH_TYPES: FrozenSet[str] = frozenset()

# Plans with at most this many eligible rooms are solved exactly. ResPlan has <= 10.
EXACT_LIMIT = 10
# Safety valve: the exact search gives up after this many steps (about a second) and the
# greedy answer is used instead, so an odd plan can never hang the pipeline.
EXACT_BUDGET = 400_000


class _OutOfBudget(Exception):
    pass


def _euclid(p: XY, q: XY) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1])


# ---------------------------------------------------------------- neighbour map
def eligible_graph(plan: Plan, pass_through: Iterable[str] = PASS_THROUGH_TYPES) -> Graph:
    """Which eligible rooms touch which.

    Two eligible rooms are neighbours if a door joins them directly, or if they are
    joined through a chain of rooms whose type is in `pass_through`. Any other
    non-eligible room (balcony, garden, stair, ...) is a wall for zone purposes.
    """
    allowed = set(pass_through)
    types = {r.id: r.type for r in plan.rooms}
    eligible = {r.id for r in plan.rooms if r.eligible}
    graph: Graph = {rid: set() for rid in eligible}
    for start in eligible:
        seen = {start}
        queue = deque([start])
        while queue:
            cur = queue.popleft()
            for nxt in plan.adjacency.get(cur, []):
                if nxt in seen:
                    continue
                seen.add(nxt)
                if nxt in eligible:
                    graph[start].add(nxt)      # stop at an eligible room
                elif types.get(nxt) in allowed:
                    queue.append(nxt)          # allowed pass-through room: keep walking
    for a in list(graph):                      # make it symmetric, just in case
        for b in graph[a]:
            graph[b].add(a)
    return graph


def is_connected(group: Set[int], graph: Graph) -> bool:
    if len(group) <= 1:
        return True
    start = next(iter(group))
    seen, stack = {start}, [start]
    while stack:
        cur = stack.pop()
        for nxt in graph[cur]:
            if nxt in group and nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return len(seen) == len(group)


# --------------------------------------------------------------------- helpers
def _load(group: Set[int], area: Dict[int, float], ndev: Dict[int, int]):
    return sum(area[r] for r in group), sum(ndev[r] for r in group)


def _fits(group: Set[int], room: int, area, ndev) -> bool:
    a, n = _load(group, area, ndev)
    return a + area[room] <= MAX_PANEL_AREA and n + ndev[room] <= MAX_PANEL_DEVICES


def _spread(group: Set[int], xy_room: Dict[int, XY]) -> float:
    """How scattered a group is: sum of squared distances of its rooms' devices to their
    centre. Small = compact = shorter cable loop."""
    pts = [xy_room[r] for r in group if r in xy_room]
    if len(pts) < 2:
        return 0.0
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    return sum((p[0] - cx) ** 2 + (p[1] - cy) ** 2 for p in pts)


# ------------------------------------------------------------ step 2: greedy grow
def grow_groups(graph: Graph, area, ndev, rng: random.Random) -> List[Set[int]]:
    unassigned = set(graph)
    groups: List[Set[int]] = []
    while unassigned:
        # Start from the room with the fewest free neighbours (dead ends first), so it
        # doesn't get stranded later.
        seed = min(sorted(unassigned),
                   key=lambda r: (len(graph[r] & unassigned), rng.random()))
        group = {seed}
        unassigned.remove(seed)
        while True:
            candidates = {n for r in group for n in graph[r]
                          if n in unassigned and _fits(group, n, area, ndev)}
            if not candidates:
                break
            nxt = min(sorted(candidates),
                      key=lambda r: (len(graph[r] & unassigned), rng.random()))
            group.add(nxt)
            unassigned.remove(nxt)
        groups.append(group)
    return groups


# ------------------------------------------------- step 3: fewer panels (dissolve)
def _try_dissolve(idx: int, groups: List[Set[int]], graph, area, ndev) -> Optional[List[Set[int]]]:
    """Move every room of groups[idx] into other groups. Return new groups, or None."""
    trial = [set(g) for g in groups]
    pending = sorted(trial[idx], key=lambda r: -area[r])      # biggest rooms first
    trial[idx] = set()
    progress = True
    while pending and progress:
        progress = False
        for r in list(pending):
            for j, h in enumerate(trial):
                if j != idx and h and graph[r] & h and _fits(h, r, area, ndev):
                    h.add(r)
                    pending.remove(r)
                    progress = True
                    break
    if pending:
        return None
    return [h for j, h in enumerate(trial) if j != idx]


def reduce_groups(groups: List[Set[int]], graph, area, ndev) -> List[Set[int]]:
    improved = True
    while improved:
        improved = False
        order = sorted(range(len(groups)), key=lambda i: _load(groups[i], area, ndev)[0])
        for i in order:
            result = _try_dissolve(i, groups, graph, area, ndev)
            if result is not None:
                groups, improved = result, True
                break
    return groups


# ------------------------------------------------ step 4: tighter groups (moves)
def improve_compactness(groups: List[Set[int]], graph, area, ndev,
                        xy_room: Dict[int, XY], max_passes: int = 50) -> List[Set[int]]:
    """Repeatedly make the single best room move that lowers the total spread.

    A move takes one room out of its group and puts it into a touching group. It is only
    allowed if the new group still fits the 100 m2 / 5 device limits (MAX_PANEL_AREA / MAX_PANEL_DEVICES) and the group the
    room leaves stays in one connected piece. Panel count never changes.
    """
    groups = [set(g) for g in groups]
    for _ in range(max_passes):
        best_gain, best_move = 1e-9, None
        for i, a in enumerate(groups):
            spread_a = _spread(a, xy_room)
            for r in sorted(a):
                rest = a - {r}
                if not rest or not is_connected(rest, graph):
                    continue                          # never empty a group or split it
                spread_rest = _spread(rest, xy_room)
                for j, b in enumerate(groups):
                    if j == i or not (graph[r] & b) or not _fits(b, r, area, ndev):
                        continue
                    gain = (spread_a + _spread(b, xy_room)
                            - spread_rest - _spread(b | {r}, xy_room))
                    if gain > best_gain:
                        best_gain, best_move = gain, (i, j, r)
        if best_move is None:
            break
        i, j, r = best_move
        groups[i].remove(r)
        groups[j].add(r)
    return groups


# ------------------------------------------------------ step 6: panel placement
def _panel_location(plan: Plan, group: Set[int], device_ids: List[int],
                    dist: DistFn = _euclid) -> XY:
    """The device whose total distance to the group's other devices is smallest.

    Staying on a device keeps the panel inside a room and inside the free space.
    Pass a routing-based `dist` (from Person C) to measure walking distance instead of
    straight-line distance."""
    if device_ids:
        pts = [plan.device_by_id(d).xy for d in device_ids]
        return min(pts, key=lambda p: sum(dist(p, q) for q in pts))
    poly = plan.room_by_id(min(group)).polygon
    if poly is not None:
        c = poly.centroid
        return (c.x, c.y)
    return (0.0, 0.0)


# ------------------------------------------------------------------ main entry
def _area_gap(groups: List[Set[int]], area: Dict[int, float]) -> float:
    """Tie-break from the problem statement: gap between the biggest and smallest hub."""
    totals = [sum(area[r] for r in g) for g in groups]
    return max(totals) - min(totals) if totals else 0.0


def _score(groups: List[Set[int]], area, xy_room) -> Tuple[int, float, float]:
    """Smaller is better: fewest hubs, then tightest groups (stand-in for cost J until
    Person C routes them), then the smallest area gap."""
    return (len(groups),
            round(sum(_spread(g, xy_room) for g in groups), 6),
            round(_area_gap(groups, area), 6))


# ------------------------------------------------------- exact search (small plans)
def exact_groups(graph: Graph, area, ndev, xy_room: Dict[int, XY],
                 upper_bound: int, limit: int = 20) -> List[List[Set[int]]]:
    """Try every way to split the rooms into groups.

    Rooms are placed one by one, either into an existing group (if it still fits the
    area / node limits) or into a new group. A split is kept only if every group is
    connected. `upper_bound` is a known-feasible hub count (from the greedy solver): the
    search never explores more groups than that. Returns up to `limit` best splits
    (all with the fewest hubs found), best first. An oversized room always gets a group
    of its own, because nothing else fits next to it.
    """
    rooms = sorted(graph)
    n = len(rooms)
    best_k = upper_bound
    kept: List[Tuple[Tuple[int, float, float], List[Set[int]]]] = []
    seen_keys: Set[FrozenSet[FrozenSet[int]]] = set()

    groups: List[Set[int]] = []
    loads: List[List[float]] = []               # [area, nodes] per group
    steps = 0

    def recurse(i: int):
        nonlocal best_k, kept, steps
        steps += 1
        if steps > EXACT_BUDGET:
            raise _OutOfBudget
        if len(groups) > best_k:
            return
        if i == n:
            if all(is_connected(g, graph) for g in groups):
                k = len(groups)
                if k < best_k:
                    best_k = k
                    kept = []
                    seen_keys.clear()
                key = frozenset(frozenset(g) for g in groups)
                if k == best_k and key not in seen_keys:
                    seen_keys.add(key)
                    snapshot = [set(g) for g in groups]
                    kept.append((_score(snapshot, area, xy_room), snapshot))
                    kept.sort(key=lambda t: (t[0], sorted(sorted(g) for g in t[1])))
                    del kept[limit:]
            return
        r = rooms[i]
        for gi, g in enumerate(groups):
            if (loads[gi][0] + area[r] <= MAX_PANEL_AREA
                    and loads[gi][1] + ndev[r] <= MAX_PANEL_DEVICES):
                g.add(r)
                loads[gi][0] += area[r]
                loads[gi][1] += ndev[r]
                recurse(i + 1)
                g.remove(r)
                loads[gi][0] -= area[r]
                loads[gi][1] -= ndev[r]
        if len(groups) + 1 <= best_k:           # open a new group
            groups.append({r})
            loads.append([area[r], ndev[r]])
            recurse(i + 1)
            groups.pop()
            loads.pop()

    try:
        recurse(0)
    except _OutOfBudget:
        pass                                    # every kept split was fully checked: still valid
    return [g for _, g in kept]


def _heuristic_groups(graph, area, ndev, xy_room, n_restarts, seed):
    rng = random.Random(seed)                      # fixed seed -> reproducible results
    best, best_score = None, None
    for _ in range(n_restarts):
        groups = grow_groups(graph, area, ndev, rng)
        groups = reduce_groups(groups, graph, area, ndev)
        groups = improve_compactness(groups, graph, area, ndev, xy_room)
        score = _score(groups, area, xy_room)
        if best is None or score < best_score:
            best, best_score = groups, score
    return best


def assign(plan: Plan, n_restarts: int = 30, seed: int = 0,
           dist: Optional[DistFn] = None,
           pass_through: Iterable[str] = PASS_THROUGH_TYPES) -> List[PanelAssignment]:
    """Best grouping: fewest hubs, then tightest, then smallest area gap."""
    options = assign_candidates(plan, limit=1, n_restarts=n_restarts, seed=seed,
                                dist=dist, pass_through=pass_through)
    return options[0] if options else []


def assign_candidates(plan: Plan, limit: int = 20, n_restarts: int = 30, seed: int = 0,
                      dist: Optional[DistFn] = None,
                      pass_through: Iterable[str] = PASS_THROUGH_TYPES
                      ) -> List[List[PanelAssignment]]:
    """Up to `limit` different groupings, all with the fewest hubs found, best first.

    Person C can route each one and keep the lowest true cost J. Small plans (<=
    EXACT_LIMIT eligible rooms) are solved exactly; bigger ones use the greedy solver and
    return a single grouping."""
    dist = dist or _euclid
    graph = eligible_graph(plan, pass_through)
    if not graph:
        return []

    area = {r.id: r.area for r in plan.rooms if r.eligible}
    devs_by_room: Dict[int, List[int]] = defaultdict(list)
    xy_room: Dict[int, XY] = {}
    for d in plan.devices:
        devs_by_room[d.room_id].append(d.id)
        xy_room.setdefault(d.room_id, d.xy)
    ndev = {rid: len(devs_by_room[rid]) for rid in graph}

    heuristic = _heuristic_groups(graph, area, ndev, xy_room, n_restarts, seed)
    options = [heuristic]
    if len(graph) <= EXACT_LIMIT:
        exact = exact_groups(graph, area, ndev, xy_room, upper_bound=len(heuristic), limit=limit)
        if exact:
            options = exact
    return [_build(plan, groups, area, ndev, devs_by_room, dist) for groups in options]


def _build(plan: Plan, best: List[Set[int]], area, ndev, devs_by_room, dist) -> List[PanelAssignment]:
    result: List[PanelAssignment] = []
    for pid, group in enumerate(sorted(best, key=min)):      # stable panel numbering
        room_ids = sorted(group)
        device_ids = sorted(d for r in room_ids for d in devs_by_room[r])
        warnings: List[str] = []
        for r in room_ids:
            if area[r] > MAX_PANEL_AREA:
                warnings.append(f"room {r} area {area[r]:.1f} m2 exceeds {MAX_PANEL_AREA:.0f} m2; assigned alone")
            if ndev[r] > MAX_PANEL_DEVICES:
                warnings.append(f"room {r} has {ndev[r]} devices, over the {MAX_PANEL_DEVICES} limit")
        result.append(PanelAssignment(
            panel_id=pid,
            panel_xy=_panel_location(plan, group, device_ids, dist),
            room_ids=room_ids,
            device_ids=device_ids,
            warnings=warnings,
        ))
    return result


if __name__ == "__main__":
    from toy_plan import make_toy_plan

    plan = make_toy_plan()
    for p in assign(plan):
        total = sum(plan.room_by_id(r).area for r in p.room_ids)
        print(f"panel {p.panel_id} at {p.panel_xy}: rooms {p.room_ids}, "
              f"devices {p.device_ids}, area {total:.0f} m2, warnings {p.warnings}")
