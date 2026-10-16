#!/usr/bin/env python3
"""Local upload/read contention experiment, reusing the original upload and parity harness."""
import argparse
import hashlib
import http.client
import json
import os
import signal
from contextlib import contextmanager
import subprocess
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit
import upload_benchmark as upload
from analyze_upload_query_benchmark import analyze_trial

ROOT=Path(__file__).resolve().parents[2]


def load_configuration(args):
    mode=getattr(args,'load_model','arrival')
    if mode=='users':
        vus=getattr(args,'vus',1)
        if not isinstance(vus,int) or not 1<=vus<=100:raise ValueError('VUs must be between 1 and 100')
        return dict(loadModel=mode,configuredRate=None,configuredVUs=vus,configuredMeanRate=vus/5,
                    readIntervalSeconds=5,requestPattern='synchronized',preAllocatedVUs=vus)
    if mode!='arrival' or not 1<=args.rate<=400:raise ValueError('Rate must be between 1 and 400')
    return dict(loadModel=mode,configuredRate=args.rate,preAllocatedVUs=60)


def trial_label(args):
    if getattr(args,'load_model','arrival')=='users':
        return f"{args.variant}-p{args.pool}-{args.scenario}-{'measure' if args.measured else 'warm'}-{args.index:02}-{'on' if args.timing_enabled else 'off'}-{args.stage}-vu{args.vus}"
    suffix=f"-{args.stage}-r{args.rate}" if args.stage!='legacy' else ''
    return f"{args.variant}-p{args.pool}-{args.scenario}-{'measure' if args.measured else 'warm'}-{args.index:02}-{'on' if args.timing_enabled else 'off'}{suffix}"


class UploadObservationTimeout(TimeoutError):
    pass


@contextmanager
def upload_deadline(seconds):
    """Interrupt stalled multipart sends/polls as well as the polling loop (local Unix harness)."""
    if seconds<=0:raise ValueError('Upload timeout must be positive')
    def expired(*_):raise UploadObservationTimeout('Upload observation deadline reached')
    previous=signal.signal(signal.SIGALRM,expired)
    signal.setitimer(signal.ITIMER_REAL,seconds)
    try:yield
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)
        signal.signal(signal.SIGALRM,previous)

def validate_seed(dataset,queries):
    if not queries:raise ValueError('Lookup seed cannot be empty')
    ids=[r['runId'] for r in queries];versions=[r['runVersionId'] for r in queries]
    if len(set(ids))!=len(ids) or len(set(versions))!=len(versions):raise ValueError('Duplicate seed references')
    if not set(ids)<=set(dataset.get('expected',dataset.get('runIds',[]))):raise ValueError('Seed must use the supported upload grid')
    if not all(r.get('sha256') for r in queries):raise ValueError('Expected payload hash required')


def raw_get(base,path):
    u=urlsplit(base)
    if u.hostname not in {'127.0.0.1','localhost'}:raise ValueError('Local benchmark only')
    connection=http.client.HTTPConnection(u.hostname,u.port,timeout=10)
    try:
        connection.request('GET',path);response=connection.getresponse();body=response.read()
        if response.status!=200:raise RuntimeError(f'Unexpected lookup status: {response.status}')
        return body
    finally:connection.close()


def validate_query_payloads(base,queries):
    for row in queries:
        body=raw_get(base,'/api/run-versions/'+row['runVersionId'])
        assert hashlib.sha256(body).hexdigest()==row['sha256'],'Lookup payload changed'


