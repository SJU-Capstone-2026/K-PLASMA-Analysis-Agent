#!/usr/bin/env python3
"""Bounded, local pool-10 upload/query experiment. No production configuration changes."""
import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace
import upload_benchmark as u
import upload_query_benchmark as q

RATES=(20,50,100,200,400)


def stop_reason(row):
    lookup=row['lookup']
    achieved=lookup.get('achieved_start_rate')
    if lookup.get('dropped_iterations',0) or (achieved is not None and achieved<row['configuredRate']*.95):
        return 'arrival_limit'
    if lookup.get('all_invalid_payloads',0) or lookup['unmatched_clients']:
        return 'invalid_measurement'
    worker=lookup.get('worker',{})
    if (worker.get('db_acquire_ms',{}).get('p95') or 0)>=5 and worker.get('pending_samples',0)>=3:
        return 'connection_contention'
    if (lookup['client_ms']['p95'] or 0)>=50 or lookup['errors']/max(1,lookup['count'])>=.01:
        return 'http_degradation'
    return None


def selected_rates(rows):
    last=rows[-1];reason=stop_reason(last);rate=last['configuredRate']
    if reason=='invalid_measurement':raise ValueError('Measurement integrity failed')
    if reason=='arrival_limit':
        return ([rows[-2]['configuredRate']] if len(rows)>1 else [5]),reason
    if reason:return ([rows[-2]['configuredRate'] if len(rows)>1 else 5,rate]),reason
    return [rate],'no_bottleneck_within_limit'


def confirmation_schedule(rates):
    # B1 -> C1,2,3 -> B2,3; rate order reverses each repeat.
    return [(variant,index,rate) for variant,indices in [('B',[1]),('C',[1,2,3]),('B',[2,3])]
            for index in indices for rate in (rates if index%2 else list(reversed(rates)))]


def parse_args():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ['artifacts','fixture-root','output']:parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--container',required=True)
    parser.add_argument('--java',default=shutil.which('java'))
    parser.add_argument('--server-port',type=int,default=18552)
    parser.add_argument('--db-port',type=int,default=15452)
    return parser.parse_args()


