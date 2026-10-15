#!/usr/bin/env python3
"""End-to-end upload benchmark. Refuses to reset any database except an isolated benchmark container."""
import argparse
import collections
import hashlib
import http.client
import json
import math
import os
import shutil
import socket
import statistics
import subprocess
import time
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

DB_USER = DB_NAME = "upload_benchmark"
ACTIVE = {"QUEUED", "PROCESSING"}

def sql(container, query):
    if not container.startswith("kplasma-upload-benchmark-"):
        raise ValueError("Only a dedicated upload benchmark container is allowed")
    result = subprocess.run(["docker","exec",container,"psql","-U",DB_USER,"-d",DB_NAME,"-v","ON_ERROR_STOP=1","-Atc",query],
                            check=True,capture_output=True,text=True)
    return result.stdout.strip()

def get(base, path):
    u=urlsplit(base)
    assert u.hostname in {"127.0.0.1","localhost"}
    connection=http.client.HTTPConnection(u.hostname,u.port,timeout=180)
    try:
        connection.request("GET",path)
        response=connection.getresponse();body=response.read()
        if response.status!=200: raise RuntimeError(f"GET {path}: {response.status} {body[:300]!r}")
        return json.loads(body)
    finally: connection.close()

def post(base, dataset, mode, key, zip_path=None):
    u=urlsplit(base);boundary="kplasma-benchmark-fixed-boundary-20261015"
    if mode=="ZIP":
        uploads=[("archive","original.zip",zip_path)]
        manifest={"mode":"ZIP","entries":[{"partName":"archive","relativePath":"original.zip"}]}
    else:
        uploads=[(f"f{i}",Path(e["relativePath"]).name,Path(e["path"])) for i,e in enumerate(dataset["entries"])]
        manifest={"mode":"FOLDER","entries":[{"partName":f"f{i}","relativePath":e["relativePath"]} for i,e in enumerate(dataset["entries"])]}
    def header(name, filename=None):
        disposition=f'Content-Disposition: form-data; name="{name}"'
        if filename is not None: disposition+=f'; filename="{filename}"'
        return f"--{boundary}\r\n{disposition}\r\nContent-Type: application/octet-stream\r\n\r\n".encode()
    manifest_data=json.dumps(manifest).encode()
    manifest_header=header("manifest")
    end=f"--{boundary}--\r\n".encode()
    parts=[(header(name,filename),path) for name,filename,path in uploads]
    length=len(manifest_header)+len(manifest_data)+2+sum(len(h)+p.stat().st_size+2 for h,p in parts)+len(end)
    connection=http.client.HTTPConnection(u.hostname,u.port,timeout=600)
    started=time.perf_counter_ns()
    try:
        connection.putrequest("POST","/api/import-batches")
        connection.putheader("Content-Type",f"multipart/form-data; boundary={boundary}")
        connection.putheader("Content-Length",str(length));connection.putheader("Idempotency-Key",key)
        connection.endheaders()
        connection.send(manifest_header);connection.send(manifest_data);connection.send(b"\r\n")
        for h,p in parts:
            connection.send(h)
            with p.open("rb") as stream:
                while data:=stream.read(1024*1024): connection.send(data)
            connection.send(b"\r\n")
        connection.send(end);sent=time.perf_counter_ns()
        response=connection.getresponse();body=response.read();accepted=time.perf_counter_ns()
        if response.status!=202: raise RuntimeError(f"POST {response.status}: {body[:500]!r}")
        return json.loads(body),started,sent,accepted,length
    finally: connection.close()

def make_zip(dataset, path):
    if path.exists(): return
    with zipfile.ZipFile(path,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=1) as archive:
        for entry in dataset["entries"]: archive.write(entry["path"],entry["relativePath"])

def normalize(run):
    return {key:value for key,value in run.items() if key not in {"runVersionId","registeredAt"}}

