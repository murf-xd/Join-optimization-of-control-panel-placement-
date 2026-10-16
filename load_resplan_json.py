import json
from shapely.geometry import shape
from geometry import load_plan

with open("resplan_json/plan_0.json") as f:
    raw = json.load(f)

for key, value in raw.items():
    if isinstance(value, dict) and value.get("type") in (
        "Polygon", "MultiPolygon", "GeometryCollection"
    ):
        raw[key] = shape(value)

result = load_plan(raw)

print("Plan:", result["plan_id"])
print("Rooms:", len(result["rooms"]))
print("Scale:", result["scale"])
print("Warnings:", result["warnings"])
