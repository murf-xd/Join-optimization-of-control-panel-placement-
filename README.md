# Honeywell — Panel Placement and Cable Routing

Automated electrical panel placement and closed-loop cable routing for the Honeywell 48-hour hackathon.

## Assumptions

| Item | Value | Reason |
|---|---|---|
| Minimum open-passage width | 0.7 m | Just below the narrowest measured door; sensitivity testing is documented separately. |
| Rescue minimum | 0.4 m | Used only to reconnect an otherwise disconnected eligible room. |
| Minimum clear gate width | 0.2 m | Narrower openings are treated as blocked. |
| Windows | Barriers | Cables must not pass through windows. |
| Hub clearance from windows | 0.5 m | Conservative assumption; the statement specifies wall clearance. |
| Balcony | External | Excluded from the interior walkable space. |
| Bathroom | Walkable, no device | Cables may pass through it; territory connectivity rules need confirmation. |

## Shared Python Modules

- `geometry_v2.py` — floor-plan geometry and room connectivity.
- `contract_v2.py` — shared data structures and constraints.
- `adapter.py` — converts input plans into the shared `Plan` format.
- `check_all.py` — geometry and connectivity checks.
- `check_adapter.py` — adapter and node-placement checks.

## Units

All geometry in the shared `Plan` representation uses plan metres. Coordinate-frame conversion is handled at the output boundary.

## Notes

Node positions are placeholders until the organisers' fixed-point input requirements are confirmed. Verify all assumptions against the official problem statement and sample plans.
