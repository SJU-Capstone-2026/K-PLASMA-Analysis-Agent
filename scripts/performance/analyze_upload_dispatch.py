#!/usr/bin/env python3
"""Audit offered load separately from server entry. Never select by latency outcome."""
import collections
import json
from pathlib import Path
from analyze_upload_query_benchmark import describe, summarize_queries

# Millisecond client clock; gates describe a synchronized burst, not exact wire equality.
LIMITS = dict(max_lateness_ms=5, max_spread_ms=5, max_pair_spread_difference_ms=3,
              max_pair_mean_lateness_difference_ms=3, min_worker_fraction=.75)


def load_trial(path):
    meta=json.loads((path/'result.json').read_text())
    events=[json.loads(x) for x in (path/'timing.jsonl').read_text().splitlines() if x.strip()]
    clients=[json.loads(x) for x in (path/'lookup.jsonl').read_text().splitlines() if x.startswith('{')]
    events=[e for e in events if e['kind']!='lookup' or e['id'].startswith(meta['label']+'-')]
    measured=summarize_queries(events,clients,None)
    roots=[e for e in events if e['phase']==e['kind'] and e.get('batchId') in meta['batchIds']]
    worker_ids={(e['kind'],e['id']) for e in roots if e['kind'] in ('job','claim')}
    jobs=[e for e in roots if e['kind']=='job']
    held=[e for e in events if e['phase']=='db.connection_held' and (e['kind'],e['id']) in worker_ids]
    counts=lambda spans,t:sum(e['startNs']<=t<e['endNs'] for e in spans)
    result={}
    for cohort in sorted({r['cohort'] for r in measured['rows']}):
        rows=[r for r in measured['rows'] if r['cohort']==cohort]
        monotonic=all('startMonoMs' in r for r in rows)
        starts=[r['startMonoMs'] if monotonic else r['startEpochMs'] for r in rows]
        server=[r['serverStartNs'] for r in rows]
        lateness=[r['startMonoMs']-r['scheduledMonoMs'] if monotonic else r['startEpochMs']-r['scheduledEpochMs'] for r in rows]
        result[cohort]=dict(clock='monotonic' if monotonic else 'wall',count=len(rows),unique_vus=len({r['vu'] for r in rows}),
            query_mix=dict(collections.Counter(r['version'] for r in rows)),
            query_by_vu={str(r['vu']):r['version'] for r in rows},
            errors=sum(r['status']!=200 or not r['valid'] for r in rows),
            scheduled_epoch_ms=sorted({r['scheduledEpochMs'] for r in rows}),
            first_call_clock_ms=min(starts),last_call_clock_ms=max(starts),
            finish_send_spread_ms=(max(r['sentMonoMs'] for r in rows)-min(r['sentMonoMs'] for r in rows)) if monotonic and all(r.get('sentMonoMs') is not None for r in rows) else None,
            call_spread_ms=max(starts)-min(starts),lateness_ms={**describe(lateness),'min':min(lateness)},
            server_entry_spread_ms=(max(server)-min(server))/1e6,
            active_workers=describe([counts(jobs,t) for t in server]),
            upload_connections=describe([counts(held,t) for t in server]))
        for field in ['elapsedMs','db_acquire_ms','held_ms','sql_ms','server_ms','blockedMs',
                      'connectingMs','sendingMs','waitingMs','receivingMs']:
            result[cohort][field]=describe([r[field] for r in rows if r.get(field) is not None])
    return dict(label=meta['label'],workers=meta['workers'],cohorts=result)


def reasons(before,after,workers,require_same_vu=False):
    result=[]
    for label,row in [('B',before),('C',after)]:
        if row['count']!=100 or row['unique_vus']!=100:result.append(label+': incomplete burst')
        if row['errors']:result.append(label+': query errors')
        if len(row['scheduled_epoch_ms'])!=1:result.append(label+': inconsistent schedule')
        delay=row['lateness_ms']
        if delay['min']<0 or delay['max']>LIMITS['max_lateness_ms']:result.append(label+': dispatch lateness')
        if row['call_spread_ms']>LIMITS['max_spread_ms']:result.append(label+': dispatch spread')
        if row['active_workers']['mean']<workers*LIMITS['min_worker_fraction']:result.append(label+': insufficient active upload workers')
    if before['upload_connections']['mean']<workers*LIMITS['min_worker_fraction']:result.append('B: insufficient upload connection occupancy')
    if before['query_mix']!=after['query_mix']:result.append('different query mix')
    if require_same_vu and before['query_by_vu']!=after['query_by_vu']:result.append('different query per VU')
    if abs(before['call_spread_ms']-after['call_spread_ms'])>LIMITS['max_pair_spread_difference_ms']:result.append('different dispatch spread')
    if abs(before['lateness_ms']['mean']-after['lateness_ms']['mean'])>LIMITS['max_pair_mean_lateness_difference_ms']:result.append('different dispatch offset')
    return result


def compare(root,workers=(4,8),repeats=(1,2,3),require_same_vu=False):
    pairs=[]
    for w in workers:
        for index in repeats:
            paths={v:root/'results'/f'{v}-w{w}-{index}' for v in ['B','C']}
            if not all((p/'result.json').exists() for p in paths.values()):continue
            trials={v:load_trial(p) for v,p in paths.items()}
            cohorts=[]
            for c in sorted(set(trials['B']['cohorts'])&set(trials['C']['cohorts'])):
                b=trials['B']['cohorts'][c];a=trials['C']['cohorts'][c]
                why=reasons(b,a,w,require_same_vu)
                cohorts.append(dict(cohort=c,B=b,C=a,eligible=not why,reasons=why))
            pairs.append(dict(workers=w,repeat=index,cohorts=cohorts))
    return dict(limits=LIMITS,wire_timestamps_available=False,
        note='startEpochMs is immediately before k6 http.get; Date.now has millisecond resolution. Server uses a separate monotonic clock.',pairs=pairs)


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('root',type=Path);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--workers',type=int,nargs='+',default=[4,8]);p.add_argument('--repeats',type=int,nargs='+',default=[1,2,3])
    p.add_argument('--same-vu',action='store_true')
    args=p.parse_args()
    result=compare(args.root,args.workers,args.repeats,args.same_vu)
    args.output.write_text(json.dumps(result,indent=2))
    for pair in result['pairs']:
        print(json.dumps(dict(workers=pair['workers'],repeat=pair['repeat'],eligible=[c['cohort'] for c in pair['cohorts'] if c['eligible']])))
