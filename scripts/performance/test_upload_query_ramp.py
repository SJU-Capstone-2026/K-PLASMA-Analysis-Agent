import unittest
from types import SimpleNamespace
from upload_query_benchmark import trial_label,upload_deadline,UploadObservationTimeout
from upload_query_ramp import stop_reason,selected_rates,confirmation_schedule

def row(rate=20,p95=3,acquire=0,pending=0,dropped=0,achieved=None):
    return dict(configuredRate=rate,lookup=dict(client_ms={'p95':p95},worker=dict(db_acquire_ms={'p95':acquire},pending_samples=pending),
        errors=0,count=100,unmatched_clients=[],all_invalid_payloads=0,dropped_iterations=dropped,achieved_start_rate=rate if achieved is None else achieved))

class RampTest(unittest.TestCase):
    def test_connection_contention_requires_both_acquisition_and_pool_evidence(self):
        self.assertIsNone(stop_reason(row(acquire=6)))
        self.assertEqual(stop_reason(row(acquire=6,pending=3)),'connection_contention')
    def test_chooses_knee_and_previous_without_using_c_results(self):
        self.assertEqual(selected_rates([row(20),row(50,p95=55)])[0],[20,50])
        self.assertEqual(selected_rates([row(20,p95=55)])[0],[5,20])
        self.assertEqual(selected_rates([row(400)])[0],[400])
    def test_arrival_failure_is_not_a_successful_load_point(self):
        self.assertEqual(selected_rates([row(20),row(50,dropped=5)])[0],[20])
        self.assertEqual(stop_reason(row(achieved=18)),'arrival_limit')
    def test_comparison_has_three_independent_repeats_per_rate_variant(self):
        schedule=confirmation_schedule([20,50])
        self.assertEqual(len(schedule),12)
        for variant in ['B','C']:
            for rate in [20,50]:self.assertEqual({i for v,i,r in schedule if v==variant and r==rate},{1,2,3})
    def test_output_names_distinguish_rates_and_phases(self):
        a=SimpleNamespace(variant='B',pool=10,scenario='combined',measured=True,index=1,timing_enabled=True,stage='discovery',rate=20)
        name=trial_label(a);a.rate=50;self.assertNotEqual(name,trial_label(a))
        a.rate=20;a.stage='confirm';self.assertNotEqual(name,trial_label(a))
    def test_upload_deadline_interrupts_blocking_io(self):
        import time
        with self.assertRaises(UploadObservationTimeout):
            with upload_deadline(.01):time.sleep(.2)

    def test_zero_deadline_cannot_silently_disable_timeout(self):
        with self.assertRaises(ValueError):
            with upload_deadline(0):pass

    def test_existing_server_does_not_trigger_database_cleanup(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import upload_query_ramp as ramp
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);art=root/'artifacts';art.mkdir()
            for v in ['B','C']:(art/(v+'.jar')).write_bytes(v.encode())
            args=SimpleNamespace(container='kplasma-upload-benchmark-test',artifacts=art,fixture_root=root/'fixture',
                output=root/'result',java='unused',server_port=18552,db_port=15452)
            hashes=['3570164bede4c955b1f8b190a4c2f43669c77e6aeff06bc112a8f8605d2e6f38',
                    'b3e06de0a0b6948cba22f3f1ab49b864279254a278147f8a74bcc0721a880b92']
            digest=[SimpleNamespace(hexdigest=lambda value=h:value) for h in hashes]
            with patch.object(ramp.hashlib,'sha256',side_effect=digest), \
                 patch.object(ramp.subprocess,'run',return_value=SimpleNamespace(stdout='existing-server')), \
                 patch.object(ramp.u,'sql') as sql,patch.object(ramp.u,'restore_seed') as restore:
                with self.assertRaisesRegex(RuntimeError,'already occupied'):ramp.run(args)
                sql.assert_not_called();restore.assert_not_called()

if __name__=='__main__':unittest.main()