def observe_resources(args,path,stop):
    # A separate DB connection; this does not borrow from the app pool.
    with path.open('w') as output:
        while not stop.is_set():
            row={'epochNs':time.time_ns()}
            commands={'process':['ps','-p',str(args.pid),'-o','pid=,%cpu=,rss='],
                      'loadProcess':['ps','-p',str(getattr(args,'k6_pid',0)),'-o','pid=,%cpu=,rss='],
                      'hostMemory':['memory_pressure','-Q'],
                      'dbResources':['docker','exec',args.container,'sh','-c','cat /sys/fs/cgroup/cpu.stat /sys/fs/cgroup/memory.current /sys/fs/cgroup/io.stat'],
                      'dbWaits':['docker','exec',args.container,'psql','-U',upload.DB_USER,'-d',upload.DB_NAME,'-Atc',"select coalesce(json_agg(json_build_object('state',state,'waitType',wait_event_type,'wait',wait_event)),'[]') from pg_stat_activity where datname=current_database() and pid<>pg_backend_pid()"]}
            for name,command in commands.items():
                try:row[name]=subprocess.run(command,capture_output=True,text=True,timeout=5,check=True).stdout.strip()
                except Exception as error:row[name]={'error':type(error).__name__}
            output.write(json.dumps(row)+'\n');output.flush();stop.wait(2)


