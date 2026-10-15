import json
import shutil
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from upload_query_benchmark import load_configuration, trial_label
from upload_query_ramp import user_schedule

class UserLoadTest(unittest.TestCase):
    def test_fixed_users_are_distinct_from_request_rate(self):
        a=SimpleNamespace(load_model='users',vus=100,rate=5)
        result=load_configuration(a)
        self.assertEqual(result['configuredVUs'],100)
        self.assertEqual(result['configuredMeanRate'],20)
        self.assertIsNone(result['configuredRate'])
        for invalid in [0,101]:
            a.vus=invalid
            with self.assertRaises(ValueError):load_configuration(a)

    def test_labels_do_not_mix_users_with_arrival_rate(self):
        a=SimpleNamespace(variant='B',pool=10,scenario='combined',measured=True,index=1,timing_enabled=True,
            stage='confirm',rate=5,load_model='users',vus=10)
        before=trial_label(a);a.vus=20
        self.assertNotEqual(before,trial_label(a));a.load_model='arrival'
        self.assertNotEqual(before,trial_label(a))

    def test_user_comparison_has_two_repeats_at_every_requested_level(self):
        schedule=user_schedule()
        self.assertEqual(len(schedule),20)
        for variant in ['B','C']:
            for vus in [1,10,20,50,100]:self.assertEqual({i for v,i,n in schedule if v==variant and n==vus},{1,2})

    @unittest.skipUnless(shutil.which('node'),'Node required for scheduling checks')
    def test_schedules_preserve_volume_and_make_burst_explicit(self):
        helper=(Path(__file__).parent/'upload_query_user_schedule.mjs').resolve().as_uri()
        code=f'''import assert from 'node:assert/strict';
import {{requestSlot}} from {json.dumps(helper)};
for (const vus of [1,10,20,50,100]) {{
  for (let vu=1;vu<=vus;vu++) {{
    const slots=Array.from({{length:10}},(_,i)=>requestSlot(i,i*5000+2,5000));
    assert.equal(new Set(slots).size,10);
    assert.deepEqual(slots,Array.from({{length:10}},(_,i)=>i));
  }}
}}
assert.equal(requestSlot(1,17000,5000),3);
assert.equal(requestSlot(4,17000,5000),4);
console.log('schedule checks passed');'''
        result=subprocess.run(['node','--input-type=module','-e',code],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

if __name__=='__main__':unittest.main()