def verify(base, container, dataset, scenario, golden=None):
    runs=get(base,"/api/runs")
    expected=dataset.get("expected",{})
    if len(runs)!=len(expected or dataset["runIds"]): raise AssertionError(f"Expected {len(expected)} runs, received {len(runs)}")
    full={}
    for run in runs:
        ident=run["runId"]
        if expected:
            want=expected[ident]
            for field in ["pressure","sourcePower","biasPower"]:
                assert run[field]==want[field],(ident,field,run[field],want[field])
            for field in ["meanIonEnergy","ionFlux","iedWidth"]:
                actual,target=run["metrics"][field],want[field]
                assert actual is None and target is None or actual is not None and target is not None and math.isclose(actual,target,rel_tol=1e-12),(ident,field,actual,target)
        full[ident]=normalize(get(base,"/api/run-versions/"+run["runVersionId"]))
    if golden is not None: assert full==golden,"Version-independent scalar/sample parity mismatch"
    # All metadata SHA-256 values must match the original input, independently of the parser.
    stored=json.loads(sql(container,"select json_agg(json_build_object('runId',r.run_id,'name',f.relative_path,'hash',f.sha256)) from run r join run_version v on v.id=r.current_version_id join source_file f on f.source_id=v.source_id"))
    source={(row["runId"],row["name"]):row["hash"] for row in stored}
    for entry in dataset["entries"]:
        parts=entry["relativePath"].split("/")
        p=int(parts[0].split("_")[1]);s=int(parts[1].split("_")[1]);b=int(parts[2].split("_")[1])
        assert source[(f"RUN-P{p:02}-S{s:03}-B{b:04}","/".join(parts[3:]))]==entry["sha256"]
    versions=int(sql(container,"select count(*) from run_version"))
    assert versions==len(runs)*(2 if scenario=="update" else 1),(scenario,versions)
    return full

def events_for(log, offset, batch):
    with log.open() as stream:
        stream.seek(offset);events=[json.loads(line) for line in stream if line.strip()]
    contexts={(e["kind"],e["id"]) for e in events if e["batchId"]==batch}
    return [e for e in events if (e["kind"],e["id"]) in contexts]

def summarize_events(events):
    durations=collections.defaultdict(float);counts=collections.Counter();byte_counts=collections.Counter()
    for event in events:
        name=event["phase"]
        durations[name]+=(event["endNs"]-event["startNs"])/1e6
        counts[name]+=1;byte_counts[name]+=event.get("bytes",0)
    requests=[e for e in events if e["phase"]=="request"]
    jobs=sorted([e for e in events if e["phase"]=="job"],key=lambda e:e["startNs"])
    terminals=[e["endNs"] for e in events if e["phase"]=="job.terminal"]
    ready=[e["endNs"] for e in events if e["phase"]=="queue.ready"]
    if not requests or not jobs or not terminals or not ready: raise AssertionError("Incomplete timing trace")
    first_gap=(jobs[0]["startNs"]-ready[-1])/1e6
    gaps=[(b["startNs"]-a["endNs"])/1e6 for a,b in zip(jobs,jobs[1:])]
    assert min(gaps or [0])>=0,"Unexpected concurrent workers"
    total=(max(terminals)-min(e["startNs"] for e in requests))/1e6
    file_ms=sum(durations[k] for k in ["file.controller_copy","file.staging_copy_hash","file.promote_move","file.zip_container_scan"])
    parse_ms=durations["parse.scalar"]+durations["parse.graph"]
    db_ms=durations["db.execute"]+durations["db.commit"]+durations["db.acquire"]
    queue_ms=first_gap+sum(gaps)
    return {"server_total_ms":total,"queue_first_gap_ms":first_gap,"inter_job_gap_ms":sum(gaps),
            "queue_ms":queue_ms,"file_ms":file_ms,"parse_ms":parse_ms,"db_ms":db_ms,
            "other_ms":total-queue_ms-file_ms-parse_ms-db_ms,
            "connection_held_ms":durations["db.connection_held"],
            "transaction_ms":sum(value for key,value in durations.items() if key.startswith("tx.")),
            "sql_calls":counts["db.execute"],"commit_calls":counts["db.commit"],
            "phase_ms":dict(durations),"phase_counts":dict(counts),"phase_bytes":dict(byte_counts)}

def clear(container, storage):
    assert storage.name=="storage" and "performance/upload" in str(storage.resolve())
    assert int(sql(container,"select count(*) from import_job where status in ('QUEUED','PROCESSING')"))==0,"Jobs still active"
    sql(container,"truncate import_batch,source_set,run cascade")
    shutil.rmtree(storage,ignore_errors=True);storage.mkdir()
    sql(container,"select pg_stat_statements_reset()")

def save_seed(container, storage, seed):
    seed.mkdir(parents=True,exist_ok=True)
    tables=["import_batch","source_set","source_file","import_batch_file","import_job","import_idempotency","run","run_version","reprocess_idempotency"]
    command=["docker","exec",container,"pg_dump","-U",DB_USER,"-d",DB_NAME,"--data-only","--disable-triggers"]
    command += [argument for table in tables for argument in ["--table",table]]
    with (seed/"data.sql").open("wb") as stream: subprocess.run(command,stdout=stream,check=True)
    shutil.copytree(storage,seed/"storage",copy_function=os.link,dirs_exist_ok=True)

def restore_seed(container, storage, seed):
    clear(container,storage)
    with (seed/"data.sql").open("rb") as stream:
        subprocess.run(["docker","exec","-i",container,"psql","-U",DB_USER,"-d",DB_NAME,"-v","ON_ERROR_STOP=1"],stdin=stream,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=True)
    shutil.copytree(seed/"storage",storage,copy_function=os.link,dirs_exist_ok=True)
    sql(container,"select pg_stat_statements_reset()")

