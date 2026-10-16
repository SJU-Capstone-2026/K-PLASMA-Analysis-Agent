#!/usr/bin/env python3
"""Parallel upload aggregation: interval sums are not wall-clock time."""
import collections
import json
from pathlib import Path
from analyze_upload_query_benchmark import describe, summarize_queries


def partition(dataset, width):
    if width not in (1,2,4,8):raise ValueError('Unsupported worker count')
    groups=collections.defaultdict(list)
    for e in dataset['entries']:
        parts=e['relativePath'].split('/')
        if len(parts)<4:raise ValueError('Every file must belong to a Run bundle')
        groups['/'.join(parts[:3])].append(e)
    quotas=[len(groups)//width+(i<len(groups)%width) for i in range(width)]
    buckets=[[] for _ in range(width)];weights=[0]*width
    # Full bundles, including ancillary files; byte volume is a fixed parsing-cost proxy.
    for key,entries in sorted(groups.items(),key=lambda kv:(-sum(e['size'] for e in kv[1]),kv[0])):
        i=min((i for i in range(width) if len(buckets[i])<quotas[i]),key=lambda i:(weights[i],i))
        buckets[i].append((key,entries));weights[i]+=sum(e['size'] for e in entries)
    parts=[dict(entries=[e for _,es in b for e in es],roots=[k for k,_ in b],bytes=weights[i]) for i,b in enumerate(buckets)]
    names=[e['relativePath'] for p in parts for e in p['entries']]
    if len(set(names))!=len(names) or sorted(names)!=sorted(e['relativePath'] for e in dataset['entries']):
        raise ValueError('Partition dropped or duplicated input')
    return parts


def concurrency(spans,window):
    points=[]
    for e in spans:
        a,b=max(window[0],e['startNs']),min(window[1],e['endNs'])
        if a<b:points.extend([(a,1),(b,-1)])
    active=peak=0;area=0;last=window[0]
    for t,delta in sorted(points):
        area+=active*(t-last);last=t;active+=delta;peak=max(peak,active)
    return dict(peak=peak,mean=area/(window[1]-window[0]) if window[1]>window[0] else 0)


def summarize_upload(events,batches,expected):
    roots=[e for e in events if e['phase']==e['kind'] and e.get('batchId') in batches and e['kind'] in ('request','claim','job')]
    ids={(e['kind'],e['id']) for e in roots}
    related=[e for e in events if (e['kind'],e['id']) in ids]
    select=lambda p:[e for e in related if e['phase']==p]
    jobs=select('job');claims=select('claim');terminal=select('job.terminal');requests=select('request')
    if len(jobs)!=expected or len(claims)!=expected or len(terminal)!=expected:raise ValueError('Incomplete job traces')
    if len({e['id'] for e in jobs})!=expected or {e['jobId'] for e in claims}!={e['id'] for e in jobs}:raise ValueError('Duplicate or uncorrelated claims')
    ready={e['batchId']:e['endNs'] for e in select('queue.ready')}
    if set(ready)!=set(batches) or len(requests)!=len(batches):raise ValueError('Incomplete intake trace')
    window=[min(e['startNs'] for e in requests),max(e['endNs'] for e in terminal)]
    queue_wait=[(e['endNs']-ready[e['batchId']])/1e6 for e in claims]
    if min(queue_wait)<0:raise ValueError('Claim precedes queue commit')
    def phase_summary(rows):
        phases=collections.defaultdict(list)
        for e in rows:phases[e['phase']].append((e['endNs']-e['startNs'])/1e6)
        return {p:dict(describe(v),sum=sum(v)) for p,v in phases.items()}
    intake=phase_summary([e for e in related if e['kind']=='request'])
    worker=phase_summary([e for e in related if e['kind'] in ('job','claim')])
    held=lambda p:p.get('db.connection_held',{}).get('sum',0)/1000
    parses=[e for e in related if e['phase'] in ('parse.scalar','parse.graph')]
    return dict(windowNs=window,workerWindowNs=[max(ready.values()),window[1]],server_total_ms=(window[1]-window[0])/1e6,
                intake=intake,worker=worker,intake_held_s=held(intake),worker_held_s=held(worker),
                total_held_s=held(intake)+held(worker),queue_wait_ms=describe(queue_wait),
                active_workers=concurrency(jobs,window),active_parsers=concurrency(parses,window),
                worker_threads=sorted({e['workerThread'] for e in jobs}),job_count=len(jobs))


def summarize(path,window_override=None):
    meta=json.loads((path/'result.json').read_text())
    events=[json.loads(x) for x in (path/'timing.jsonl').read_text().splitlines() if x.strip()]
    upload=summarize_upload(events,meta['batchIds'],meta['expectedJobs'])
    clients=[json.loads(x) for x in (path/'lookup.jsonl').read_text().splitlines() if x.startswith('{')] if (path/'lookup.jsonl').exists() else []
    events=[e for e in events if e['kind']!='lookup' or e['id'].startswith(meta['label']+'-')]
    window=window_override or upload['windowNs']
    lookup=summarize_queries(events,clients,window)
    lookup['cohorts']=sorted({r['cohort'] for r in lookup['rows']})
    lookup['start_delay_ms']=describe([r['startEpochMs']-r['scheduledEpochMs'] for r in lookup['rows']])
    lookup['all_client_count']=len(clients)
    lookup['all_errors']=sum(r['status']!=200 or not r['valid'] for r in clients)
    # Complete final cohort is observed before intentional k6 interruption.
    counts=collections.Counter(r['cohort'] for r in clients)
    expected=(max(counts)+1)*100 if counts else 0
    lookup['missing_scheduled_requests']=expected-len(clients) if clients else 0
    lookup['cohort_counts']=dict(sorted(counts.items()))
    pool=[e for e in events if e['kind']=='pool' and window[0]<=e['startNs']<=window[1]]
    lookup['pool']=dict(samples=len(pool),configured_maxima=sorted({e['maximum'] for e in pool}),
        configured_minima=sorted({e['minimumIdle'] for e in pool}),active_peak=max((e['active'] for e in pool),default=0),
        active_mean=sum(e['active'] for e in pool)/len(pool) if pool else None,
        pending_peak=max((e['pending'] for e in pool),default=0),pending_samples=sum(e['pending']>0 for e in pool),
        pending_fraction=sum(e['pending']>0 for e in pool)/len(pool) if pool else None)
    worker_lookup=summarize_queries(events,clients,upload['workerWindowNs'])
    lookup['after_intake']={k:v for k,v in worker_lookup.items() if k!='rows'}
    lookup.pop('rows')
    return dict(**meta,upload=upload,lookup=lookup)


def aggregate(root):
    """Keep repeat-level observations and compare equal elapsed windows for each pair."""
    rows=[json.loads(p.read_text()) for p in sorted((root/'results').glob('*/summary.json'))]
    for w in (1,2,4,8):
        for index in (1,2,3):
            pair=[r for r in rows if r['workers']==w and r['index']==index]
            if len(pair)!=2:continue
            common=min(r['upload']['windowNs'][1]-r['upload']['windowNs'][0] for r in pair)
            for r in pair:
                start=r['upload']['windowNs'][0]
                r['commonLookup']=summarize(root/'results'/r['label'],[start,start+common])['lookup']
                r['commonWindowMs']=common/1e6
    (root/'aggregate.json').write_text(json.dumps(rows,indent=2))
    return rows


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path)
    a=p.parse_args();rows=aggregate(a.root)
    print(json.dumps(dict(completed=len(rows),labels=[r['label'] for r in rows])))
