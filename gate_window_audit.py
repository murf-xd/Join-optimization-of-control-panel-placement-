#!/usr/bin/env python3
"""gate_window_audit.py -- DEV_ONLY_NOT_OFFICIAL read-only audit: do WINDOW polygons overlap usable gates in the RAW data?

    python gate_window_audit.py --n 200 [--detail 25]  > out_dev/DEV_ONLY_NOT_OFFICIAL_gatewin.txt

Works on geometry.load_plan output in drawing units (raw door/window polygons, no adapter, no routing).
Question it answers: is window-over-door a one-off (plan 25) or systematic, and does it happen on exterior
walls (window next to the front door / balcony) or on interior doors? That decides whether the rule is
'data quirk' or 'by design' -- it does NOT decide the rule; Person A / organisers do.
"""
import argparse
import math
import os
import pickle
import sys
from collections import Counter

sys.path.insert(0, os.getcwd())
import geometry
from shapely.geometry import LineString

STAMP = "DEV_ONLY_NOT_OFFICIAL"


def audit(g):
    sc, win, inner = g["scale"], g["windows"], g["inner"]
    out = []
    for k, gate in enumerate(g["gates"]):
        poly, seg = gate.get("poly"), gate["segment"]
        if poly is None or poly.is_empty:
            continue
        frac_poly = poly.intersection(win).area / poly.area if win and not win.is_empty else 0.0
        frac_line = seg.intersection(win).length / seg.length if seg.length and not win.is_empty else 0.0
        ext = inner.boundary.distance(seg) / sc if not inner.is_empty else None
        out.append(dict(k=k, kind=gate.get("kind"), usable=gate.get("usable"), width_m=gate.get("width_m"),
                        frac_poly=frac_poly, frac_line=frac_line, to_exterior_m=ext,
                        a=gate.get("room_a"), b=gate.get("room_b")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pkl", default="ResPlan.pkl")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--detail", type=int, default=25)
    a = ap.parse_args()
    with open(a.pkl, "rb") as f:
        data = pickle.load(f)
    print(f"{STAMP}: read-only audit of raw gate/window overlap; no official meaning\n")
    hit, total, by_kind, ext_hist, plans = 0, 0, Counter(), Counter(), []
    for i in range(min(a.n, len(data))):
        try:
            g = geometry.load_plan(data[i])
        except Exception as e:
            print(f"plan {i}: load failed {type(e).__name__}: {e}")
            continue
        rows = [r for r in audit(g) if r["usable"]]
        total += len(rows)
        bad = [r for r in rows if r["frac_line"] > 0.5]
        if bad:
            plans.append(i)
        for r in bad:
            hit += 1
            by_kind[r["kind"]] += 1
            ext_hist["<=0.5 m from outer boundary" if (r["to_exterior_m"] or 9) <= 0.5 else "interior"] += 1
        if i == a.detail:
            print(f"--- detail plan {i}: all usable gates ---")
            for r in rows:
                print("  ", {k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()})
            gt = next((r for r in rows if r["frac_line"] > 0.5), None)
            if gt:
                gate, win = g["gates"][gt["k"]], g["windows"]
                print(f"  raw door poly bounds (drawing units): {tuple(round(v, 2) for v in gate['poly'].bounds)}")
                for w in getattr(win, "geoms", [win]):
                    if w.intersects(gate["poly"].buffer(1)):
                        print(f"  window part bounds: {tuple(round(v, 2) for v in w.bounds)} "
                              f"area={w.area:.2f}  door area={gate['poly'].area:.2f}  "
                              f"overlap={w.intersection(gate['poly']).area:.2f}")
    print(f"\nusable gates audited: {total}; with >50% of the gate line covered by a window: {hit} "
          f"in {len(plans)} plans")
    print("by gate kind:", dict(by_kind), " location:", dict(ext_hist))
    print("plan indexes:", plans[:60])


if __name__ == "__main__":
    main()
