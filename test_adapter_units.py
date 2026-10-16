#!/usr/bin/env python3
"""test_adapter_units.py -- READ-ONLY checks of adapter.make_plan on real ResPlan plans.

Run from the project root (next to geometry.py, adapter.py, ResPlan.pkl):

    python test_adapter_units.py                       # tests adapter.py on the first 200 plans
    python test_adapter_units.py --adapter adapter_candidate   # test a candidate file instead

It never writes a file and never edits adapter.py, geometry.py or panel_routing/.
It creates no device / node coordinates (the official ones are not available yet);
a Plan that contains devices counts as a failure.

Checks per plan (failures are reported as "plan index / check name"):
  make_plan_runs           make_plan(geometry_result) does not raise
  source_not_mutated       geometry_result is bit-for-bit the same after make_plan
  no_invented_nodes        plan.devices is empty
  room_count_preserved     same number of rooms
  room_ids_are_ints        every Room.id is an int
  room_ids_unique          no duplicate Room.id
  room_names_present       plan.room_names exists (new int id -> geometry id)
  room_names_bijective     room_names is a one-to-one map covering exactly the geometry ids
  room_names_order         room i keeps its own name, and its type is preserved
  room_area_unchanged      Room.area == geometry area_m2 exactly (not converted twice)
  room_polygon_area        Room.polygon.area (m2) matches Room.area within 0.01 m2
  free_space_not_empty     free space exists
  free_space_area_scaled   area == original area / scale^2
  free_space_bounds_scaled bounds == original bounds / scale
  scale_carried            plan.scale == geometry scale
  walkable_in_free_space   each walkable room is >= 99% inside free space
  adjacency_round_trip     plan.adjacency mapped back through room_names == original adjacency
  plan_id_carried          plan.plan_id == str(geometry plan_id)
"""
import argparse
import copy
import dataclasses
import importlib
import math
import os
import pickle
import sys
from collections import Counter

AREA_TOL_M2 = 0.01
REL_TOL = 1e-9
BOUNDS_TOL_M = 1e-6
COVERAGE_MIN = 0.99

CHECKS = [
    "make_plan_runs", "source_not_mutated", "no_invented_nodes", "room_count_preserved",
    "room_ids_are_ints", "room_ids_unique", "room_names_present", "room_names_bijective",
    "room_names_order", "room_area_unchanged", "room_polygon_area", "free_space_not_empty",
    "free_space_area_scaled", "free_space_bounds_scaled", "scale_carried",
    "walkable_in_free_space", "adjacency_round_trip", "plan_id_carried",
]


def _wkb(geom):
    try:
        return geom.wkb
    except Exception:
        return (geom.geom_type, tuple(geom.bounds), geom.area)


def snapshot(g):
    """Exact copy of everything make_plan could accidentally change."""
    return {
        "scale": g["scale"],
        "plan_id": g.get("plan_id"),
        "rooms": [(r["id"], r["type"], r["area_m2"], _wkb(r["poly"])) for r in g["rooms"]],
        "free": _wkb(g["free_space"]),
        "adj": {k: list(v) for k, v in g["adjacency"].items()},
        "extra": {k: _wkb(g[k]) for k in ("inner", "walls", "windows") if k in g},
    }


def plan_extension_report():
    """Can contract.Plan carry the extra attributes the proposed adapter attaches?"""
    lines, problems = [], []
    try:
        from panel_routing.contract import Plan
    except Exception as e:
        return [f"could not import panel_routing.contract.Plan: {e!r}"], ["cannot import Plan"]
    params = getattr(Plan, "__dataclass_params__", None)
    frozen = bool(getattr(params, "frozen", False))
    slots = bool(getattr(params, "slots", False)) or hasattr(Plan, "__slots__")
    lines.append(f"Plan is a dataclass: {dataclasses.is_dataclass(Plan)}; frozen={frozen}; slots={slots}")
    if frozen or slots:
        problems.append("Plan is frozen/slotted: extra attributes (scale, room_names, geo) cannot be attached")
        return lines, problems
    p = Plan(rooms=[], devices=[], free_space=None)
    try:
        p.scale, p.room_names, p.geo = 19.5, {0: "living_0"}, {"walls": None}
    except Exception as e:
        problems.append(f"cannot set extra attributes on a Plan: {e!r}")
        return lines, problems
    lines.append("extra attributes can be set on a Plan instance: yes")
    for label, fn in (("copy.copy", copy.copy), ("copy.deepcopy", copy.deepcopy),
                      ("pickle round trip", lambda x: pickle.loads(pickle.dumps(x)))):
        try:
            ok = getattr(fn(p), "room_names", None) == {0: "living_0"}
        except Exception as e:
            ok = False
            problems.append(f"{label} failed on a Plan with extra attributes: {e!r}")
        lines.append(f"extra attributes survive {label}: {'yes' if ok else 'NO'}")
        if not ok:
            problems.append(f"extra attributes are lost by {label}")
    lost = getattr(dataclasses.replace(p), "room_names", None) is None
    lines.append("dataclasses.replace(plan) " + ("DROPS the extra attributes (rebuilds from fields only)" if lost
                                                 else "keeps the extra attributes"))
    if lost:
        problems.append("NOTE: dataclasses.replace(plan, ...) drops scale/room_names/geo; "
                        "nobody on the team should rebuild a Plan that way after make_plan")
    return lines, problems


