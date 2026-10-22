"""Isolated artificial picker data; never reads .env or accepts a DB URL."""
import json
import subprocess
import sys
import time

CONTAINER = 'kplasma-selection-benchmark-db'
DATABASE = 'run_selection_bench'


def sql(statement):
    label = subprocess.check_output(['docker', 'inspect', '--format', '{{index .Config.Labels "kplasma.benchmark"}}', CONTAINER], text=True).strip()
    if label != 'run-selection-synthetic-only':
        raise RuntimeError('Refusing unmarked database')
    return subprocess.check_output(['docker', 'exec', '-i', CONTAINER, 'psql', '-X', '-v', 'ON_ERROR_STOP=1', '-U', 'benchmark', '-d', DATABASE, '-At'], input=statement, text=True).strip()


def seed(size):
    if size not in (150, 10000, 100000, 1000000):
        raise ValueError('Unsupported benchmark size')
    start = time.perf_counter()
    sql(f"""
BEGIN;
TRUNCATE import_batch, source_set, run, agent_request, conversation_turn, workspace_idempotency, decision RESTART IDENTITY CASCADE;
UPDATE workspace SET active_run=null,candidate_reference=null,revision=0,workspace_epoch=workspace_epoch+1,conversation_epoch=conversation_epoch+1;
CREATE TEMP TABLE seed_rows ON COMMIT DROP AS
SELECT i, 'RUN-P'||lpad((i/20000+1)::text,2,'0')||'-S'||lpad(((i/200%100+1)*5)::text,3,'0')||'-B'||lpad((i%200*50)::text,4,'0') AS run_id,
md5('picker-version-'||i)::uuid AS version_id, md5('picker-source-'||i)::uuid AS source_id FROM generate_series(0,{size-1}) i;
INSERT INTO source_set(id,sha256,total_bytes) SELECT source_id,md5('a-'||i)||md5('b-'||i),1 FROM seed_rows;
INSERT INTO run(run_id) SELECT run_id FROM seed_rows ORDER BY md5(i::text);
INSERT INTO run_version(id,run_id,source_id,registered_at,summary,full_run)
SELECT version_id,run_id,source_id,'2000-01-01',summary,summary FROM
(SELECT *, jsonb_build_object('runId',run_id,'runVersionId',version_id::text,'pressure',i/20000+1,'sourcePower',(i/200%100+1)*5,'biasPower',i%200*50,
'units',jsonb_build_object('pressure','mTorr','sourcePower','W','biasPower','W','ionFlux','10¹⁸ m⁻²s⁻¹','meanIonEnergy','eV','iedWidth','eV'),
'metrics',jsonb_build_object('ionFlux',i%900,'meanIonEnergy',i%600,'iedWidth',i%300),
'catalogStatus',case when i%101=100 then 'UNAVAILABLE' else 'READY' end,'qualityStatus','VERIFIED','convergenceStatus','CONVERGED',
'registeredAt','2000-01-01T00:00:00Z','note','Artificial picker benchmark','analysis','{{}}'::jsonb) AS summary FROM seed_rows) t ORDER BY i;
UPDATE run r SET current_version_id=v.id FROM run_version v WHERE v.run_id=r.run_id;
COMMIT;
VACUUM (ANALYZE) run; VACUUM (ANALYZE) run_version;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
""")
    return {'size': size, 'seedSeconds': time.perf_counter()-start, 'format': 'picker-synthetic-v1', 'historicalVersions': 0}


if __name__ == '__main__':
    print(json.dumps(seed(int(sys.argv[1]))))
