import unittest
from analyze_upload_query_benchmark import summarize_queries, describe, paired_delta, analyze_trial, aggregate

def event(phase,start,end,ident='r',kind='lookup',**extra):
    return dict(kind=kind,id=ident,phase=phase,startNs=start*1000000,endNs=end*1000000,**extra)
def client(ident='r',status=200):
    return dict(id=ident,status=status,elapsedMs=20,durationMs=19,valid=status==200,errorCode=0,bodyCharacters=500,version='v')

class QueryAnalysisTest(unittest.TestCase):
    def test_includes_query_finishing_after_window_and_sums_acquisitions(self):
        events=[event('lookup',10,100,status=200),event('db.acquire',10,14),event('db.acquire',18,20),
                event('lookup',1,19,'before',status=200),event('lookup',21,30,'after',status=200)]
        result=summarize_queries(events,[client(),client('before'),client('after')],(5e6,20e6))
        self.assertEqual(result['count'],1);self.assertEqual(result['db_acquire_ms']['mean'],6)
        self.assertEqual(result['server_ms']['mean'],90)
    def test_failures_are_counted_and_not_zero_latency_successes(self):
        result=summarize_queries([event('lookup',10,50,status=500),event('db.acquire',10,40,outcome='error')],[client(status=500)],None)
        self.assertEqual(result['errors'],1);self.assertEqual(result['acquire_errors'],1)
        self.assertIsNone(result['success_client_ms']['mean'])
    def test_missing_or_duplicate_correlations_fail(self):
        with self.assertRaises(ValueError):summarize_queries([event('lookup',1,2,status=200)],[],None)
        with self.assertRaises(ValueError):summarize_queries([], [client(),client()],None)
    def test_uninstrumented_control_preserves_client_latency_without_fabricated_db_times(self):
        import json,tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)
            (path/'result.json').write_text(json.dumps({'label':'control','timingEnabled':False,'clientWindowEpochMs':[10,30]}))
            (path/'timing.jsonl').write_text('')
            (path/'lookup.jsonl').write_text(json.dumps({**client('control-1'),'startEpochMs':20})+'\n')
            result=analyze_trial(path)['lookup']
            self.assertEqual(result['count'],1)
            self.assertEqual(result['client_ms']['mean'],20)
            self.assertIsNone(result['db_acquire_ms']['mean'])

    def test_aggregate_preserves_incomplete_runs_and_keeps_measured_http_errors(self):
        import json,tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            common=dict(measured=True,verified=True,variant='B',pool=1,scenario='combined',timingEnabled=True)
            cases={
                'failed':dict(error={'type':'RuntimeError','message':'upload failed'}),
                'incomplete':dict(incompleteWindow=True),
                'unmatched':{},
                'http-error':{},
            }
            for label,extra in cases.items():
                path=root/'results'/label;path.mkdir(parents=True)
                (path/'result.json').write_text(json.dumps(dict(common,label=label,**extra)))
                if label=='failed':continue
                ident=label+'-request'
                (path/'timing.jsonl').write_text(json.dumps(event('lookup',1,21,ident,status=500))+'\n' if label=='http-error' else '')
                (path/'lookup.jsonl').write_text(json.dumps(client(ident,status=500 if label=='http-error' else 200))+'\n' if label!='incomplete' else '')
            result=aggregate(root)
            self.assertEqual({row['label'] for row in result['excluded_trials']},{'failed','incomplete','unmatched'})
            measured=result['groups']['B-p1-combined-on']
            self.assertEqual(measured['batches'],1)
            self.assertEqual(measured['errors'],1)
            self.assertEqual(measured['metrics']['client_ms']['mean'],20)

    def test_rates_and_discovery_do_not_merge_into_one_improvement(self):
        import json,tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for rate,stage in [(20,'discovery'),(20,'confirm'),(50,'confirm')]:
                label=f'B-{stage}-{rate}';ident=label+'-1'
                path=root/'results'/label;path.mkdir(parents=True)
                (path/'result.json').write_text(json.dumps(dict(label=label,measured=True,verified=True,variant='B',pool=10,
                    scenario='combined',timingEnabled=True,configuredRate=rate,configuredDuration=60,stage=stage)))
                (path/'timing.jsonl').write_text(json.dumps(event('lookup',1,21,ident,status=200))+'\n')
                (path/'lookup.jsonl').write_text(json.dumps(client(ident))+'\n')
            result=aggregate(root)
            self.assertEqual(set(result['groups']),{'B-p10-combined-on-discovery-r20','B-p10-combined-on-confirm-r20','B-p10-combined-on-confirm-r50'})

    def test_user_levels_do_not_merge_with_arrival_rate_groups(self):
        import json,tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for vus in [10,100]:
                label=f'B-vu{vus}';ident=label+'-1'
                path=root/'results'/label;path.mkdir(parents=True)
                (path/'result.json').write_text(json.dumps(dict(label=label,measured=True,verified=True,variant='B',pool=10,
                    scenario='combined',timingEnabled=True,configuredRate=None,configuredDuration=50,stage='confirm',
                    loadModel='users',configuredVUs=vus)))
                (path/'timing.jsonl').write_text(json.dumps(event('lookup',1,21,ident,status=200))+'\n')
                (path/'lookup.jsonl').write_text(json.dumps(client(ident))+'\n')
            result=aggregate(root)
            self.assertEqual(set(result['groups']),{'B-p10-combined-on-confirm-vu10','B-p10-combined-on-confirm-vu100'})

    def test_p95_empty_and_zero_baseline(self):
        self.assertEqual(describe([1,2,3,4,5])['p95'],4.8)
        self.assertIsNone(describe([])['p95'])
        self.assertIsNone(paired_delta([0,0],[1,1])['reduction_percent'])
        self.assertEqual(paired_delta([10,20],[5,15])['mean_reduction_ms'],5)

if __name__=='__main__':unittest.main()