def check_plan(idx, g, adapter, fail):
    before = snapshot(g)
    try:
        plan = adapter.make_plan(g)
    except Exception as e:
        fail(idx, "make_plan_runs", repr(e))
        return
    if snapshot(g) != before:
        fail(idx, "source_not_mutated", "geometry_result changed during make_plan")

    s = g["scale"]
    rooms_g = g["rooms"]
    if plan.devices:
        fail(idx, "no_invented_nodes", f"{len(plan.devices)} devices present (none may be invented)")

    # ---- rooms: ids, names, order, types ------------------------------------------------
    aligned = len(plan.rooms) == len(rooms_g)
    if not aligned:
        fail(idx, "room_count_preserved", f"{len(plan.rooms)} rooms vs {len(rooms_g)} in geometry")
    ids = [r.id for r in plan.rooms]
    if not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
        fail(idx, "room_ids_are_ints", f"non-int ids: {[i for i in ids if not isinstance(i, int)][:5]}")
    if len(set(ids)) != len(ids):
        dup = [k for k, c in Counter(ids).items() if c > 1]
        fail(idx, "room_ids_unique", f"duplicate ids {dup[:5]}")

    names = getattr(plan, "room_names", None)
    names_ok = False
    if names is None:
        fail(idx, "room_names_present", "plan.room_names is missing (old adapter?)")
    else:
        orig_ids = [r["id"] for r in rooms_g]
        names_ok = (set(names) == set(ids) and len(set(names.values())) == len(names)
                    and sorted(names.values()) == sorted(orig_ids))
        if not names_ok:
            fail(idx, "room_names_bijective",
                 f"room_names has {len(names)} entries / {len(set(names.values()))} distinct values; "
                 f"{len(ids)} rooms; {len(orig_ids)} geometry ids")
    if aligned:
        for i, (r, o) in enumerate(zip(plan.rooms, rooms_g)):
            if names_ok and names.get(r.id) != o["id"]:
                fail(idx, "room_names_order", f"room {i} is named {names.get(r.id)!r}, geometry says {o['id']!r}")
                break
            if r.type != o["type"]:
                fail(idx, "room_names_order", f"room {o['id']}: type {r.type!r} != {o['type']!r}")
                break

    # ---- room areas -----------------------------------------------------------------------
    if aligned:
        for r, o in zip(plan.rooms, rooms_g):
            if r.area != o["area_m2"]:
                fail(idx, "room_area_unchanged", f"{o['id']}: Room.area {r.area} != area_m2 {o['area_m2']}")
                break
        for r, o in zip(plan.rooms, rooms_g):
            if abs(r.polygon.area - r.area) > AREA_TOL_M2:
                fail(idx, "room_polygon_area",
                     f"{o['id']}: polygon {r.polygon.area:.4f} m2 vs area {r.area:.4f} m2 "
                     f"(units mixed? ratio {r.polygon.area / r.area if r.area else float('nan'):.2f})")
                break

    # ---- free space -----------------------------------------------------------------------
    fs_o, fs_m = g["free_space"], plan.free_space
    if fs_m is None or fs_m.is_empty:
        fail(idx, "free_space_not_empty", "free space is empty")
    else:
        want = fs_o.area / s ** 2
        if not math.isclose(fs_m.area, want, rel_tol=REL_TOL, abs_tol=1e-9):
            fail(idx, "free_space_area_scaled", f"{fs_m.area:.6f} m2, expected {want:.6f} m2")
        bad = [(a, b / s) for a, b in zip(fs_m.bounds, fs_o.bounds) if abs(a - b / s) > BOUNDS_TOL_M]
        if bad:
            fail(idx, "free_space_bounds_scaled", f"bounds {tuple(round(v, 4) for v in fs_m.bounds)} "
                 f"vs expected {tuple(round(v / s, 4) for v in fs_o.bounds)}")
        if aligned:
            for r, o in zip(plan.rooms, rooms_g):
                if not o["walkable"] or r.polygon.area <= 0:
                    continue
                try:
                    ratio = r.polygon.intersection(fs_m).area / r.polygon.area
                except Exception as e:
                    fail(idx, "walkable_in_free_space", f"{o['id']}: geometry error {e!r}")
                    break
                if ratio < COVERAGE_MIN:
                    fail(idx, "walkable_in_free_space", f"{o['id']}: only {ratio:.1%} inside free space")
                    break
    plan_scale = getattr(plan, "scale", None)
    if plan_scale is None or not math.isclose(plan_scale, s, rel_tol=1e-12):
        fail(idx, "scale_carried", f"plan.scale = {plan_scale!r}, geometry scale = {s!r}")

    # ---- adjacency round trip ---------------------------------------------------------------
    if names_ok:
        try:
            back = {names[k]: sorted(names[n] for n in v) for k, v in plan.adjacency.items()}
        except KeyError as e:
            fail(idx, "adjacency_round_trip", f"adjacency uses an id with no name: {e}")
        else:
            orig = {k: sorted(v) for k, v in g["adjacency"].items()}
            if back != orig:
                missing = sorted(set(orig) - set(back))[:3]
                changed = [k for k in orig if k in back and back[k] != orig[k]][:3]
                fail(idx, "adjacency_round_trip", f"rooms missing {missing}; neighbours changed for {changed}")
    elif names is not None:
        fail(idx, "adjacency_round_trip", "skipped: room_names is not bijective")

    if g.get("plan_id") is not None and plan.plan_id != str(g["plan_id"]):
        fail(idx, "plan_id_carried", f"plan.plan_id = {plan.plan_id!r}, geometry plan_id = {g['plan_id']!r}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--adapter", default="adapter", help="module to test (default: adapter)")
    ap.add_argument("--pkl", default="ResPlan.pkl")
    ap.add_argument("--n", type=int, default=200, help="how many plans from the start (default 200)")
    ap.add_argument("--max-print", type=int, default=40, help="max failures to list (default 40)")
    args = ap.parse_args()

    sys.path.insert(0, os.getcwd())
    import geometry
    adapter = importlib.import_module(args.adapter)
    print(f"adapter under test : {getattr(adapter, '__file__', args.adapter)}")
    print(f"geometry           : {getattr(geometry, '__file__', 'geometry')}")

    lines, problems = plan_extension_report()
    print("\nPlan compatibility with extra attributes:")
    for ln in lines:
        print("  " + ln)

    with open(args.pkl, "rb") as f:
        plans = pickle.load(f)
    n = min(args.n, len(plans))
    print(f"\ndataset has {len(plans)} plans; testing the first {n}\n")

    failures, load_errors = [], []

    def fail(idx, check, msg):
        failures.append((idx, check, msg))

    for idx in range(n):
        try:
            g = geometry.load_plan(plans[idx])
        except Exception as e:
            load_errors.append((idx, repr(e)))
            continue
        check_plan(idx, g, adapter, fail)

    tested = n - len(load_errors)
    print(f"FAILURES (first {args.max_print} of {len(failures)}):")
    for idx, check, msg in failures[: args.max_print]:
        print(f"  plan {idx:>5}  {check:<26} {msg}")
    if load_errors:
        print(f"\ngeometry.load_plan raised on {len(load_errors)} plans (geometry problem, not the adapter):")
        for idx, msg in load_errors[:10]:
            print(f"  plan {idx:>5}  {msg}")

    by_check = Counter(c for _, c, _ in failures)
    print("\nSUMMARY")
    print(f"  plans requested        : {n}")
    print(f"  plans tested           : {tested}")
    print(f"  plans failing >= 1 chk : {len({i for i, _, _ in failures})}")
    print(f"  total failures         : {len(failures)}")
    print("  failures per check:")
    for c in CHECKS:
        print(f"    {c:<26} {by_check.get(c, 0)}")
    if problems:
        print("\nPlan compatibility concerns:")
        for p in problems:
            print("  - " + p)
    ok = not failures and not load_errors
    print("\nRESULT:", "ALL CHECKS PASSED" if ok else "FAILURES FOUND (see above)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
