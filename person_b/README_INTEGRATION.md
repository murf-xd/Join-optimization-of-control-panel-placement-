# Person B — contract_v2 integration

This package uses Person A's `contract_v2.py` unchanged. Public APIs:

```python
from assign import assign, assign_candidates
panels = assign(plan)   # contract_v2.Plan -> list[v2_bridge.PanelAssignment]
from pipeline import solve
solution = solve(plan, route=routing_api.route, limit=5, refine=False)
from validator import assignment_problems, loop_problems, score
```

`PanelAssignment` fields: `panel_id` (`H1`...), `panel_xy` (plan metres), `room_ids` (original v2 strings), `node_ids` (original v2 strings), `warnings`. Aliases: `device_ids`, `hub_id`, `assigned_rooms`, `assigned_nodes`. No IDs are renumbered externally. Internally, the original exact/greedy partition algorithm runs through `v2_bridge.py` using integer IDs. The original files remain as `legacy_*` and `contract_merged.py` for reference.

Capacity is 100 m2 and 5 nodes; violations are **invalid**, even if warnings are present. Default zone connectivity uses assigned eligible rooms only. `pass_through=('bathroom','stair')` is available, but needs organiser clarification and the validator currently interprets any nonempty pass_through as all walkable excluded rooms, so **use default strict mode for official scoring**.

Hub candidates are node coordinates when valid plus representative points from assigned rooms' `hub_zone`. Invalid hub locations are warned and rejected by the validator. A hub coinciding with a node remains permitted when valid; the router must support that case or use the alternative candidate positions. Candidate refinement checks single-ring validity, but cannot fully optimize inter-ring crossings; complete candidates are ranked by validity, hub count, J, area gap.

## Tests

```bash
python3 -m pip install shapely
python3 -m unittest -v test_v2_integration
```

Five v2 integration tests run against six sample plans. **These plans have development placeholder nodes, not organiser-provided fixed node coordinates.** Old unit tests are in `legacy_tests/` and should be run against the original pre-v2 package, not the new facade. This archive does not include Person C's router. No end-to-end real-router compatibility or official JSON schema has been verified.

## Routing compatibility

C's route function should accept a `contract_v2.Plan` and panels with the above fields, and return loop objects with `panel_id`, `order` (list of original node IDs) and `route_coords` (flat closed list of XY points). If C's loop type differs (e.g. per-leg route segments), adapt that return shape before calling `score`; do not silently assume compatibility.

For time-sensitive integration, start with `solve(plan, routing_api.route, limit=1, refine=False)` and increase `limit`/enable `refine` after measuring latency. `sample_plans.pkl` is included for smoke tests. Final output origin/axis conversion belongs to A/C at JSON output edge, not B.
