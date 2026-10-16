#!/usr/bin/env python3
"""Fixed pool 10 / total 150 Runs, matched administrators and workers 1,2,4,8."""
import argparse
import concurrent.futures
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import threading
import time
import uuid
from types import SimpleNamespace
import upload_benchmark as u
import upload_query_benchmark as q
from analyze_upload_workers import partition,summarize

ROOT=Path(__file__).resolve().parents[2]


def read_clients(path):
    if not path.exists():return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.startswith('{') and x.endswith('}')]


def schedule(workers=(1,2,4,8), repeats=3, start_index=1):
    if not workers or len(set(workers))!=len(workers) or any(w not in (1,2,4,8) for w in workers):
        raise ValueError('Choose distinct worker counts from 1,2,4,8')
    if not 1<=repeats<=5 or start_index<1 or start_index+repeats-1>5:
        raise ValueError('Repeat indices must be between 1 and 5')
    return [(w,v,i) for w in workers for i in range(start_index,start_index+repeats)
            for v in (('B','C') if i%2 else ('C','B'))]


def run(args):
    if not args.container.startswith('kplasma-upload-benchmark-'):raise ValueError('Dedicated database required')
    if args.output.exists():raise FileExistsError(args.output)
    args.output.mkdir(parents=True)
    dataset=json.loads((args.fixture/'synthetic/manifest.json').read_text())
    golden=json.loads((args.fixture/'golden-new.json').read_text())
    queries=json.loads((args.seed_artifacts/'queries.json').read_text())
    if len(dataset['expected'])!=150:raise ValueError('Exactly 150 Runs required')
    q.validate_seed(dataset,queries)
    trials=schedule(args.workers,args.repeats,args.start_index)
    parts={w:partition(dataset,w) for w in args.workers}
    (args.output/'partitions.json').write_text(json.dumps(parts,indent=2))
    measured=args.output/'measured-harness';measured.mkdir()
    for name in ['upload_worker_benchmark.py','analyze_upload_workers.py','analyze_upload_query_benchmark.py','upload_query_benchmark.py','upload_benchmark.py','upload_query_load.js','upload_query_user_schedule.mjs','upload_query_monotonic.mjs']:
        shutil.copy2(Path(__file__).parent/name,measured/name)
    jars={v:hashlib.sha256((args.builds/(v+'.jar')).read_bytes()).hexdigest() for v in ['B','C']}
    state=dict(status='preparing',completed=[],current=None)
    manifest=dict(pool=10,administratorsAndWorkers=args.workers,vus=100,intervalSeconds=5,totalRuns=150,
        files=len(dataset['entries']),bytes=sum(e['size'] for e in dataset['entries']),datasetHash=dataset['datasetHash'],
        jarSha256=jars,schedule=trials,restartEachTrial=args.restart_each_trial,loadEngine=args.load_engine,uploadOffsetMs=args.upload_offset_ms,partitionCostProxy='original bytes',maxNewBatchSeconds=1800,maxSuiteSeconds=2100)
    (args.output/'experiment.json').write_text(json.dumps(manifest,indent=2))
    base=f'http://127.0.0.1:{args.server_port}';storage=args.builds/'active/storage'
    process=None;target=None;current=None;block=0;started=time.monotonic();owns_db=False
    def save():(args.output/'state.json').write_text(json.dumps(state,indent=2))
    def stop_server():
        nonlocal process,current
        if process:
            process.terminate()
            try:process.wait(15)
            except subprocess.TimeoutExpired:process.kill();process.wait(5)
        process=None;current=None
    def restore():u.restore_seed(args.container,storage,args.seed_artifacts/'seed')
    def start(variant,width):
        nonlocal process,current,block,target,owns_db
        if current==(variant,width) and not args.restart_each_trial:return False
        stop_server();block+=1
        if subprocess.run(['lsof','-t',f'-iTCP:{args.server_port}','-sTCP:LISTEN'],capture_output=True,text=True).stdout.strip():raise RuntimeError('Port already occupied')
        target=args.output/'servers'/f'{variant}-w{width}-{block}';(target/'tmp').mkdir(parents=True)
        storage.mkdir(parents=True,exist_ok=True)
        command=[args.java,'-Xms256m','-Xmx2g',f'-Djava.io.tmpdir={target.resolve()}/tmp',
            '-Dkplasma.import-timing.enabled=true',f'-Dkplasma.import-timing.file={target.resolve()}/timing.jsonl',
            '-jar',str((args.builds/(variant+'.jar')).resolve()),f'--server.port={args.server_port}',
            f'--spring.datasource.url=jdbc:postgresql://127.0.0.1:{args.db_port}/upload_benchmark',
            '--spring.datasource.username=upload_benchmark','--spring.datasource.password=isolated-upload-benchmark',
            '--spring.datasource.hikari.maximum-pool-size=10','--spring.datasource.hikari.minimum-idle=10',
            f'--kplasma.worker.concurrency={width}',f'--kplasma.storage-root={storage.resolve()}']
        (target/'command.json').write_text(json.dumps(command,indent=2))
        with (target/'server.log').open('w') as log:process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT)
        for _ in range(80):
            if process.poll() is not None:raise RuntimeError('Server failed to start')
            try:
                if u.get(base,'/api/health')['status']=='UP':break
            except Exception:time.sleep(.5)
        else:raise TimeoutError('Startup timeout')
        owns_db=True;current=(variant,width)
        restore()
        # Same eight complete biased Run bundles after every JVM start; never counted as measurements.
        groups=partition(dataset,1)[0];roots=sorted({e['relativePath'].rsplit('/0d_setting.ini',1)[0] for e in groups['entries'] if e['relativePath'].endswith('/0d_setting.ini') and '/Bias_0600/' in e['relativePath']})[:8]
        small={'entries':[e for e in dataset['entries'] if '/'.join(e['relativePath'].split('/')[:3]) in roots]}
        if len(roots)!=8:raise ValueError('Warmup input incomplete')
        with q.upload_deadline(60):
            info,*_=u.post(base,small,'FOLDER','warm-'+str(uuid.uuid4()),timeout=60)
            while info['status'] in u.ACTIVE:time.sleep(.1);info=u.get(base,'/api/import-batches/'+info['batchId'])
        if info['status']!='SUCCESS' or len(info['jobs'])!=8:raise AssertionError('Warmup failed')
        (target/'warmup.json').write_text(json.dumps(info,indent=2));return True
    def trial(variant,width,index,restarted):
        label=f'{variant}-w{width}-{index}';out=args.output/'results'/label;out.mkdir(parents=True)
        restore();q.validate_query_payloads(base,queries)
        timing=target/'timing.jsonl';offset=timing.stat().st_size
        meta=dict(label=label,variant=variant,workers=width,administrators=width,pool=10,index=index,
            restarted=restarted,loadEngine=args.load_engine,expectedJobs=150,batchIds=[],verified=False,errors=[])
        stop=threading.Event();load=None;monitor=None;executor=None
        def save_meta():(out/'result.json').write_text(json.dumps(meta,indent=2))
        try:
            env={**os.environ,'BASE_URL':base,'QUERY_MANIFEST':str((args.seed_artifacts/'queries.json').resolve()),
                 'TRIAL_ID':label,'LOAD_MODEL':'users','USER_VUS':'100','DURATION':'70s','SUMMARY_PATH':str((out/'k6-summary.json').resolve())}
            trigger=out/'upload-trigger.json'
            env['UPLOAD_TRIGGER_PATH']=str(trigger.resolve())
            env['UPLOAD_OFFSET_MS']=str(args.upload_offset_ms)
            with (out/'k6.log').open('w') as log:
                if args.load_engine=='node-monotonic':
                    with (out/'lookup.jsonl').open('w') as lookups:
                        load=subprocess.Popen(['node',str(ROOT/'scripts/performance/upload_query_monotonic.mjs')],env=env,stdout=lookups,stderr=log)
                else:
                    load=subprocess.Popen(['k6','run','--quiet','--log-format','raw','--console-output',str((out/'lookup.jsonl').resolve()),str(ROOT/'scripts/performance/upload_query_load.js')],env=env,stdout=log,stderr=subprocess.STDOUT)
            monitor=threading.Thread(target=q.observe_resources,args=(SimpleNamespace(pid=process.pid,k6_pid=load.pid,container=args.container),out/'resources.jsonl',stop),daemon=True);monitor.start()
            # Anchor to the first actual synchronized cohort, not k6 process startup.
            deadline=time.monotonic()+15
            while not read_clients(out/'lookup.jsonl'):
                if load.poll() is not None or time.monotonic()>deadline:raise RuntimeError('k6 did not start')
                time.sleep(.05)
            first=read_clients(out/'lookup.jsonl')[0]['scheduledEpochMs']
            if args.load_engine=='node-monotonic':
                while not trigger.exists():
                    if load.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Upload trigger missing')
                    time.sleep(.002)
            else:
                time.sleep(max(0,(first+args.upload_offset_ms-time.time()*1000)/1000))
            gate=threading.Barrier(width+1);executor=concurrent.futures.ThreadPoolExecutor(max_workers=width)
            def send(part):
                gate.wait(timeout=10);epoch=time.time()*1000
                info,t0,sent,accepted,wire=u.post(base,part,'FOLDER',label+'-'+str(uuid.uuid4()),timeout=60)
                return dict(info=info,startEpochMs=epoch,startNs=t0,sentNs=sent,acceptedNs=accepted,wireBytes=wire)
            futures=[executor.submit(send,p) for p in parts[width]]
            start_ns=time.perf_counter_ns();start_epoch=time.time()*1000;gate.wait(timeout=10)
            with q.upload_deadline(60):
                submitted=[f.result(timeout=60) for f in futures]
                meta['batchIds']=[s['info']['batchId'] for s in submitted];save_meta()
                infos=[s['info'] for s in submitted]
                while any(i['status'] in u.ACTIVE for i in infos):
                    time.sleep(.1);infos=[u.get(base,'/api/import-batches/'+i['batchId']) for i in infos]
            end_ns=time.perf_counter_ns();end_epoch=time.time()*1000
            if not all(i['status']=='SUCCESS' for i in infos):raise AssertionError('Upload batch failed')
            if sum(len(i['jobs']) for i in infos)!=150 or not all(j['status']=='READY' for i in infos for j in i['jobs']):raise AssertionError('Job loss/duplication')
            meta.update(client_total_ms=(end_ns-start_ns)/1e6,clientWindowEpochMs=[start_epoch,end_epoch],
                adminStartSpreadMs=max(s['startEpochMs'] for s in submitted)-min(s['startEpochMs'] for s in submitted),
                admins=[{k:v for k,v in s.items() if k!='info'} for s in submitted])
            (out/'batches.json').write_text(json.dumps(infos,indent=2))
            final_cohort=(max(c['cohort'] for c in read_clients(out/'lookup.jsonl'))+1 if args.load_engine=='node-monotonic' else math.floor((end_epoch-first)/5000)+1)
            deadline=time.monotonic()+15
            while sum(c['cohort']==final_cohort for c in read_clients(out/'lookup.jsonl'))<100:
                if load.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Final lookup cohort incomplete')
                time.sleep(.05)
            load.send_signal(signal.SIGINT);meta['k6ExitCode']=load.wait(15)
            meta['loadStop']='intentional SIGINT after complete post-upload cohort';meta['finalCohort']=final_cohort
            if meta['k6ExitCode'] not in (0,105):raise RuntimeError('Unexpected k6 exit')
            stop.set();monitor.join(15);time.sleep(.12)
            with timing.open('rb') as stream:stream.seek(offset);(out/'timing.jsonl').write_bytes(stream.read())
            (out/'sql.json').write_text(u.sql(args.container,"select coalesce(json_agg(json_build_object('query',query,'calls',calls,'executionMs',total_exec_time)),'[]') from pg_stat_statements where dbid=(select oid from pg_database where datname=current_database())"))
            q.validate_query_payloads(base,queries);u.verify(base,args.container,dataset,'new',golden,historical_versions=3)
            meta['verified']=True;save_meta();row=summarize(out)
            p=row['lookup']['pool'];look=row['lookup']
            if p['configured_maxima']!=[10] or p['configured_minima']!=[10]:raise AssertionError('Pool differs from ten')
            if look['all_errors'] or look['unmatched_clients'] or look['missing_scheduled_requests']:raise AssertionError('Lookup failures/missing observations')
            if row['upload']['active_workers']['peak']>width:raise AssertionError('Worker bound exceeded')
            (out/'summary.json').write_text(json.dumps(row,indent=2))
            print('RESULT '+json.dumps(dict(label=label,uploadMs=meta['client_total_ms'],heldSeconds=row['upload']['total_held_s'],acquireMs=look['db_acquire_ms']['mean'],httpMs=look['client_ms']['mean'],workersPeak=row['upload']['active_workers']['peak'],pendingPeak=p['pending_peak'])),flush=True)
            return row
        except BaseException as e:
            meta['error']=dict(type=type(e).__name__,message=str(e));raise
        finally:
            stop.set()
            if load and load.poll() is None:
                load.terminate()
                try:load.wait(10)
                except subprocess.TimeoutExpired:load.kill();load.wait()
            if monitor:monitor.join(15)
            if executor:executor.shutdown(wait=False,cancel_futures=True)
            with timing.open('rb') as stream:stream.seek(offset);(out/'timing.jsonl').write_bytes(stream.read())
            save_meta()
    def expire(*_):raise TimeoutError('35 minute suite limit')
    previous=signal.signal(signal.SIGUSR1,expire)
    watchdog=threading.Timer(2100,lambda:os.kill(os.getpid(),signal.SIGUSR1));watchdog.daemon=True;watchdog.start()
    try:
        state.update(status='running',startedEpoch=time.time());save()
        for width,variant,index in trials:
            if time.monotonic()-started>=1800:raise TimeoutError('30 minute new-batch cutoff')
            state['current']=dict(workers=width,variant=variant,index=index);save();print('START '+json.dumps(state['current']),flush=True)
            restarted=start(variant,width);row=trial(variant,width,index,restarted)
            state['completed'].append(row['label']);save()
        state['status']='complete'
    except BaseException as e:state.update(status='stopped',error=dict(type=type(e).__name__,message=str(e)));raise
    finally:
        watchdog.cancel();signal.signal(signal.SIGUSR1,previous);stop_server()
        if owns_db:
            u.sql(args.container,'truncate import_batch,source_set,run cascade');restore()
        state.update(current=None,elapsedSeconds=time.monotonic()-started,finishedEpoch=time.time());save()

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['builds','seed-artifacts','fixture','output']:p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--workers',type=int,nargs='+',default=[1,2,4,8]);p.add_argument('--repeats',type=int,default=3)
    p.add_argument('--start-index',type=int,default=1)
    p.add_argument('--restart-each-trial',action='store_true')
    p.add_argument('--load-engine',choices=['k6','node-monotonic'],default='k6')
    p.add_argument('--upload-offset-ms',type=int,default=5000)
    p.add_argument('--container',required=True);p.add_argument('--java',default='/opt/homebrew/opt/openjdk@21/bin/java')
    p.add_argument('--server-port',type=int,default=18552);p.add_argument('--db-port',type=int,default=15452)
    run(p.parse_args())
