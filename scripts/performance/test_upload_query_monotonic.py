import hashlib
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest

@unittest.skipUnless(shutil.which('node'),'Node.js required')
class MonotonicLoadTest(unittest.TestCase):
    def test_backward_wall_clock_jump_does_not_skip_a_burst(self):
        body=b'{"synthetic":true}'
        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version='HTTP/1.1'
            def do_GET(self):
                self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def log_message(self,*_):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder);manifest=root/'queries.json';trigger=root/'trigger.json'
                manifest.write_text(json.dumps([dict(runVersionId='synthetic',sha256=hashlib.sha256(body).hexdigest())]))
                hook=root/'clock-jump.mjs'
                hook.write_text("import {performance} from 'node:perf_hooks';const wall=Date.now;const begin=performance.now();Date.now=()=>wall()-(performance.now()-begin>2000?5000:0);")
                env={**os.environ,'BASE_URL':f'http://127.0.0.1:{server.server_port}','QUERY_MANIFEST':str(manifest),
                     'USER_VUS':'100','DURATION':'6s','TRIAL_ID':'clock-check','SUMMARY_PATH':str(root/'summary.json'),
                     'UPLOAD_TRIGGER_PATH':str(trigger),'UPLOAD_OFFSET_MS':'3000'}
                result=subprocess.run(['node','--import',str(hook),str(Path(__file__).with_name('upload_query_monotonic.mjs'))],env=env,capture_output=True,text=True,timeout=20,check=True)
                rows=[json.loads(line) for line in result.stdout.splitlines()]
                self.assertEqual(len(rows),200)
                self.assertEqual({r['cohort'] for r in rows},{0,1})
                self.assertTrue(all(r['valid'] and r['elapsedMs']>=0 for r in rows))
                for c in [0,1]:self.assertEqual(len({r['vu'] for r in rows if r['cohort']==c}),100)
                first=min(rows,key=lambda r:r['startMonoMs']);last=min((r for r in rows if r['cohort']==1),key=lambda r:r['startMonoMs'])
                self.assertGreater(last['startMonoMs']-first['startMonoMs'],4900)
                self.assertLess(abs(last['startEpochMs']-first['startEpochMs']),1000)
                self.assertTrue(trigger.exists())
        finally:server.shutdown();server.server_close();worker.join()

if __name__=='__main__':unittest.main()
