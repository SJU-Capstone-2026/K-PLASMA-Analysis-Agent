"""Local synthetic measurements; uses the actual product SQL and Agent worker."""
import argparse
import copy
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import httpx
from seed import ROOT, seed, sql, make_run

URL = 'http://127.0.0.1:18088'


def timeout_handler(*_):
    raise TimeoutError('60-second request deadline exceeded')


def query(scenario):
    result = {'constraints': [{'metric': 'meanIonEnergy', 'operator': 'between', 'min': 150, 'max': 160, 'unit': 'eV'}], 'goals': [{'metric': 'ionFlux', 'direction': 'maximize', 'unit': '10¹⁸ m⁻²s⁻¹'}]}
    if scenario == 'no_match':
        result['constraints'][0].update(min=1e12, max=1e12+10)
    if scenario == 'sort_only':
        result['constraints'] = []
    return result


def append(path, value):
    with path.open('a') as f:
        f.write(json.dumps(value, ensure_ascii=False, allow_nan=False)+'\n')


def identity(client):
    value=client.get('/benchmark/identity').json()
    assert value['marker']=='reverse-lookup-synthetic-only' and value['database']=='reverse_lookup_bench'
    return value


def summarize(rows):
    good=[r for r in rows if r['ok']]
    times=[r['totalMs'] for r in good]
    value={'samples':len(rows),'successes':len(good),'failures':len(rows)-len(good)}
    for field in ['totalMs','dbMs','fetchMs','inventoryMs','serializeMs','bytes','rows','sqlCount','catalogRefs']:
        numbers=[r[field] for r in good if field in r]
        if numbers:value[field+'Mean']=statistics.mean(numbers)
    if times:value.update(medianMs=statistics.median(times),p95Ms=sorted(times)[math.ceil(len(times)*.95)-1])
    return value


def measure(output, method, scenario='match', samples=200):
    output.mkdir(parents=True,exist_ok=True)
    path=output/f'{method}-{scenario}-query.jsonl'
    if path.exists():raise ValueError('Refusing to overwrite '+str(path))
    with httpx.Client(base_url=URL,timeout=60) as client:
        runtime=identity(client)
        (output/f'{method}-runtime.json').write_text(json.dumps(runtime,indent=2))
        warmups=5
        try:
            plan=client.post('/benchmark/explain',json=query(scenario));plan.raise_for_status()
            (output/f'{method}-{scenario}-plan.json').write_text(json.dumps(plan.json(),indent=2))
        except httpx.HTTPError as error:
            (output/f'{method}-{scenario}-explain-error.json').write_text(json.dumps({'error':type(error).__name__,'detail':str(error)[:400]}))
            samples=1;warmups=0
        records=[]
        for index in range(samples+warmups):
            begin=time.perf_counter_ns()
            record={'index':index,'warmup':index<warmups,'method':method,'scenario':scenario,'ok':False}
            try:
                response=client.post('/benchmark/query',json=query(scenario));response.raise_for_status()
                runs=response.json()['runs']
                if scenario=='match':
                    expected=[make_run(i)['runVersionId'] for i in reversed(range(5))]
                    assert [r['runVersionId'] for r in runs]==expected, 'Independent candidate oracle mismatch'
                    assert [r['metrics'] for r in runs]==[make_run(i)['metrics'] for i in reversed(range(5))]
                if scenario=='no_match' and method!='a':assert not runs
                record.update(ok=True,rows=len(runs),bytes=len(response.content),sqlCount=int(response.headers['X-Bench-Queries']),dbMs=float(response.headers['X-Bench-Db-Ms']),fetchMs=float(response.headers['X-Bench-Fetch-Ms']),inventoryMs=float(response.headers['X-Bench-Inventory-Ms']),serializeMs=float(response.headers['X-Bench-Serialize-Ms']),catalogRefs=int(response.headers['X-Bench-Catalog-Refs']))
            except AssertionError:raise
            except Exception as error:record.update(error=type(error).__name__,detail=str(error)[:400])
            record['totalMs']=(time.perf_counter_ns()-begin)/1e6
            append(path,record)
            if index>=warmups:records.append(record)
            if not record['ok']:break
        summary=summarize(records)
        (output/f'{method}-{scenario}-summary.json').write_text(json.dumps(summary,indent=2))
        print(method,scenario,summary,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--method',choices=['a','b','c'],required=True);p.add_argument('--size',type=int);p.add_argument('--samples',type=int,default=200);p.add_argument('--scenario',default='match',choices=['match','no_match','sort_only']);args=p.parse_args()
    if args.size:seed(args.size,args.output)
    measure(args.output,args.method,args.scenario,args.samples)
