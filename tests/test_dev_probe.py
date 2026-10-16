"""Regression: dev probes must lie inside free_space (plan 24: probes in R02/R03 were outside).
Needs shapely, so it is skipped where shapely is missing (run it on the Mac)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest

shapely = pytest.importorskip("shapely")
from shapely.geometry import box

from panel_routing.contract import Plan, Room
from run import PipelineError, dev_probe_devices


def make(free):
    rooms = [Room(0, "living", box(0, 0, 4, 4), 16.0), Room(1, "bedroom", box(5, 0, 9, 4), 16.0)]
    plan = Plan(rooms, [], None, adjacency={0: [1], 1: [0]}, plan_id="SYNTHETIC_PROBE")
    plan.free_space = free
    return plan


def test_probe_lies_inside_the_routable_part_of_the_room():
    # room 1 is mostly outside free space (only x 5..6 is routable)
    plan = make(box(0, 0, 4, 4).union(box(4, 1, 5, 2)).union(box(5, 0, 6, 4)))
    for d in dev_probe_devices(plan):
        assert plan.free_space.covers(shapely.geometry.Point(d.xy)), d


def test_room_with_no_free_space_is_a_clear_error():
    plan = make(box(0, 0, 4, 4))
    with pytest.raises(PipelineError, match="no free space"):
        dev_probe_devices(plan)
