import json
import tempfile
import unittest
from pathlib import Path
import generate_upload_fixture as fixture
import upload_benchmark as bench

class UploadBenchmarkContractTest(unittest.TestCase):
    def test_all_150_conditions_are_unique_and_bias_off_is_retained(self):
        profile=fixture.default_profile(150)
        self.assertEqual(len({(r["pressure"],r["source"],r["bias"]) for r in profile}),150)
        self.assertEqual(sum(r["bias"]==0 for r in profile),25)

    def test_padding_preserves_numeric_rows_and_exact_volume(self):
        result=fixture.padded("# header\n",["0 1\n","1 1\n"],100)
        self.assertEqual(len(result.encode()),100)
        self.assertEqual([line.split() for line in result.splitlines()[1:]],[["0","1"],["1","1"]])

    def test_nested_intervals_are_not_added_to_server_total(self):
        def e(phase,start,end,kind="job"):
            return {"phase":phase,"startNs":start*1000000,"endNs":end*1000000,"kind":kind,"bytes":0}
        events=[e("request",0,20,"request"),e("queue.ready",15,15,"request"),
                e("job",20,40),e("job.terminal",39,39),e("parse.scalar",25,30),
                e("tx.process",23,39),e("db.connection_held",23,39),e("db.execute",31,32)]
        metrics=bench.summarize_events(events)
        self.assertEqual(metrics["server_total_ms"],39)
        self.assertEqual(metrics["queue_ms"],5)
        self.assertEqual(metrics["parse_ms"],5)
        self.assertEqual(metrics["db_ms"],1)

    def test_commit_observation_race_is_reported_without_clamping(self):
        def e(phase,start,end,kind="job"):
            return {"phase":phase,"startNs":start,"endNs":end,"kind":kind,"bytes":0}
        metrics=bench.summarize_events([e("request",0,30,"request"),e("queue.ready",21,21,"request"),
            e("job",20,50),e("job.terminal",49,49)])
        self.assertLess(metrics["queue_first_gap_ms"],0)
        self.assertLess(metrics["queue_ms"],0)

    def test_reset_refuses_service_database_before_starting_docker(self):
        with self.assertRaises(ValueError):
            bench.sql("k-plasma-analysis-agent-postgres-1","truncate run cascade")

    def test_job_claim_timings_before_batch_binding_are_joined_by_trace_identity(self):
        events=[
            {"kind":"job","id":"j1","batchId":"","phase":"db.execute"},
            {"kind":"job","id":"j1","batchId":"b1","phase":"job"},
            {"kind":"request","id":"r1","batchId":"","phase":"file.controller_copy"},
            {"kind":"request","id":"r1","batchId":"b1","phase":"request"},
            {"kind":"job","id":"j2","batchId":"b2","phase":"db.execute"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"timing.jsonl"
            path.write_text("".join(json.dumps(e)+"\n" for e in events))
            selected=bench.events_for(path,0,"b1")
        self.assertEqual(len(selected),4)
        self.assertEqual({e["id"] for e in selected},{"j1","r1"})

    def test_second_block_warmup_cannot_overwrite_the_fifth_measured_result(self):
        self.assertNotEqual(bench.trial_label("B","new",0,1,5),"B-new-05")
        self.assertEqual(bench.trial_label("B","new",1,1,5),"B-new-06")

    def test_missing_required_timing_events_fail_the_measurement(self):
        with self.assertRaises(AssertionError):
            bench.summarize_events([])

if __name__=="__main__":unittest.main()