def run_batch(args, dataset, label, scenario, measured, seed=None, golden=None):
    if scenario in {"duplicate","update"}: restore_seed(args.container,args.storage,seed)
    else: clear(args.container,args.storage)
    offset=args.timing.stat().st_size if args.timing.exists() else 0
    zipped=None
    if scenario=="zip":
        zipped=args.manifest.parent/"original.zip";make_zip(dataset,zipped)
    info,t0,sent,accepted,wire=post(args.base,dataset,"ZIP" if scenario=="zip" else "FOLDER",str(uuid.uuid4()),zipped)
    batch=info["batchId"];deadline=time.monotonic()+args.timeout
    while info["status"] in ACTIVE:
        if time.monotonic()>deadline: raise TimeoutError(f"Batch {batch} not terminal")
        time.sleep(1);info=get(args.base,"/api/import-batches/"+batch)
    end=time.perf_counter_ns()
    if info["status"]!="SUCCESS": raise AssertionError(info)
    want="DUPLICATE" if scenario=="duplicate" else "READY"
    assert all(job["status"]==want for job in info["jobs"]),collections.Counter(job["status"] for job in info["jobs"])
    assert len(info["jobs"])==150
    time.sleep(.02)
    events=events_for(args.timing,offset,batch) if args.timing.exists() else []
    metrics={} if args.no_timing else summarize_events(events)
    query_stats=json.loads(sql(args.container,"select coalesce(json_agg(json_build_object('query',query,'calls',calls,'executionMs',total_exec_time,'planningMs',total_plan_time)),'[]') from pg_stat_statements where dbid=(select oid from pg_database where datname=current_database())"))
    result={"variant":args.variant,"label":label,"scenario":scenario,"measured":measured,
            "artificial":dataset["artificial"],"dataset_hash":dataset["datasetHash"],"batchId":batch,
            "client_total_ms":(end-t0)/1e6,"accept_ms":(accepted-t0)/1e6,"send_ms":(sent-t0)/1e6,"wire_bytes":wire,
            "jobs":len(info["jobs"]),"status":info["status"],**metrics}
    full=verify(args.base,args.container,dataset,scenario,golden)
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/(label+".json")).write_text(json.dumps({"result":result,"sql":query_stats},indent=2))
    print(json.dumps(result),flush=True)
    return result,full

def main():
    parser=argparse.ArgumentParser()
    for name in ["variant","base","container"]: parser.add_argument("--"+name,required=True)
    for name in ["manifest","timing","storage","output"]: parser.add_argument("--"+name,type=Path,required=True)
    parser.add_argument("--iterations",type=int,default=10);parser.add_argument("--warmups",type=int,default=1)
    parser.add_argument("--timeout",type=float,default=600);parser.add_argument("--scenario",choices=["new","zip","duplicate","update","private"],default="new")
    parser.add_argument("--start-index",type=int,default=0)
    parser.add_argument("--seed",type=Path);parser.add_argument("--save-seed",type=Path)
    parser.add_argument("--golden",type=Path);parser.add_argument("--no-timing",action="store_true")
    args=parser.parse_args()
    dataset=json.loads(args.manifest.read_text())
    golden=json.loads(args.golden.read_text()) if args.golden and args.golden.exists() else None
    results=[]
    for i in range(args.warmups+args.iterations):
        label=f"{args.variant}-{args.scenario}-{i-args.warmups+1+args.start_index:02}"
        try:
            result,full=run_batch(args,dataset,label,args.scenario,i>=args.warmups,args.seed,golden)
        except Exception as error:
            args.output.mkdir(parents=True,exist_ok=True)
            (args.output/(label+"-failure.json")).write_text(json.dumps({"variant":args.variant,"label":label,
                "scenario":args.scenario,"errorType":type(error).__name__,"error":str(error)[:2000]},indent=2))
            raise
        if args.golden and golden is None: args.golden.parent.mkdir(parents=True,exist_ok=True);args.golden.write_text(json.dumps(full));golden=full
        if args.save_seed and not (args.save_seed/"data.sql").exists(): save_seed(args.container,args.storage,args.save_seed)
        if i>=args.warmups:results.append(result)
    (args.output/f"summary-{args.scenario}.json").write_text(json.dumps(results,indent=2))
    names=["client_total_ms","server_total_ms","queue_ms","file_ms","parse_ms","db_ms","connection_held_ms","transaction_ms"]
    print(json.dumps({"summary":{name:{"mean":statistics.mean(r[name] for r in results),"median":statistics.median(r[name] for r in results)}
                     for name in names if all(name in r for r in results)}}),flush=True)

if __name__=="__main__":main()
