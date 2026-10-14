import subprocess,json,time
from pathlib import Path
from seed import check_isolation

check_isolation()
root=Path(__file__).resolve().parents[3]
out=root/'.local/performance/reverse-lookup/pgbench';out.mkdir(exist_ok=True)
if (out/'results.json').exists():raise ValueError('Refusing to overwrite pgbench measurements')
container='kplasma-reverse-benchmark-db'
def sql(text):
 return subprocess.run(['docker','exec','-i',container,'psql','-U','benchmark','-d','reverse_lookup_bench','-v','ON_ERROR_STOP=1','-X','-At'],input=text,text=True,capture_output=True,check=True).stdout
assert sql('select current_database()').strip()=='reverse_lookup_bench'
import os
cp=(root/'.local/performance/reverse-lookup/classpath.txt').read_text().strip()
java=Path(os.environ['JAVA_HOME'])/'bin/java'
r=subprocess.run([str(java),'-cp',cp,'com.kplasma.analysisagent.agent.ReverseLookupBenchmarkSupport','--dump-query-sql'],check=True,capture_output=True,text=True)
query_file=out/'query.sql';query_file.write_text(r.stdout)
subprocess.run(['docker','cp',str(query_file),container+':/tmp/reverse-query.sql'],check=True,capture_output=True)
indexsql=(root/'backend/src/main/resources/db/migration/V7__run_search_indexes.sql').read_text()
drop='drop index run_search_energy_idx,run_search_flux_idx,run_search_width_idx,run_search_conditions_idx; analyze run;'
results=[]
for method in ['c','b','b','c']:
 if method=='b' and sql("select count(*) from pg_indexes where indexname='run_search_energy_idx'").strip()=='1':sql(drop)
 if method=='c' and sql("select count(*) from pg_indexes where indexname='run_search_energy_idx'").strip()=='0':
  start=time.perf_counter();sql(indexsql);results.append({'indexBuildAndAnalyzeMs':(time.perf_counter()-start)*1000})
 # warm-up separate from measurement; one client, simple protocol, actual generated product SQL.
 subprocess.run(['docker','exec',container,'pgbench','-U','benchmark','-d','reverse_lookup_bench','-n','-c','1','-j','1','-t','5','-M','simple','-f','/tmp/reverse-query.sql'],check=True,capture_output=True,text=True)
 label=f'{method}-{len(results)}'
 r=subprocess.run(['docker','exec',container,'pgbench','-U','benchmark','-d','reverse_lookup_bench','-n','-c','1','-j','1','-t','100','-M','simple','-f','/tmp/reverse-query.sql','-l','--log-prefix=/tmp/'+label],check=True,capture_output=True,text=True)
 (out/(label+'.txt')).write_text(r.stdout+r.stderr)
 logs=subprocess.run(['docker','exec',container,'sh','-c','cat /tmp/'+label+'.*'],check=True,capture_output=True,text=True).stdout
 (out/(label+'.log')).write_text(logs)
 results.append({'method':method,'log':label,'output':r.stdout})
 # Measure 100 scalar projection updates, rollback outside product registration, no upload/parse claim.
 begin=time.perf_counter()
 sql("begin; set local jit=off; select run_search_refresh_v1(run_id) from (select run_id from run order by run_id limit 100) s; rollback;")
 results[-1]['projectionUpdate100Ms']=(time.perf_counter()-begin)*1000
print(sql("select indexrelname,pg_relation_size(indexrelid) from pg_stat_user_indexes where indexrelname like 'run_search_%' order by indexrelname"))
(out/'index-sizes.txt').write_text(sql("select indexrelname,pg_relation_size(indexrelid) from pg_stat_user_indexes where indexrelname like 'run_search_%' order by indexrelname"))
(out/'results.json').write_text(json.dumps(results,indent=2))
print('DONE',len(results))
