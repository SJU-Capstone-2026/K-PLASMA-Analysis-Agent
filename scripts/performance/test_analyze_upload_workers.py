import unittest
from analyze_upload_workers import partition,concurrency,summarize_upload
class ParallelAggregationTest(unittest.TestCase):
    def test_partition_preserves_every_run_and_ancillary_file(self):
        data={'entries':[dict(relativePath=f'PRS_02/Source_100/Bias_{i:04}/{name}',size=(i+1)*9) for i in range(150) for name in ['0d_setting.ini','0d_result/log/GasPhaseReactionPath.krp']]}
        for width in (1,2,4,8):
            p=partition(data,width);self.assertEqual(sum(len(x['entries']) for x in p),300)
            sizes=[len(x['roots']) for x in p];self.assertLessEqual(max(sizes)-min(sizes),1)
            self.assertEqual(p,partition(data,width))
    def test_parallel_work_sum_can_exceed_wall_time(self):
        v=concurrency([dict(startNs=0,endNs=5),dict(startNs=0,endNs=5)],(0,5))
        self.assertEqual(v,dict(peak=2,mean=2))
        self.assertEqual(concurrency([dict(startNs=0,endNs=5),dict(startNs=5,endNs=10)],(0,10))['peak'],1)
    def test_each_batch_uses_its_own_queue_commit(self):
        rows=[]
        def e(k,i,p,a,b,batch,**kw):return dict(kind=k,id=i,phase=p,startNs=a,endNs=b,batchId=batch,**kw)
        for n,ready in [('a',2),('b',4)]:
            rows += [e('request',n,'request',0,ready,n),e('request',n,'queue.ready',ready,ready,n),
                e('claim',n,'claim',ready,ready+1,n,jobId=n),e('job',n,'job',ready+1,10,n,workerThread=n),e('job',n,'job.terminal',10,10,n)]
        rows.append(e('claim','a','db.acquire',2,3,''))
        v=summarize_upload(rows,['a','b'],2)
        self.assertEqual(v['worker']['db.acquire']['n'],1)
        self.assertEqual(v['queue_wait_ms']['mean'],1e-6)
        self.assertEqual(v['active_workers']['peak'],2)
        with self.assertRaises(ValueError):summarize_upload([r for r in rows if not (r['id']=='b' and r['phase']=='job.terminal')],['a','b'],2)
if __name__=='__main__':unittest.main()
