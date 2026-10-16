# Person B: hub assignment, scoring, pipeline

Rules (problem statement): each hub serves at most 100 m2 and 5 nodes, in one connected zone;
ranking is fewest hubs, then lowest cost J = L + 5X + O + 0.5B, then smaller area gap.

| File | What it does |
|---|---|
| `contract_merged.py` | Shared data shapes (`Plan`, `PanelAssignment`, `Loop`) and the limits |
| `assign.py` | `assign()` / `assign_candidates()`: exact search for <= 10 eligible rooms, greedy fallback |
| `validator.py` | `score()`: hard-rule checks plus the metrics L, X, O, B, J (1 mm tolerance) |
| `pipeline.py` | `solve(plan, route)`: routes each candidate grouping, refines hub spots, keeps the cheapest |
| `stub_route.py` | Stand-in router (ignores walls). Person C replaces it, same `route(plan, panels)` signature |
| `benchmark.py` | `python benchmark.py --n 200` summary: validity, hubs vs lower bound, cost J, time |
| `toy_plan.py` | Fake houses for tests, no shapely needed |

## Run

    pip install shapely pytest
    python run_tests.py test_assign test_validator test_pipeline     # expect 51 passed
    python run_tests.py --skip-geom test_assign test_validator test_pipeline   # without shapely geometry tests
    python benchmark.py --n 200 --seed 1

## Switches that need the organisers' answer

- Pass-through rooms: `PASS_THROUGH_TYPES` in `assign.py` (empty = zones join only through direct doors).
- Hub on a node: hubs sit on a node point; `validator.py` accepts a zero-length ring when the hub is on every node it serves.

Tested on toy and random plans only, not on real ResPlan files.
