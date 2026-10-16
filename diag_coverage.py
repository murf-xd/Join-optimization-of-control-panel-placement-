import pickle
import sys
import geometry

idx = int(sys.argv[1])

with open("ResPlan.pkl", "rb") as f:
    raw = pickle.load(f)[idx]

g = geometry.load_plan(raw)
scale = g["scale"]
free = g["free_space"]
inner = g["inner"]
windows = g["windows"]

inner_ok = inner.difference(windows) if not windows.is_empty else inner
walk = [r for r in g["rooms"] if r["walkable"]]

print(f"Plan index: {idx} | ID: {g.get('plan_id')} | scale: {scale:.3f}")
print(
    f"Inner: {len(getattr(inner, 'geoms', [inner]))} part(s), "
    f"{inner.area / scale**2:.2f} m² | raw area: {raw.get('area')} m²"
)
print(f"Sum of walkable room areas: {sum(r['area_m2'] for r in walk):.2f} m²")
print("Rooms outside main free space:",
      g["diagnostics"]["rooms_outside_main_free_space"])

print("\nRoom         Area m²   Outside   Windows   Lost free   Expected   Residual")
for r in walk:
    p = r["poly"]
    if p.area == 0:
        continue

    outside = p.difference(inner).area / p.area
    in_win = p.intersection(windows).area / p.area if not windows.is_empty else 0.0
    lost = p.difference(free).area / p.area
    expected = p.difference(inner_ok).area / p.area
    residual = lost - expected

    print(
        f"{r['id']:<12} {r['area_m2']:7.2f} "
        f"{outside:8.1%} {in_win:8.1%} {lost:10.1%} "
        f"{expected:9.1%} {residual:9.2%}"
    )