def run_trial(args):
    for key,value in dict(rate=5,stage='legacy',query_duration=60,upload_timeout=600).items():
        if not hasattr(args,key):setattr(args,key,value)
    load=load_configuration(args)
    dataset=json.loads(args.manifest.read_text());queries=json.loads(args.queries.read_text())
    validate_seed(dataset,queries)
    if urlsplit(args.base).hostname not in {'localhost','127.0.0.1'}:raise ValueError('Local benchmark only')
    label=trial_label(args)
    target=args.output/label
    if target.exists():raise FileExistsError(target)
    target.mkdir(parents=True)
    result=dict(label=label,variant=args.variant,pool=args.pool,scenario=args.scenario,index=args.index,
                measured=args.measured,timingEnabled=args.timing_enabled,datasetHash=dataset['datasetHash'],
                **load,stage=args.stage,configuredDuration=args.query_duration if args.scenario=='query' else args.duration,newRuns=len(dataset.get("expected",dataset.get("runIds",[])))-len(queries),updatedRuns=len(queries),errors=[],queryManifest=[{k:v for k,v in q.items() if k!='sha256'} for q in queries])
    process=None;stop=threading.Event();monitor=None;offset=None
    try:
        upload.restore_seed(args.container,args.storage,args.seed)
        validate_query_payloads(args.base,queries)
        offset=args.timing.stat().st_size if args.timing.exists() else 0
        monitor=threading.Thread(target=observe_resources,args=(args,target/'resources.jsonl',stop),daemon=True);monitor.start()
        if args.scenario!='upload':
            duration=args.query_duration if args.scenario=='query' else args.duration
            env={**os.environ,'BASE_URL':args.base,'QUERY_MANIFEST':str(args.queries.resolve()),'TRIAL_ID':label,
                 'RATE':str(args.rate),'LOAD_MODEL':load['loadModel'],'USER_VUS':str(load.get('configuredVUs',1)),'DURATION':f'{duration}s','SUMMARY_PATH':str((target/'k6-summary.json').resolve())}
            with (target/'k6.log').open('w') as log:
                process=subprocess.Popen(['k6','run','--quiet','--log-format','raw','--console-output',str((target/'lookup.jsonl').resolve()),str(ROOT/'scripts/performance/upload_query_load.js')],env=env,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
            args.k6_pid=process.pid
            result['loadStartedEpochMs']=time.time()*1000
            if args.scenario=='combined':time.sleep(args.pre_seconds)
        if args.scenario!='query':
            epoch=time.time_ns()
            with upload_deadline(args.upload_timeout):
                info,t0,sent,accepted,wire=upload.post(args.base,dataset,'FOLDER',str(uuid.uuid4()))
                result['batchId']=info['batchId']
                while info['status'] in upload.ACTIVE:
                    time.sleep(1)
                    try:info=upload.get(args.base,'/api/import-batches/'+info['batchId'])
                    except RuntimeError as error:result['errors'].append({'kind':'poll','error':str(error)[:100]})
            end=time.perf_counter_ns();end_epoch=time.time_ns()
            result['batchId']=info['batchId'];result['clientWindowEpochMs']=[epoch/1e6,end_epoch/1e6]
            result['upload']={'client_total_ms':(end-t0)/1e6,'accept_ms':(accepted-t0)/1e6,'send_ms':(sent-t0)/1e6,'wire_bytes':wire,'jobs':len(info['jobs']),'status':info['status']}
            assert info['status']=='SUCCESS',info['status']
            assert len(info['jobs'])==len(dataset['expected'])
            assert all(j['status']=='READY' for j in info['jobs'])
            if args.scenario=='combined' and (end-t0)/1e9>args.duration-args.pre_seconds-5:result['incompleteWindow']=True
        if process:
            code=process.wait(timeout=args.duration+30)
            result['k6ExitCode']=code
            if code:raise RuntimeError(f'k6 exited {code}')
        stop.set()
        if monitor:monitor.join(15)
        time.sleep(.12)
        if args.timing.exists():
            with args.timing.open('rb') as stream:stream.seek(offset);raw=stream.read()
            (target/'timing.jsonl').write_bytes(raw)
        else:(target/'timing.jsonl').write_text('')
        if args.scenario!='query' and args.timing_enabled:
            events=upload.events_for(target/'timing.jsonl',0,result['batchId'])
            result['upload'].update(upload.summarize_events(events))
            result['windowNs']=[min(e['startNs'] for e in events if e['phase']=='request'),max(e['endNs'] for e in events if e['phase']=='job.terminal')]
        stats=upload.sql(args.container,"select coalesce(json_agg(json_build_object('query',query,'calls',calls,'executionMs',total_exec_time)),'[]') from pg_stat_statements where dbid=(select oid from pg_database where datname=current_database())")
        (target/'sql.json').write_text(stats)
        validate_query_payloads(args.base,queries)
        if args.scenario!='query':
            golden=json.loads(args.golden.read_text()) if args.golden else None
            upload.verify(args.base,args.container,dataset,'new',golden,historical_versions=len(queries))
        result['verified']=True
    except Exception as error:
        if isinstance(error,UploadObservationTimeout):
            result['censored']=True
            result['observationLowerBoundMs']=args.upload_timeout*1000
        result['error']={'type':type(error).__name__,'message':str(error)[:1000]}
        raise
    finally:
        stop.set()
        if monitor:monitor.join(15)
        if process and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=15)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        if offset is not None and args.timing.exists():
            with args.timing.open('rb') as stream:stream.seek(offset);raw=stream.read()
            (target/'timing.jsonl').write_bytes(raw)
        (target/'result.json').write_text(json.dumps(result,indent=2))
    analyzed=analyze_trial(target)
    if analyzed['lookup']['all_invalid_payloads']:raise AssertionError('Lookup payload mismatch during load')
    print(json.dumps({'label':label,'upload':result.get('upload',{}).get('client_total_ms'),
                      'lookups':analyzed['lookup']['count'],'acquire':analyzed['lookup']['db_acquire_ms']['mean'],
                      'client':analyzed['lookup']['client_ms']['mean'],'p95':analyzed['lookup']['client_ms']['p95'],
                      'errors':analyzed['lookup']['errors']}),flush=True)
    return analyzed


def arguments():
    parser=argparse.ArgumentParser()
    for key in ['base','variant','container']:parser.add_argument('--'+key,required=True)
    for key in ['manifest','queries','seed','storage','timing','output']:parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--golden',type=Path);parser.add_argument('--pool',type=int,required=True)
    parser.add_argument('--pid',type=int,required=True);parser.add_argument('--index',type=int,default=1)
    parser.add_argument('--scenario',choices=['query','upload','combined'],default='combined')
    parser.add_argument('--warmup',dest='measured',action='store_false');parser.add_argument('--no-timing',dest='timing_enabled',action='store_false')
    parser.add_argument('--load-model',choices=['arrival','users'],default='arrival');parser.add_argument('--vus',type=int,default=1)
    parser.add_argument('--rate',type=int,default=5);parser.add_argument('--stage',choices=['legacy','discovery','confirm','diagnostic','warmup'],default='legacy')
    parser.add_argument('--query-duration',type=int,default=60);parser.add_argument('--upload-timeout',type=float,default=600)
    parser.add_argument('--duration',type=int,default=90);parser.add_argument('--pre-seconds',type=int,default=10)
    return parser.parse_args()

if __name__=='__main__':run_trial(arguments())
