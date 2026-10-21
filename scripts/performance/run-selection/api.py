"""Prepared-session API and DB evidence, separate from creation and browser timing."""
import json
import os
from pathlib import Path
import subprocess
import sys
from seed import sql
from run import request

directory=Path(sys.argv[1]);variant=sys.argv[2]
iterations=10 if directory.name=='1000000' else 100
(directory/'api-policy.json').write_text(json.dumps({'blocks':3,'iterationsPerBlock':iterations,'reason':'Million-row scalability check uses a bounded sample; smaller sizes retain 300 requests per scenario.'}))
fixture=json.loads((directory/'request.json').read_text())
sql('SELECT pg_stat_statements_reset();')
scenarios={'page':''}
if variant!='A':
    sql('ANALYZE agent_run_selection_option;')
    scenarios.update({'exact':'&query=RUN-P01-S005-B0050','missing':'&query=NO-SUCH-SYNTHETIC-RUN','short':'&query=P0'})
    first=request(fixture['path'])[0]
    if first['nextCursor']:
        scenarios['next']='&cursor='+first['nextCursor']
for name,query in scenarios.items():
    for block in range(3):
        env={**os.environ,'SELECTION_ITERATIONS':str(iterations),'SELECTION_REQUEST':str((directory/'request.json').resolve()),'SELECTION_SUMMARY':str((directory/f'k6-{name}-{block}.json').resolve()),'SELECTION_QUERY':query,'SELECTION_SCENARIO':name}
        with (directory/f'k6-{name}-{block}.log').open('w') as log:
            result=subprocess.run(['k6','run','--quiet','scripts/performance/run-selection/selection-load.js'],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=660)
        if result.returncode:raise RuntimeError(f'k6 failed: {name}/{block}')
if variant!='A':
    snapshot=first['snapshotId']
    # Identifier was supplied by the local product and must parse before interpolation.
    import uuid
    uuid.UUID(snapshot)
    sql('ANALYZE agent_run_selection_option;')
    queries={
        'page':f"select o.alias,o.run_id,o.run_version_id,o.conditions,v.id from agent_run_selection_option o left join run_version v on v.id=o.run_version_id where snapshot_id='{snapshot}' order by natural_sort_key,run_id,run_version_id limit 31",
        'exact':f"select o.alias,o.run_id,o.run_version_id,o.conditions,v.id from agent_run_selection_option o left join run_version v on v.id=o.run_version_id where snapshot_id='{snapshot}' and search_text like '%run-p01-s005-b0050%' order by natural_sort_key,run_id,run_version_id limit 31",
        'selected':f"select alias from agent_run_selection_option where snapshot_id='{snapshot}' and selected order by ordinal limit 31"
    }
    for name,query in queries.items():
        (directory/f'explain-{name}.json').write_text(sql('EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) '+query))
    (directory/'db-storage.json').write_text(sql("select json_build_object('optionsHeapBytes',pg_table_size('agent_run_selection_option'),'optionsIndexBytes',pg_indexes_size('agent_run_selection_option'),'snapshotBytes',pg_total_relation_size('agent_run_selection'),'mutationBytes',pg_total_relation_size('agent_run_selection_mutation'));"))
(directory/'sql-statistics.json').write_text(sql("select coalesce(json_agg(row_to_json(t)),'[]') from (select calls,total_exec_time,mean_exec_time,rows,shared_blks_hit,shared_blks_read,wal_bytes,query from pg_stat_statements where query not like '%pg_stat_statements%' order by total_exec_time desc limit 30)t;"))
