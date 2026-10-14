import sys,json
from pathlib import Path
import httpx
root=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(root/'scripts/performance/reverse-lookup'))
from seed import make_run
U={'pressure':'mTorr','sourcePower':'W','biasPower':'W','meanIonEnergy':'eV','ionFlux':'10¹⁸ m⁻²s⁻¹','iedWidth':'eV'}
def eq(k,v):return {'metric':k,'operator':'eq','value':v,'unit':U[k]}
energy={'metric':'meanIonEnergy','operator':'between','min':150,'max':160,'unit':'eV'}
g=[{'metric':'ionFlux','direction':'maximize','unit':U['ionFlux']}]
scenarios={'Q2':[energy,eq('ionFlux',.37),eq('iedWidth',.13)],'Q3':[eq('pressure',1),eq('sourcePower',5),eq('biasPower',0),energy],'Q4-source':[eq('sourcePower',5),energy],'Q4-bias':[eq('biasPower',0),energy],'Q5':[{'metric':'meanIonEnergy','operator':'gte','value':1e12,'unit':'eV'}],'Q6':[{'metric':'meanIonEnergy','operator':'between','min':150,'max':152,'unit':'eV'},eq('iedWidth',699.99)]}
expected={k:[] for k in scenarios}
for i in range(1000000):
 # Independent mathematical oracle (not selected SQL/Python source).
 values={'pressure':i//20000+1,'sourcePower':(i//200%100+1)*5,'biasPower':i%200*50,'meanIonEnergy':150+i if i<5 else 2000+i,'ionFlux':i*37%90000/100,'iedWidth':i*13%70000/100}
 def matches(r):
  x=values[r['metric']]
  if r['operator']=='eq':return x==r['value']
  if r['operator']=='gte':return x>=r['value']
  return r['min']<=x<=r['max']
 for name,rules in scenarios.items():
  common=all(matches(r) for r in rules)
  independent=any(matches(r) for r in rules if r['metric'] in ['meanIonEnergy','ionFlux','iedWidth'])
  if common or independent:expected[name].append((i,values['ionFlux']))
out=root/'.local/performance/reverse-lookup/scenarios';out.mkdir(exist_ok=True)
results=[]
with httpx.Client(base_url='http://127.0.0.1:18088',timeout=60) as c:
 for name,rules in scenarios.items():
  query={'constraints':rules,'goals':g}
  r=c.post('/benchmark/query',json=query);r.raise_for_status();runs=r.json()['runs']
  indices=sorted(expected[name],key=lambda x:(-x[1],make_run(x[0])['runId']))
  oracle=[make_run(i) for i,_ in indices]
  assert [(r['runId'],r['runVersionId'],r['metrics']) for r in runs]==[(r['runId'],r['runVersionId'],r['metrics']) for r in oracle],name
  plan=c.post('/benchmark/explain',json=query);plan.raise_for_status()
  (out/f'{name}-plan.json').write_text(json.dumps(plan.json()))
  results.append({'scenario':name,'passed':True,'returned':len(runs),'sqlCount':r.headers['x-bench-queries']})
  print(results[-1],flush=True)
 (out/'matrix.json').write_text(json.dumps(results,indent=2))
