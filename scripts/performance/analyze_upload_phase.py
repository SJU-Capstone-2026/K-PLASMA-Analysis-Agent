import argparse,sys,json,statistics,collections
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser(description='Validate eight-worker phase alignment and summarize every paired burst')
parser.add_argument('base',type=Path)
parser.add_argument('--experiment',default='synchronized')
args=parser.parse_args()
BASE=args.base
RUN=args.experiment
sys.path.insert(0,str(ROOT/'scripts/performance'))
from analyze_upload_dispatch import load_trial
from analyze_upload_query_benchmark import summarize_queries,describe
clock=[json.loads(l) for l in (BASE/(RUN+'-clock.jsonl')).read_text().splitlines() if l.strip()]
trials={}
for path in sorted((BASE/RUN/'results').glob('*')):
 if not (path/'summary.json').exists():continue
 meta=json.loads((path/'result.json').read_text());summary=json.loads((path/'summary.json').read_text())
 gate=json.loads((path/'phase-gate.json').read_text())
 events=[json.loads(l) for l in (path/'timing.jsonl').read_text().splitlines() if l.strip()]
 clients=[json.loads(l) for l in (path/'lookup.jsonl').read_text().splitlines() if l.startswith('{')]
 events=[e for e in events if e['kind']!='lookup' or e['id'].startswith(meta['label']+'-')]
 measured=summarize_queries(events,clients,None);rows=sorted([r for r in measured['rows'] if r['cohort']==2],key=lambda r:r['serverStartNs'])
 related=[e for e in events if e.get('batchId') in meta['batchIds']]
 jobs=[e for e in related if e['kind']=='job' and e['phase']=='job']
 parses=[e for e in related if e['phase'] in ('parse.scalar','parse.graph')]
 count=lambda spans,t:sum(e['startNs']<=t<e['endNs'] for e in spans)
 counts=[count(jobs,r['serverStartNs']) for r in rows];pc=[count(parses,r['serverStartNs']) for r in rows]
 cohort=load_trial(path)['cohorts'][2]
 first=min(r['startEpochMs'] for r in clients);last=max(r['startEpochMs']+r['elapsedMs'] for r in clients)
 offsets=[(r['wallNs']-r['monoNs'])/1e6 for r in clock if first-200<=r['wallNs']/1e6<=last+200]
 drift=max(offsets)-min(offsets) if offsets else None
 issues=[]
 if len(rows)!=100 or len({r['vu'] for r in rows})!=100:issues.append('incomplete cohort')
 if not meta['verified'] or any(r['status']!=200 or not r['valid'] for r in clients):issues.append('data/response validation')
 if counts and counts[0]!=8:issues.append('first server request not during eight active jobs')
 if cohort['call_spread_ms']>5:issues.append('client call spread >5ms')
 if drift is None or drift>5:issues.append('wall clock step within trial')
 if summary['lookup']['missing_scheduled_requests']:issues.append('missing scheduled requests')
 fields={f:describe([r[f] for r in rows]) for f in ['elapsedMs','durationMs','db_acquire_ms','sql_ms','server_ms','held_ms','acquire_count','sql_count']}
 data=dict(label=meta['label'],repeat=meta['index'],variant=meta['variant'],restarted=meta['restarted'],verified=meta['verified'],issues=issues,
  upload_seconds=meta['client_total_ms']/1000,upload_held_seconds=summary['upload']['total_held_s'],worker_held_seconds=summary['upload']['worker_held_s'],intake_held_seconds=summary['upload']['intake_held_s'],
  cohort=cohort,metrics=fields,
  processing_at_arrival=dict(first=counts[0] if counts else None,min=min(counts,default=0),mean=statistics.mean(counts) if counts else None,exact_eight=sum(c==8 for c in counts)),
  parsing_at_arrival=dict(first=pc[0] if pc else None,min=min(pc,default=0),mean=statistics.mean(pc) if pc else None,exact_eight=sum(c==8 for c in pc)),
  gate_actual=dict(active_jobs=count(jobs,gate['releaseMonotonicNs']),parsing=count(parses,gate['releaseMonotonicNs']),log_lag_ms=(gate['releaseMonotonicNs']-gate['lastEventNs'])/1e6),
  gate_since_upload_ms=gate['releaseEpochMs']-meta['clientWindowEpochMs'][0],clock_offset_range_ms=drift,
  all_count=len(clients),errors=sum(r['status']!=200 or not r['valid'] for r in clients),pool=summary['lookup']['pool'])
 trials[meta['label']]=data
pairs=[]
for i in (1,2,3):
 if not all(f'{v}-w8-{i}' in trials for v in 'BC'):continue
 b=trials[f'B-w8-{i}'];c=trials[f'C-w8-{i}'];issues=[f'{v}: {issue}' for v,row in [('B',b),('C',c)] for issue in row['issues']]
 if b['cohort']['query_mix']!=c['cohort']['query_mix']:issues.append('query mix differs')
 if abs(b['cohort']['call_spread_ms']-c['cohort']['call_spread_ms'])>3:issues.append('pair client spread differs >3ms')
 pairs.append(dict(repeat=i,issues=issues,B=b,C=c))
def aggregate(ps):
 if not ps:return None
 result=dict(repeats=[p['repeat'] for p in ps],pairs=len(ps),requests=len(ps)*200)
 for f in ['upload_seconds','upload_held_seconds','worker_held_seconds','intake_held_seconds','elapsedMs','durationMs','db_acquire_ms','sql_ms','server_ms']:
  values={v:statistics.mean(p[v][f] if f in p[v] else p[v]['metrics'][f]['mean'] for p in ps) for v in 'BC'}
  values['reduction_pct']=100*(values['B']-values['C'])/values['B'] if values['B'] else None
  result[f]=values
 return result
out=dict(protocol='phase-gated cohort2; frozen B/C jars; k6; original server reuse policy',trials=trials,pairs=pairs,all_completed=aggregate(pairs),phase_valid=aggregate([p for p in pairs if not p['issues']]))
(BASE/(RUN+'-analysis.json')).write_text(json.dumps(out,ensure_ascii=False,indent=2))
assert json.loads((BASE/(RUN+'-analysis.json')).read_text())==out
for p in pairs:
 print('PAIR',p['repeat'],'issues',p['issues'])
 for v in 'BC':
  t=p[v];print(v,'http',t['metrics']['elapsedMs']['mean'],'acquire',t['metrics']['db_acquire_ms']['mean'],'hold_s',round(t['upload_held_seconds'],3),'upload_s',round(t['upload_seconds'],3),'processing',t['processing_at_arrival'],'parsing',t['parsing_at_arrival'],'spread',t['cohort']['call_spread_ms'],'gate',t['gate_actual'],'drift',t['clock_offset_range_ms'])
print('SUMMARY',json.dumps({k:out[k] for k in ['all_completed','phase_valid']},ensure_ascii=False))
