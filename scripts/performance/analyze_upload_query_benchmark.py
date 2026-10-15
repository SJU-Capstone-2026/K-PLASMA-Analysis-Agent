#!/usr/bin/env python3
"""Join measured lookup traces by ID; keep failures and use batches as experimental units."""
import argparse
import collections
import json
import math
import random
import statistics
from pathlib import Path


def describe(values):
    values=sorted(values)
    if not values:return dict(n=0,mean=None,median=None,p95=None,max=None)
    index=(len(values)-1)*.95;lo=math.floor(index);hi=math.ceil(index)
    return dict(n=len(values),mean=statistics.mean(values),median=statistics.median(values),
                p95=values[lo]+(values[hi]-values[lo])*(index-lo),max=values[-1])


def paired_delta(before,after):
    if not before or len(before)!=len(after):raise ValueError('Paired batches required')
    delta=[a-b for a,b in zip(before,after)];rng=random.Random(20261015)
    bootstrap=sorted(statistics.mean(rng.choices(delta,k=len(delta))) for _ in range(5000))
    baseline=statistics.mean(before)
    return dict(n=len(delta),before_mean=baseline,after_mean=statistics.mean(after),mean_reduction_ms=statistics.mean(delta),
                reduction_percent=100*statistics.mean(delta)/baseline if baseline else None,
                bootstrap95=[bootstrap[124],bootstrap[4874]],per_pair=delta)


def summarize_queries(events,clients,window):
    by_id={}
    for row in clients:
        if row['id'] in by_id:raise ValueError('Duplicate client request ID')
        by_id[row['id']]=row
    phases=collections.defaultdict(list);roots={}
    for e in events:
        if e['kind']!='lookup':continue
        phases[e['id']].append(e)
        if e['phase']=='lookup':
            if e['id'] in roots:raise ValueError('Duplicate server request ID')
            roots[e['id']]=e
    # Preflight/verifications have different IDs, so callers pass the matching trial slice only.
    missing=set(roots)-set(by_id)
    if missing:raise ValueError(f'Missing client correlations: {len(missing)}')
    rows=[]
    for ident,root in roots.items():
        if window and not window[0]<=root['startNs']<=window[1]:continue
        client=by_id[ident];spans=phases[ident]
        selected=lambda name:[x for x in spans if x['phase']==name]
        elapsed=lambda name:sum((x['endNs']-x['startNs'])/1e6 for x in selected(name))
        rows.append(dict(**client,server_ms=(root['endNs']-root['startNs'])/1e6,
                         db_acquire_ms=elapsed('db.acquire'),sql_ms=elapsed('db.execute'),held_ms=elapsed('db.connection_held'),
                         acquire_count=len(selected('db.acquire')),sql_count=len(selected('db.execute')),
                         acquire_errors=sum(x.get('outcome')=='error' for x in selected('db.acquire')),
                         serverStartNs=root['startNs'],serverEndNs=root['endNs']))
    success=[r for r in rows if r['status']==200 and r['valid']]
    result=dict(count=len(rows),success=len(success),errors=len(rows)-len(success),
                timeouts=sum(r.get('errorCode')==1050 for r in rows),
                invalid_payloads=sum(r['status']==200 and not r['valid'] for r in rows),
                acquire_errors=sum(r['acquire_errors'] for r in rows),sql_calls=sum(r['sql_count'] for r in rows),
                unmatched_clients=[r for i,r in by_id.items() if i not in roots],
                status_counts=dict(collections.Counter(str(r['status']) for r in rows)))
    for field in ['elapsedMs','durationMs','server_ms','db_acquire_ms','sql_ms','held_ms']:
        result[{'elapsedMs':'client_ms','durationMs':'http_duration_ms'}.get(field,field)]=describe([r[field] for r in rows])
    result['success_client_ms']=describe([r['elapsedMs'] for r in success])
    result['by_version']={v:dict(count=len(sub),client_ms=describe([r['elapsedMs'] for r in sub]),db_acquire_ms=describe([r['db_acquire_ms'] for r in sub]))
                          for v in sorted({r['version'] for r in rows}) if (sub:=[r for r in rows if r['version']==v])}
    result['rows']=rows
    return result


