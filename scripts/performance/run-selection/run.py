"""Real product HTTP lifecycle benchmark, with deterministic HITL instead of LLM."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
import urllib.error
import hashlib
import uuid
from seed import CONTAINER, seed, sql

ROOT = Path(__file__).resolve().parents[3]
BASE = 'http://127.0.0.1:18049'
TOKEN = 'synthetic-selection-worker'


def request(path, body=None):
    headers = {'Content-Type': 'application/json', 'X-Agent-Token': TOKEN, 'Idempotency-Key': str(uuid.uuid4())}
    req = urllib.request.Request(BASE+path, data=None if body is None else json.dumps(body).encode(), headers=headers)
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail=exc.read(2000).decode(errors='replace')
        raise RuntimeError(f'HTTP {exc.code} {path}: {detail}') from exc
    elapsed = (time.perf_counter()-start)*1000
    return json.loads(raw), elapsed, len(raw)


def prepare():
    state = request('/api/workspace')[0]
    if state.get('activeAgentRequest'):
        request('/api/agent/requests/'+state['activeAgentRequest']['requestId']+'/cancel', {})
        state = request('/api/workspace')[0]
    # Clear completed/cancelled history identically between independent sessions.
    state = request('/api/workspace/new-conversation', {'stateToken': state['stateToken']})[0]
    job = request('/api/agent/requests', {'text': '인공 실험 두 개 비교', 'stateToken': state['stateToken']})[0]
    claimed = request('/internal/agent/claim', {'workerId':'picker-benchmark','leaseSeconds':300})[0]
    fence = {'claimGeneration':claimed['claimGeneration'], 'requestRevision':claimed['requestRevision']}
    prefix = '/internal/agent/requests/'+job['requestId']
    request(prefix+'/heartbeat', {**fence, 'operationKind':'compare_runs'})
    result, ms, _ = request(prefix+'/needs-input', {**fence, 'pendingInput':{'id':'pick','type':'run_selection','message':'비교할 실험을 선택해 주세요.','minSelections':2,'baselineRequired':False}})
    return result, ms


def start_server(jar, directory, heap='8g'):
    env = {**os.environ, 'BACKEND_PORT':'18049','DB_URL':'jdbc:postgresql://127.0.0.1:15449/run_selection_bench','POSTGRES_USER':'benchmark','POSTGRES_PASSWORD':'benchmark-local-only','AGENT_WORKER_TOKEN':TOKEN,'KPLASMA_STORAGE_ROOT':str(directory/'storage')}
    log = (directory/'server.log').open('w')
    java = str(Path(os.environ['JAVA_HOME'])/'bin/java')
    proc = subprocess.Popen([java,'-Xms512m','-Xmx'+heap,'-XX:+ExitOnOutOfMemoryError','-XX:StartFlightRecording=filename='+str(directory/'runtime.jfr')+',settings=profile,dumponexit=true','-jar',str(jar)], env=env, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(120):
        if proc.poll() is not None:
            raise RuntimeError('Backend failed; see '+str(directory/'server.log'))
        try:
            request('/api/workspace')
            return proc, log
        except Exception:
            time.sleep(.5)
    proc.terminate()
    raise RuntimeError('Backend startup timeout')


def append(path, row):
    with path.open('a') as f:
        f.write(json.dumps(row, ensure_ascii=False)+'\n')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--variant', required=True, choices=['A','B','C'])
    p.add_argument('--jar', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--sizes', type=int, nargs='+', default=[150,10000,100000,1000000])
    p.add_argument('--sessions', type=int, default=10)
    p.add_argument('--heap', choices=['2g','4g','8g'], default='8g')
    args = p.parse_args()
    db_memory = int(subprocess.check_output(
        ['docker', 'inspect', '--format', '{{.HostConfig.Memory}}', CONTAINER], text=True
    ).strip())
    if db_memory != 6 * 1024**3:
        raise RuntimeError('Use the common 6GB benchmark DB limit before comparing variants')
    args.output.mkdir(parents=True, exist_ok=True)
    for size in args.sizes:
        directory=args.output/str(size);directory.mkdir(exist_ok=True)
        evidence=directory/'sessions.jsonl'
        if evidence.exists():
            raise RuntimeError('Refusing to overwrite '+str(evidence))
        (directory/'environment.json').write_text(json.dumps({'javaHeapMax':args.heap,'javaHeapInitial':'512m','postgresMemoryLimit':'6g','jarSha256':hashlib.sha256(args.jar.read_bytes()).hexdigest(),'variant':args.variant,'size':size,'sessions':args.sessions,'jar':str(args.jar.resolve())}))
        proc, log=start_server(args.jar.resolve(),directory.resolve(),args.heap)
        try:
            (directory/'dataset.json').write_text(json.dumps(seed(size)))
            for index in range(-2,args.sessions):
                try:
                    job,prepare_ms=prepare()
                    path='/api/agent/requests/'+job['requestId']+'/run-options?pendingInputId=pick'
                    if args.variant!='A':path+='&format=2'
                    options,fetch_ms,byte_count=request(path)
                    if index>=0:
                        append(evidence,{'jarSha256':hashlib.sha256(args.jar.read_bytes()).hexdigest(),'variant':args.variant,'size':size,'index':index,'ok':True,'prepareMs':prepare_ms,'fetchMs':fetch_ms,'prepareAndFetchMs':prepare_ms+fetch_ms,'responseBytes':byte_count,'returnedRows':len(options['options'])})
                    print(args.variant,size,index,round(prepare_ms,1),round(fetch_ms,1),byte_count,flush=True)
                    (directory/'request.json').write_text(json.dumps({'request':job,'path':path}))
                    if index<args.sessions-1:
                        request('/api/agent/requests/'+job['requestId']+'/cancel',{})
                except Exception as exc:
                    append(evidence,{'jarSha256':hashlib.sha256(args.jar.read_bytes()).hexdigest(),'variant':args.variant,'size':size,'index':index,'ok':False,'error':str(exc)})
                    print('FAILED',args.variant,size,index,str(exc),flush=True)
                    break
            if proc.poll() is None:
                sizes=sql("select json_build_object('contextBytes',coalesce(octet_length(context_snapshot::text),0),'manifestBytes',coalesce(octet_length(manifest::text),0)) from agent_request order by created_at desc limit 1;")
                (directory/'state-sizes.json').write_text(sizes)
                # Preserve prepared session for browser and k6 by an explicit post hook.
                hook=os.environ.get('SELECTION_BENCH_HOOK')
                if hook and (directory/'request.json').exists():
                    try:
                        subprocess.run([hook,str(directory.resolve()),args.variant],check=True,timeout=1800)
                    except (subprocess.CalledProcessError,subprocess.TimeoutExpired) as exc:
                        (directory/'browser-process-error.txt').write_text(str(exc))
        finally:
            proc.terminate()
            try:proc.wait(timeout=15)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
            log.close()


if __name__=='__main__':main()
