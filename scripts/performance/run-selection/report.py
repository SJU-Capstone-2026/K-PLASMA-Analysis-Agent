"""Aggregate measured samples without mixing heaps, warmups or failed requests."""
import argparse
import json
from pathlib import Path
from statistics import mean


def aggregate(rows):
    successful=[r for r in rows if r.get('ok') and r.get('index',0)>=0]
    failures=[r for r in rows if not r.get('ok')]
    result={'samples':len(successful),'failures':failures}
    for key in ('prepareMs','fetchMs','prepareAndFetchMs','requestOwnedRows','firstMs','searchMs','domNodes','responseBytes','returnedRows'):
        values=[r[key] for r in successful if r.get(key) is not None]
        if values:result[key]=mean(values)
    return result


def reduction(before,after):
    return None if before is None or after is None or before<=0 else (before-after)/before*100


def collect(root):
    result={}
    for variant in ('A','B','C'):
        result[variant]={}
        for size in (150,10000,100000,1000000):
            directory=root/variant/'heap8-db6'/str(size)
            if not directory.exists():continue
            env=json.loads((directory/'environment.json').read_text())
            if env['javaHeapMax']!='8g' or env['postgresMemoryLimit']!='6g':
                raise ValueError('Do not mix resource settings: '+str(directory))
            rows=[json.loads(line) for line in (directory/'sessions.jsonl').read_text().splitlines()] if (directory/'sessions.jsonl').exists() else []
            item={'lifecycle':aggregate(rows),'environment':env}
            browser_directory=root/variant/'browser-final'/str(size)
            if not (browser_directory/'browser.json').exists():browser_directory=directory
            else:
                browser_env=json.loads((browser_directory/'environment.json').read_text())
                if any(browser_env.get(key)!=env.get(key) for key in ('javaHeapMax','postgresMemoryLimit','jarSha256')):
                    raise ValueError('Browser rerun must use the same resources and JAR')
            if (browser_directory/'browser.json').exists():
                item['browser']=aggregate(json.loads((browser_directory/'browser.json').read_text()))
                item['browserEvidence']=str(browser_directory/'browser.json')
            item['api']={}
            for summary in sorted(directory.glob('k6-*.json')):
                data=json.loads(summary.read_text());metrics=data['metrics']
                item['api'][summary.stem]={'httpMs':metrics['http_req_duration']['values'],'requests':metrics['http_reqs']['values']['count'],'failedRate':metrics['http_req_failed']['values']['rate']}
            for filename in ('state-sizes.json','db-storage.json','actions.json'):
                if (directory/filename).exists():item[filename[:-5]]=json.loads((directory/filename).read_text())
            result[variant][str(size)]=item
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.write_text(json.dumps(collect(args.root),ensure_ascii=False,indent=2))
