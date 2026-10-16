from dataclasses import dataclass
from unittest.mock import patch
from pipeline import refine_hubs

@dataclass(frozen=True)
class Panel:
    panel_id: str
    panel_xy: tuple


def test_refinement_scores_full_configuration():
    panels = [Panel('H1',(0,0)), Panel('H2',(10,0))]
    calls=[]
    def fake_route(plan, current):
        calls.append(tuple(p.panel_id for p in current))
        assert len(current)==2
        return []
    def fake_score(plan,current,loops,pass_through):
        return {'valid':True,'J':100-current[0].panel_xy[0],'area_gap':0}
    with patch('pipeline.hub_options',side_effect=lambda plan,p: [(0,0),(2,0)] if p.panel_id=='H1' else [(10,0)]), patch('pipeline.score',side_effect=fake_score):
        result=refine_hubs(None,panels,fake_route)
    assert result[0].panel_xy==(2,0)
    assert all(ids==('H1','H2') for ids in calls)


def test_refinement_does_not_replace_valid_with_invalid():
    panels=[Panel('H1',(0,0)),Panel('H2',(10,0))]
    def fake_score(plan,current,loops,pass_through):
        return {'valid':current[0].panel_xy==(0,0),'J':0 if current[0].panel_xy==(2,0) else 5,'area_gap':0}
    with patch('pipeline.hub_options',side_effect=lambda plan,p: [(2,0)] if p.panel_id=='H1' else [(10,0)]), patch('pipeline.score',side_effect=fake_score):
        result=refine_hubs(None,panels,lambda plan,ps: [])
    assert result[0].panel_xy==(0,0)
