import pickle
import unittest
from pathlib import Path
from assign import assign, assign_candidates
from pipeline import solve
from validator import assignment_problems, score
from v2_bridge import Loop

class TestV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=Path(__file__).resolve().parent/'sample_plans.pkl'
        cls.plans=pickle.loads(path.read_bytes())
    def test_sample_assignments(self):
        for plan in self.plans.values():
            panels=assign(plan)
            self.assertFalse(assignment_problems(plan,panels),plan.plan_id)
            self.assertTrue(all(isinstance(p.panel_id,str) for p in panels))
            self.assertTrue(all(isinstance(n,str) for p in panels for n in p.node_ids))
    def test_determinism(self):
        for plan in self.plans.values():
            self.assertEqual(assign(plan),assign(plan))
    def test_candidates(self):
        for plan in self.plans.values():
            for candidate in assign_candidates(plan,limit=4):
                self.assertEqual(assignment_problems(plan,candidate),[])
    def test_no_router(self):
        for plan in self.plans.values():
            self.assertFalse(solve(plan).loops)
    def test_invalid_route_detected(self):
        plan=self.plans[0]
        panels=assign(plan)
        loops=[Loop(p.panel_id,list(p.node_ids),[p.panel_xy,p.panel_xy]) for p in panels]
        self.assertFalse(score(plan,panels,loops)['valid'])
if __name__=='__main__':unittest.main()
