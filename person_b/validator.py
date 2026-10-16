"""Person B v2 scoring, with strict capacity and hub-zone validation."""
from contract_v2 import MAX_HUB_AREA_M2, MAX_NODES_PER_HUB, is_contiguous
from v2_bridge import convert, to_old, valid_hub
import legacy_validator as lv

def assignment_problems(plan,panels,pass_through=()):
    problems=[]
    room_ids=[r for p in panels for r in p.room_ids]
    node_ids=[n for p in panels for n in p.node_ids]
    if sorted(room_ids)!=sorted(r.id for r in plan.eligible_rooms): problems.append('eligible rooms must be assigned exactly once')
    if sorted(node_ids)!=sorted(n.id for n in plan.nodes): problems.append('nodes must be assigned exactly once')
    if len({p.panel_id for p in panels})!=len(panels): problems.append('hub IDs must be unique')
    for p in panels:
        if any(r not in {x.id for x in plan.eligible_rooms} for r in p.room_ids):
            problems.append(f'{p.panel_id}: ineligible or unknown room')
            continue
        area=sum(plan.room(r).area_m2 for r in p.room_ids)
        if area>MAX_HUB_AREA_M2+1e-6 or len(p.node_ids)>MAX_NODES_PER_HUB:
            problems.append(f'{p.panel_id}: capacity violation ({area:.2f} m2, {len(p.node_ids)} nodes)')
        if not is_contiguous(plan,p.room_ids,via_passthrough=bool(pass_through)):
            problems.append(f'{p.panel_id}: disconnected zone')
        for n in p.node_ids:
            if n not in {x.id for x in plan.nodes} or plan.node(n).room_id not in p.room_ids:
                problems.append(f'{p.panel_id}: invalid node assignment {n}')
        if not valid_hub(plan,p,p.panel_xy): problems.append(f'{p.panel_id}: hub outside valid hub_zone or too close to obstacles')
    return problems

def _legacy(plan,panels,loops):
    op,rm,nm,_,_=convert(plan)
    pp=[to_old(p,rm,nm) for p in panels]
    ll=[]
    for l in loops:
        pid=int(str(l.panel_id)[1:])-1 if str(l.panel_id).startswith('H') else int(l.panel_id)
        ll.append(lv.Loop(pid,[nm[n] for n in l.order],list(l.route_coords)))
    return op,pp,ll

def metrics(plan,panels,loops):
    op,pp,ll=_legacy(plan,panels,loops)
    return lv.metrics(op,pp,ll)

def loop_problems(plan,panels,loops):
    try:
        op,pp,ll=_legacy(plan,panels,loops)
        return lv.loop_problems(op,pp,ll)
    except (KeyError,ValueError,TypeError,AttributeError) as exc:
        return [f'invalid loop structure: {exc}']

def score(plan,panels,loops,pass_through=()):
    problems=assignment_problems(plan,panels,pass_through)+loop_problems(plan,panels,loops)
    try: result=metrics(plan,panels,loops)
    except (KeyError,ValueError,TypeError,AttributeError) as exc:
        problems.append(f'cannot calculate metrics: {exc}')
        result={'H':len(panels),'L':float('inf'),'X':0,'O':0,'B':0,'J':float('inf'),'area_gap':float('inf')}
    return {'valid':not problems,'problems':problems,**result}