def analyze_trial(path):
    meta=json.loads((path/'result.json').read_text())
    events=[json.loads(x) for x in (path/'timing.jsonl').read_text().splitlines() if x.strip()]
    clients=[]
    for line in (path/'lookup.jsonl').read_text().splitlines() if (path/'lookup.jsonl').exists() else []:
        if line.startswith('{'):clients.append(json.loads(line))
    prefix=meta['label']+'-'
    lookup=[e for e in events if e['kind']!='lookup' or e['id'].startswith(prefix)]
    window=meta.get('windowNs')
    if meta.get('timingEnabled',True):
        measured=summarize_queries(lookup,clients,window)
    else:
        epoch_window=meta.get('clientWindowEpochMs')
        selected=[r for r in clients if not epoch_window or epoch_window[0]<=r['startEpochMs']<=epoch_window[1]]
        # Synthetic correlation roots are used only for grouping client records, never as measured server times.
        roots=[dict(kind='lookup',id=r['id'],phase='lookup',startNs=0,endNs=0,status=r['status']) for r in selected]
        measured=summarize_queries(roots,selected,None)
        for field in ['server_ms','db_acquire_ms','sql_ms','held_ms']:measured[field]=describe([])
        for row in measured['rows']:
            for field in ['server_ms','db_acquire_ms','sql_ms','held_ms','serverStartNs','serverEndNs']:row[field]=None
        for row in measured['by_version'].values():row['db_acquire_ms']=describe([])
    epoch_window=meta.get('clientWindowEpochMs')
    overhead_clients=[r for r in clients if not epoch_window or epoch_window[0]<=r['startEpochMs']<=epoch_window[1]]
    measured['client_epoch_window_ms']=describe([r['elapsedMs'] for r in overhead_clients])
    pool=[e for e in events if e['kind']=='pool' and (not window or window[0]<=e['startNs']<=window[1])]
    measured['pool']=dict(samples=len(pool),pending_max=max((e['pending'] for e in pool),default=0),
                          pending_fraction=sum(e['pending']>0 for e in pool)/len(pool) if pool else None,
                          active_max=max((e['active'] for e in pool),default=0))
    parse=[e for e in events if e['phase'] in {'parse.scalar','parse.graph'}]
    parse_rows=[r for r in measured['rows'] if r['serverStartNs'] is not None and any(e['startNs']<=r['serverStartNs']<=e['endNs'] for e in parse)]
    measured['started_during_parse']=dict(n=len(parse_rows),client_ms=describe([r['elapsedMs'] for r in parse_rows]),db_acquire_ms=describe([r['db_acquire_ms'] for r in parse_rows]))
    if (path/'k6-summary.json').exists():
        k6=json.loads((path/'k6-summary.json').read_text())
        measured['dropped_iterations']=k6.get('metrics',{}).get('dropped_iterations',{}).get('values',{}).get('count',0)
    measured['all_client_requests']=len(clients)
    measured['all_client_errors']=sum(r['status']!=200 or not r['valid'] for r in clients)
    measured['all_invalid_payloads']=sum(r['status']==200 and not r['valid'] for r in clients)
    duration=meta.get('configuredDuration')
    measured['achieved_start_rate']=len(clients)/duration if duration else None
    measured['pool']['configured_maxima']=sorted({e['maximum'] for e in pool if 'maximum' in e})
    measured['pool']['configured_minima']=sorted({e['minimumIdle'] for e in pool if 'minimumIdle' in e})
    ready=[e['endNs'] for e in events if e['phase']=='queue.ready']
    worker_start=max(ready) if ready else None
    worker_rows=[r for r in measured['rows'] if worker_start is not None and r['serverStartNs'] is not None and r['serverStartNs']>=worker_start]
    worker_pool=[e for e in pool if worker_start is not None and e['startNs']>=worker_start]
    measured['worker']=dict(count=len(worker_rows),db_acquire_ms=describe([r['db_acquire_ms'] for r in worker_rows]),
                           pending_samples=sum(e['pending']>0 for e in worker_pool))
    (path/'analysis.json').write_text(json.dumps({**meta,'lookup':measured},indent=2))
    return {**meta,'lookup':measured}


def aggregate(root):
    groups=collections.defaultdict(list);excluded=[]
    for path in sorted(root.glob('results/*/result.json')):
        meta=json.loads(path.read_text())
        reason=None
        if meta.get('error'):reason='execution_error'
        elif meta.get('incompleteWindow'):reason='incomplete_window'
        elif not meta.get('verified'):reason='verification_failed'
        if reason:
            excluded.append(dict(label=meta['label'],reason=reason,error=meta.get('error')))
            continue
        try:row=analyze_trial(path.parent)
        except (ValueError,OSError,KeyError) as error:
            excluded.append(dict(label=meta['label'],reason='analysis_error',detail=str(error)))
            continue
        lookup=row['lookup']
        if lookup['unmatched_clients']:reason='unmatched_clients'
        elif lookup['invalid_payloads']:reason='invalid_payloads'
        elif lookup.get('dropped_iterations'):reason='dropped_iterations'
        if reason:
            excluded.append(dict(label=row['label'],reason=reason))
            continue
        # HTTP errors are measured load outcomes, not grounds for exclusion.
        if row['measured']:
            name=f"{row['variant']}-p{row['pool']}-{row['scenario']}-{'on' if row['timingEnabled'] else 'off'}"
            if row.get('stage','legacy')!='legacy':name+=f"-{row['stage']}-r{row['configuredRate']}"
            groups[name].append(row)
    summary={}
    for name,rows in groups.items():
        summary[name]={'batches':len(rows),'labels':[r['label'] for r in rows],
                       'lookup_count':sum(r['lookup']['count'] for r in rows),
                       'errors':sum(r['lookup']['errors'] for r in rows),
                       'dropped':sum(r['lookup'].get('dropped_iterations',0) for r in rows),
                       'metrics':{field:describe([r['lookup'][field]['mean'] for r in rows if r['lookup'][field]['mean'] is not None]) for field in ['client_ms','http_duration_ms','server_ms','db_acquire_ms']},
                       'p95':{field:describe([r['lookup'][field]['p95'] for r in rows if r['lookup'][field]['p95'] is not None]) for field in ['client_ms','server_ms','db_acquire_ms']},
                       'upload':{field:describe([r['upload'][field] for r in rows if field in r.get('upload',{})]) for field in ['client_total_ms','server_total_ms','parse_ms','connection_held_ms']}}
    result=dict(groups=summary,excluded_trials=excluded)
    (root/'summary.json').write_text(json.dumps(result,indent=2))
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);args=parser.parse_args()
    print(json.dumps(aggregate(args.root),indent=2))
