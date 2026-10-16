import pickle
import sys

import geometry

idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0

with open("ResPlan.pkl", "rb") as f:
    raw = pickle.load(f)[idx]

res = geometry.load_plan(raw)
scale = res["scale"]

free_space_m = geometry.to_metres(res["free_space"], scale)

print(f"Plan index: {idx}")
print(f"Plan ID: {res.get('plan_id', raw.get('id', 'unknown'))}")
print(f"Scale: {scale:.3f} drawing units per metre")
print(
    f"Wall depth: {res['wall_depth']:.2f} drawing units "
    f"= {res['wall_depth'] / scale:.3f} m"
)
print("Free-space bounds in drawing units:",
      [round(v, 2) for v in res["free_space"].bounds])
print("Free-space bounds in metres:",
      [round(v, 2) for v in free_space_m.bounds])

print("\nEligible rooms:")
for room in res["rooms"]:
    if room["eligible"]:
        polygon_m = geometry.to_metres(room["poly"], scale)
        print(
            f"{room['id']}: reported area={room['area_m2']:.3f} m², "
            f"polygon area={polygon_m.area:.3f} m²"
        )

print("\nDoor widths in metres:")
print([
    round(g["width_m"], 3)
    for g in res["gates"]
    if g["kind"] == "door"
])