"""K=2 selection/resume and cleanup on the prepared session, after read timings."""
import json
from pathlib import Path
import sys
from run import request
from seed import sql

directory=Path(sys.argv[1]);variant=sys.argv[2]
fixture=json.loads((directory/'request.json').read_text());job=fixture['request']
base='/api/agent/requests/'+job['requestId']
page=request(fixture['path'])[0]
chosen=[o for o in page['options'] if o['selectable']][:2]
assert len(chosen)==2
keys=[o['key'] for o in chosen]
before_rows=None if variant=='A' else int(sql('select count(*) from agent_run_selection_option;'))
if variant!='A':assert before_rows==0
selection_ms=None
if variant=='A':
    reply={'type':'run_selection','runKeys':keys,'baselineKey':None}
else:
    selected,selection_ms,_=request(base+'/run-selection',{'pendingInputId':'pick','expectedRequestRevision':job['requestRevision'],'expectedSelectionRevision':page['selectionRevision'],'operation':'add','keys':keys})
    assert selected['selectedCount']==2
    assert sql('select count(*) from agent_run_selection_option;')=='2'
    reply={'type':'run_selection','snapshotId':selected['snapshotId'],'selectionRevision':selected['selectionRevision']}
resumed,resume_ms,_=request(base+'/resume',{'expectedRequestRevision':job['requestRevision'],'pendingInputId':'pick','input':reply})
entries=resumed['inputEvents'][-1]['input']['comparisonReference']['entries']
assert [e['ref'] for e in entries]==[o['ref'] for o in chosen]
assert resumed['status']=='QUEUED'
_,cancel_ms,_=request(base+'/cancel',{})
if variant!='A':assert sql('select count(*) from agent_run_selection_option;')=='0'
(directory/'actions.json').write_text(json.dumps({'selectedK':2,'beforeSelectionRows':before_rows,'afterSelectionRows':None if variant=='A' else 2,'selectionMs':selection_ms,'resumeMs':resume_ms,'cancelMs':cancel_ms,'exactVersions':True,'snapshotCleaned':variant!='A'}))
