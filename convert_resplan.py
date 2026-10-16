import json
import pickle
from pathlib import Path

import networkx as nx
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry


def convert(obj):
    if isinstance(obj, BaseGeometry):
        return mapping(obj)

    if isinstance(obj, nx.Graph):
        return convert(nx.node_link_data(obj, edges="links"))

    if isinstance(obj, dict):
        return {str(k): convert(v) for k, v in obj.items()}

    if isinstance(obj, (list, tuple)):
        return [convert(v) for v in obj]

    if hasattr(obj, "item"):
        return obj.item()

    return obj


with open(Path.home() / "Downloads/ResPlan.pkl", "rb") as f:
    plans = pickle.load(f)

plan = convert(plans[0])

Path("resplan_json").mkdir(exist_ok=True)

with open("resplan_json/plan_0.json", "w") as f:
    json.dump(plan, f, indent=2)

print("Created resplan_json/plan_0.json")
