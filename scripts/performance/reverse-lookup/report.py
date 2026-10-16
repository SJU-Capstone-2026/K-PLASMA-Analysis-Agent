"""Aggregate only observed samples; never turn failed requests into latency improvements."""
import argparse
import json
from pathlib import Path
import statistics

SIZES=(150,10000,100000,1000000)


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def average(values):
    return statistics.mean(values) if values else None


def agent_summary(rows):
    completed=[row for row in rows if row.get('ok')]
    result={'samples':len(rows),'successes':len(completed),'failures':len(rows)-len(completed)}
    for field in ['totalMs','manifestBytes','checkpointBytes','manifestRuns','catalogRefs']:
        values=[row[field] for row in completed if field in row]
        result[field+'Mean']=average(values)
        result[field+'Max']=max(values) if values else None
    components=[]
    for row in completed:
        spans=row.get('spans',[])
        context=sum(s['elapsedMs'] for s in spans if s['name']=='backend.context')
        checkpoint=sum(s['elapsedMs'] for s in spans if s['name']=='backend.checkpoint')
        components.append({'contextMs':context,'checkpointMs':checkpoint,'otherMs':row['totalMs']-context-checkpoint})
    for field in ['contextMs','checkpointMs','otherMs']:
        result[field+'Mean']=average([row[field] for row in components])
    return result


def reduction(before,after):
    if before is None or after is None or before<=0:return None
    return (before-after)/before*100


def build(root,b='b2',c='c'):
    result={'scope':'synthetic, fixed tool selection, empty conversation, single request; not actual LLM latency','sizes':{}}
    for size in SIZES:
        row={}
        for method,folder in [('a','a'),('b',b),('c',c)]:
            directory=root/folder/str(size)
            query=directory/f'{method}-match-summary.json'
            row[method]={'query':json.loads(query.read_text()) if query.exists() else None,'agent':agent_summary(read_rows(directory/'m3.jsonl'))}
            if method=='a' and size==1000000:
                isolated=root/'a/1000000-isolated-agent/m3.jsonl'
                if isolated.exists():row[method]['agent']=agent_summary(read_rows(isolated))
        row['queryReductions']={label:reduction(row[left]['query'].get('totalMsMean') if row[left]['query'] else None,row[right]['query'].get('totalMsMean') if row[right]['query'] else None) for label,left,right in [('A-B','a','b'),('B-C','b','c'),('A-C','a','c')]}
        row['agentReductionA-C']=reduction(row['a']['agent']['totalMsMean'],row['c']['agent']['totalMsMean'])
        result['sizes'][str(size)]=row
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--b',default='b2');parser.add_argument('--c',default='c');args=parser.parse_args()
    result=build(args.root,args.b,args.c)
    (args.root/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    for size,row in result['sizes'].items():
        print(size,'query',[row[m]['query'].get('totalMsMean') if row[m]['query'] else None for m in 'abc'],'agent',[row[m]['agent']['totalMsMean'] for m in 'abc'],'A-C%',row['agentReductionA-C'])
