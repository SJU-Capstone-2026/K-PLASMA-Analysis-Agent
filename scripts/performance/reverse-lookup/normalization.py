import sys,json,math,subprocess,random
from pathlib import Path
root=Path(__file__).resolve().parents[3];sys.path.insert(0,str(root/'agent/python/src'))
from kplasma_agent.domain.common import scalar
units={'pressure':[None,'mTorr','mtorr','밀리토르','밀리토어','millitorr','Torr','토르','토어','Pa',' mTorr ','\u00a0mTorr\u00a0'], 'sourcePower':[None,'W','w','와트','왓트','왛트','오ㅏ트','watts','Watt','kW',' W ','\u00a0W\u00a0'], 'biasPower':[None,'W','와트','왓트','mW'], 'meanIonEnergy':[None,'eV','e볼트','이볼트','전자볼트','일렉트론볼트','electronvolt','electronvolts','e V','keV',' eV ','\u00a0eV\u00a0'], 'ionFlux':[None,'10¹⁸ m⁻²s⁻¹','10^18 m^-2s^-1','10^18 m^-2 s^-1','m⁻²s⁻¹','m^-2s^-1','m^-2 s^-1','m-2s-1','x'], 'iedWidth':[None,'eV','e볼트','electronvolts','keV']}
values=[0,-0.,1,-1,150,math.nextafter(150,math.inf),160,1e-308,1e-320,5e-324,1e308,None,True,'150']
random.seed(402);values += [random.uniform(-1000,1000)*10.**random.randint(-300,300) for _ in range(20)]
cases=[]
for metric,aliases in units.items():
 for unit in aliases:
  for value in values:
   run={'metrics':{},'units':{metric:unit}}
   if metric in ['pressure','sourcePower','biasPower']:run[metric]=value
   else:run['metrics'][metric]=value
   expected=scalar(run,metric)[0];cases.append((metric,run,expected))
def quote(s):return "'"+s.replace("'","''")+"'"
text='select json_agg(v order by i) from (values '+','.join(f"({i},run_search_scalar_v1({quote(json.dumps(r,ensure_ascii=False))}::jsonb,{quote(m)}))" for i,(m,r,e) in enumerate(cases))+') s(i,v);'
r=subprocess.run(['docker','exec','-i','kplasma-reverse-benchmark-db','psql','-U','benchmark','-d','reverse_lookup_bench','-X','-At','-v','ON_ERROR_STOP=1'],input=text,text=True,capture_output=True,check=True)
actual=json.loads(r.stdout)
wrong=[{'case':i,'metric':m,'source':run,'expected':expected,'actual':a} for i,((m,run,expected),a) in enumerate(zip(cases,actual)) if a!=expected]
out=root/'.local/performance/reverse-lookup/normalization.json';out.write_text(json.dumps({'count':len(cases),'mismatches':wrong},indent=2,ensure_ascii=False))
assert not wrong, 'Search projection differs from Python normalization'
print('normalization cases',len(cases),'mismatches',len(wrong));print(json.dumps(wrong[:4],ensure_ascii=False))
