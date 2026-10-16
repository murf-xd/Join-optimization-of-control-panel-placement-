"""Person B v2 assignment; preserves legacy exact/greedy search and original string IDs."""
from dataclasses import replace
from typing import Iterable
from contract_v2 import Plan
from v2_bridge import PanelAssignment, convert, to_public, hub_options
import legacy_assign

PASS_THROUGH_TYPES=frozenset()

def assign_candidates(plan:Plan,limit=20,n_restarts=30,seed=0,dist=None,pass_through:Iterable[str]=PASS_THROUGH_TYPES):
    old,_,_,rr,rn=convert(plan)
    groups=legacy_assign.assign_candidates(old,limit=limit,n_restarts=n_restarts,seed=seed,dist=dist,pass_through=pass_through)
    result=[]
    for group in groups:
        panels=[to_public(p,rr,rn) for p in group]
        for i,p in enumerate(panels):
            options=hub_options(plan,p)
            if options:
                xy=p.panel_xy if tuple(p.panel_xy) in options else min(options,key=lambda x:sum(abs(x[0]-plan.node(n).xy[0])+abs(x[1]-plan.node(n).xy[1]) for n in p.node_ids))
                panels[i]=replace(p,panel_xy=xy)
            else:
                panels[i].warnings.append('NO_VALID_HUB_POINT: hub_zone/free-space clearance not satisfied')
        result.append(panels)
    return result

def assign(plan:Plan,n_restarts=30,seed=0,dist=None,pass_through=PASS_THROUGH_TYPES):
    candidates=assign_candidates(plan,limit=1,n_restarts=n_restarts,seed=seed,dist=dist,pass_through=pass_through)
    return candidates[0] if candidates else []
