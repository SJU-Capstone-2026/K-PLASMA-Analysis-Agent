import copy
import unittest
from analyze_upload_dispatch import reasons
from upload_worker_benchmark import schedule

class DispatchAuditTest(unittest.TestCase):
    def sample(self):
        return dict(count=100,unique_vus=100,errors=0,scheduled_epoch_ms=[1000],
            lateness_ms=dict(min=0,max=1,mean=.5),call_spread_ms=1,
            active_workers=dict(mean=4),upload_connections=dict(mean=4),
            query_mix={'v':100},query_by_vu={'1':'v'},elapsedMs=dict(mean=20))

    def test_queue_time_is_an_outcome_not_an_exclusion_rule(self):
        b=self.sample();c=copy.deepcopy(b);c['elapsedMs']['mean']=10000
        c['upload_connections']['mean']=0
        self.assertEqual(reasons(b,c,4,True),[])

    def test_late_load_and_inactive_workers_are_separate_failures(self):
        b=self.sample();c=copy.deepcopy(b);c['lateness_ms']=dict(min=54,max=56,mean=55)
        self.assertIn('C: dispatch lateness',reasons(b,c,4))
        c=self.sample();c['active_workers']['mean']=0
        self.assertIn('C: insufficient active upload workers',reasons(b,c,4))

    def test_configured_pairs_have_equal_runs_and_alternate_order(self):
        self.assertEqual(schedule((4,),3),[(4,'B',1),(4,'C',1),(4,'C',2),(4,'B',2),(4,'B',3),(4,'C',3)])
        self.assertEqual(schedule((8,),1,4),[(8,'C',4),(8,'B',4)])
        for workers,repeats in [((4,4),3),((3,),3),((4,),0)]:
            with self.assertRaises(ValueError):schedule(workers,repeats)

if __name__=='__main__':unittest.main()
