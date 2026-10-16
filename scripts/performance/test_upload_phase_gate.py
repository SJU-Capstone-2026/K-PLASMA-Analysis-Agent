import asyncio
import json
from pathlib import Path
import tempfile
import time
import unittest
from upload_phase_gate import PhaseGate
from upload_phase_gate import ProcessingState

class GateStateTest(unittest.TestCase):
    def event(self,state,i,phase,kind='job'):
        state.accept(dict(kind=kind,id=str(i),phase=phase))
    def test_eight_claims_without_files_loaded_do_not_release(self):
        s=ProcessingState()
        for i in range(8):self.event(s,i,'job.claimed')
        self.assertFalse(s.ready())
        for i in range(8):self.event(s,i,'source.load')
        self.assertTrue(s.ready())
    def test_completed_parse_or_job_prevents_stale_release(self):
        s=ProcessingState()
        for i in range(8):
            self.event(s,i,'job.claimed');self.event(s,i,'source.load')
        self.event(s,0,'parse.graph');self.assertFalse(s.ready())
        self.event(s,1,'job');self.assertNotIn('1',s.jobs)
        self.assertNotIn('1',s.parsing)
    def test_foreign_traces_do_not_count_as_workers(self):
        s=ProcessingState()
        for i in range(8):
            self.event(s,i,'job.claimed','lookup');self.event(s,i,'source.load','lookup')
        self.assertFalse(s.ready())

class GateDeliveryTest(unittest.IsolatedAsyncioTestCase):
    async def test_one_hundred_waiters_receive_same_future_dispatch(self):
        with tempfile.TemporaryDirectory() as d:
            timing=Path(d)/'timing.jsonl';timing.touch()
            gate=PhaseGate(timing,0,Path(d)/'gate.json')
            async def wait(i):
                reader,writer=await asyncio.open_connection('127.0.0.1',int(gate.url.rsplit(':',1)[1]))
                writer.write(f'GET /wait/{i} HTTP/1.1\r\nHost: localhost\r\n\r\n'.encode())
                await writer.drain();body=await reader.read();writer.close();await writer.wait_closed()
                self.assertIn(b'200 OK',body)
                return json.loads(body.split(b'\r\n\r\n',1)[1])
            tasks=[asyncio.create_task(wait(i)) for i in range(1,101)]
            try:
                for _ in range(1000):
                    if len(gate.waiters)==100:break
                    await asyncio.sleep(.002)
                self.assertEqual(len(gate.waiters),100);self.assertIsNone(gate.result)
                with timing.open('w') as f:
                    for i in range(8):
                        for phase in ['job.claimed','source.load']:
                            f.write(json.dumps(dict(kind='job',id=str(i),phase=phase,endNs=time.monotonic_ns()))+'\n')
                results=await asyncio.wait_for(asyncio.gather(*tasks),5)
                self.assertEqual(len({r['dispatchEpochMs'] for r in results}),1)
                self.assertIsInstance(results[0]['dispatchEpochMs'],int)
                self.assertGreaterEqual(results[0]['dispatchEpochMs']-results[0]['releaseEpochMs'],100)
            finally:
                gate.close()
                for task in tasks:task.cancel()
if __name__=='__main__':unittest.main()