def run(args):
    if not args.container.startswith('kplasma-upload-benchmark-'):raise ValueError('Dedicated benchmark container required')
    if args.output.exists():raise FileExistsError(args.output)
    args.output.mkdir(parents=True)
    snapshot=args.output/'measured-harness';snapshot.mkdir()
    for name in ['upload_query_ramp.py','upload_query_benchmark.py','analyze_upload_query_benchmark.py','upload_benchmark.py','upload_query_load.js']:
        shutil.copy2(Path(__file__).parent/name,snapshot/name)
    base=f'http://127.0.0.1:{args.server_port}'
    storage=args.artifacts/'active/storage'
    state={'status':'preparing','completed':[],'current':None}
    process=None;target=None;current_variant=None;block=0;started=None;owns_database=False
    def save():
        (args.output/'state.json').write_text(json.dumps(state,indent=2))
    def stop():
        nonlocal process,current_variant
        if process:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
            process=None;current_variant=None
    def start(variant):
        nonlocal process,target,current_variant,block,owns_database
        if current_variant==variant:return
        stop();block+=1
        if subprocess.run(['lsof','-t',f'-iTCP:{args.server_port}','-sTCP:LISTEN'],capture_output=True,text=True).stdout.strip():
            raise RuntimeError('Benchmark port already occupied')
        target=args.output/'servers'/f'{variant}-{block}';(target/'tmp').mkdir(parents=True)
        storage.mkdir(parents=True,exist_ok=True)
        command=[args.java,'-Xms256m','-Xmx2g',f'-Djava.io.tmpdir={target.resolve()}/tmp',
                 '-Dkplasma.import-timing.enabled=true',f'-Dkplasma.import-timing.file={target.resolve()}/timing.jsonl',
                 '-jar',str((args.artifacts/(variant+'.jar')).resolve()),f'--server.port={args.server_port}',
                 f'--spring.datasource.url=jdbc:postgresql://127.0.0.1:{args.db_port}/upload_benchmark',
                 '--spring.datasource.username=upload_benchmark','--spring.datasource.password=isolated-upload-benchmark',
                 '--spring.datasource.hikari.maximum-pool-size=10','--spring.datasource.hikari.minimum-idle=10',
                 f'--kplasma.storage-root={storage.resolve()}']
        with (target/'server.log').open('w') as log:process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT)
        for _ in range(60):
            if process.poll() is not None:raise RuntimeError('Server startup failed')
            try:
                if u.get(base,'/api/health')['status']=='UP':break
            except Exception:time.sleep(.5)
        else:raise RuntimeError('Server startup timeout')
        owns_database=True
        current_variant=variant
        trial(variant,'upload',block,'warmup',5,False)
    def trial(variant,scenario,index,stage,rate,measured=True):
        if time.monotonic()-started>=1500:raise TimeoutError('25 minute new-batch cutoff')
        state['current']=dict(variant=variant,scenario=scenario,index=index,stage=stage,rate=rate,startedEpoch=time.time());save()
        print('START '+json.dumps(state['current']),flush=True)
        row=q.run_trial(SimpleNamespace(base=base,variant=variant,pool=10,container=args.container,
            manifest=args.fixture_root/'synthetic/manifest.json',queries=args.artifacts/'queries.json',
            seed=args.artifacts/'seed',storage=storage,timing=target/'timing.jsonl',output=args.output/'results',
            pid=process.pid,index=index,scenario=scenario,measured=measured,timing_enabled=True,
            duration=60,pre_seconds=5,query_duration=30,upload_timeout=50,rate=rate,stage=stage,
            golden=args.fixture_root/'golden-new.json'))
        pool=row['lookup']['pool']
        if pool['configured_maxima']!=[10] or pool['configured_minima']!=[10]:raise AssertionError('Pool configuration mismatch')
        if row.get('incompleteWindow'):raise TimeoutError('Incomplete upload observation window')
        state['completed'].append(dict(label=row['label'],reason=stop_reason(row) if scenario=='combined' else None));save()
        return row
    jars={v:hashlib.sha256((args.artifacts/(v+'.jar')).read_bytes()).hexdigest() for v in ['B','C']}
    expected={'B':'3570164bede4c955b1f8b190a4c2f43669c77e6aeff06bc112a8f8605d2e6f38','C':'b3e06de0a0b6948cba22f3f1ab49b864279254a278147f8a74bcc0721a880b92'}
    if jars!=expected:raise ValueError('JAR differs from the measured baseline')
    (args.output/'schedule.json').write_text(json.dumps(dict(rates=RATES,pool=10,vus=60,duration=60,preSeconds=5,
        seed=str(args.artifacts/'seed'),jarSha256=jars,maxNewBatchSeconds=1500,maxSuiteSeconds=1800),indent=2))
    def expire(*_):raise TimeoutError('30 minute suite limit')
    previous=signal.signal(signal.SIGUSR1,expire)
    watchdog=threading.Timer(1800,lambda:os.kill(os.getpid(),signal.SIGUSR1));watchdog.daemon=True
    started=time.monotonic();state.update(status='running',startedEpoch=time.time());save();watchdog.start()
    try:
        start('B');discovery=[]
        for rate in RATES:
            row=trial('B','combined',1,'discovery',rate);discovery.append(row)
            if stop_reason(row):break
        rates,reason=selected_rates(discovery)
        state.update(selectedRates=rates,selectionReason=reason);save()
        (args.output/'selection.json').write_text(json.dumps(dict(rates=rates,reason=reason,selectedEpoch=time.time(),
            discovery=[r['label'] for r in discovery],confirmation=confirmation_schedule(rates)),indent=2))
        print('SELECTED '+json.dumps(dict(rates=rates,reason=reason)),flush=True)
        trial('B','query',1,'diagnostic',max(rates))
        for variant,index,rate in confirmation_schedule(rates):
            changed=current_variant!=variant;start(variant)
            if changed and variant=='C':trial('C','query',1,'diagnostic',max(rates))
            trial(variant,'combined',index,'confirm',rate)
        state['status']='complete'
    except BaseException as error:
        state.update(status='stopped',error=dict(type=type(error).__name__,message=str(error)))
        raise
    finally:
        watchdog.cancel();signal.signal(signal.SIGUSR1,previous)
        stop()
        # Server is stopped before touching abandoned jobs in this dedicated DB.
        if owns_database:
            u.sql(args.container,'truncate import_batch,source_set,run cascade')
            u.restore_seed(args.container,storage,args.artifacts/'seed')
        state.update(current=None,finishedEpoch=time.time(),elapsedSeconds=time.monotonic()-started);save()

if __name__=='__main__':run(parse_args())
