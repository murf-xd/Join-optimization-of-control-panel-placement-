"""Person B v2 pipeline: evaluate feasible candidates with real routing cost."""
from dataclasses import dataclass,field,replace
from typing import Any
from assign import assign_candidates
from validator import score
from v2_bridge import hub_options

@dataclass
class Solution:
    panels:list
    loops:list=field(default_factory=list)
    result:dict=field(default_factory=dict)

def refine_hubs(plan, panels, route, max_positions=12, pass_through=()):
    """Coordinate-descent hub search, scoring complete multi-hub designs."""
    out = list(panels)

    def evaluate(candidate_panels):
        try:
            candidate_loops = route(plan, candidate_panels)
            result = score(plan, candidate_panels, candidate_loops, pass_through)
            if not result['valid']:
                return None
            return (result['J'], result.get('area_gap', 0.0))
        except Exception:
            return None

    best_score = evaluate(out)
    # If the baseline is invalid, still search for a valid alternative.
    for i, panel in enumerate(out):
        winner = None
        for xy in hub_options(plan, panel)[:max_positions]:
            trial_panels = list(out)
            trial_panels[i] = replace(panel, panel_xy=xy)
            candidate_score = evaluate(trial_panels)
            if candidate_score is None:
                continue
            key = (*candidate_score, xy)
            if winner is None or key < winner[0]:
                winner = (key, trial_panels[i], candidate_score)
        if winner is not None and (best_score is None or winner[2] < best_score):
            out[i] = winner[1]
            best_score = winner[2]
    return out

def solve(plan,route=None,limit=20,pass_through=(),refine=True,n_restarts=30,seed=0,max_positions=12):
    candidates=assign_candidates(plan,limit=limit,n_restarts=n_restarts,seed=seed,pass_through=pass_through)
    if not candidates:
        return Solution([] ,[], {'valid':not plan.eligible_rooms,'problems':[] if not plan.eligible_rooms else ['no candidates'],'H':0,'J':0.0})
    if route is None:return Solution(candidates[0])
    best=None
    for panels in candidates:
        if refine:panels=refine_hubs(plan,panels,route,max_positions,pass_through)
        try:
            loops=route(plan,panels)
            result=score(plan,panels,loops,pass_through)
        except Exception as exc:
            loops=[]
            result={'valid':False,'problems':[f'router error: {exc}'],'H':len(panels),'J':float('inf'),'area_gap':float('inf')}
        key=(not result['valid'],result['H'],round(result['J'],6),round(result.get('area_gap',0),6))
        if best is None or key<best[0]:best=(key,Solution(panels,loops,result))
    return best[1]
