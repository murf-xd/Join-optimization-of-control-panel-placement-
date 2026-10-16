"""Node generator tests (synthetic rooms; need shapely, skipped where it is missing)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest

shapely = pytest.importorskip("shapely")
from shapely.geometry import Point, box

from nodes import NodeGenerationError, generate_nodes
from panel_routing.contract import Plan, Room


def make(rooms, walls, windows=None, free=None):
    plan = Plan(rooms, [], None, adjacency={}, plan_id="SYNTHETIC_NODES")
    plan.free_space = free if free is not None else box(-1, -1, 30, 30)
    plan.geo = {"walls": walls, "windows": windows if windows is not None else box(100, 100, 101, 101)}
    return plan


def test_node_is_inside_room_and_clear_of_walls():
    room = Room(0, "living", box(0, 0, 6, 5), 30.0)
    walls = box(-1, -1, 0, 6).union(box(6, -1, 7, 6)).union(box(-1, -1, 7, 0)).union(box(-1, 5, 7, 6))
    plan = make([room], walls)
    devs, rep = generate_nodes(plan)
    p = Point(devs[0].xy)
    assert room.polygon.covers(p) and walls.distance(p) >= 0.5
    assert rep[0]["clearance_m"] >= 0.5


def test_deterministic():
    room = Room(0, "bedroom", box(0, 0, 4, 3.4), 13.6)
    walls = box(-1, -1, 0, 5).union(box(4, -1, 5, 5)).union(box(-1, -1, 5, 0)).union(box(-1, 3.4, 5, 4.4))
    a = generate_nodes(make([room], walls))[0][0].xy
    b = generate_nodes(make([room], walls))[0][0].xy
    assert a == b


def test_window_clearance_is_respected():
    room = Room(0, "kitchen", box(0, 0, 5, 4), 20.0)
    walls = box(-1, -1, 0, 5).union(box(5, -1, 6, 5)).union(box(-1, -1, 6, 0)).union(box(-1, 4, 6, 5))
    window = box(1, 0, 4, 0.3)       # window strip inside the room's lower edge
    plan = make([room], walls, windows=window)
    p = Point(generate_nodes(plan)[0][0].xy)
    assert window.distance(p) >= 0.5


def test_room_too_small_is_reported_not_forced():
    tiny = Room(0, "storage", box(0, 0, 0.9, 0.9), 0.81)
    big = Room(1, "living", box(5, 0, 11, 5), 30.0)
    walls = box(-1, -1, 0, 6).union(box(0.9, -1, 1.9, 6)).union(box(-1, -1, 2, 0)).union(box(-1, 0.9, 2, 1.9))
    plan = make([tiny, big], walls)
    with pytest.raises(NodeGenerationError) as e:
        generate_nodes(plan)
    assert [r for r, _ in e.value.failures] == [0]      # the tiny room is named; the big room is not dropped silently


def test_room_with_no_free_space_is_reported():
    room = Room(0, "living", box(0, 0, 6, 5), 30.0)
    plan = make([room], box(100, 100, 101, 101), free=box(50, 50, 60, 60))
    with pytest.raises(NodeGenerationError, match="no free space"):
        generate_nodes(plan)
