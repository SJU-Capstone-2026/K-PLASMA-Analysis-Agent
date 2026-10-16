#!/usr/bin/env python3
"""Recompute derived intervals from immutable raw timing events, then summarize independent batches."""
import argparse
import collections
import json
import statistics
from pathlib import Path
from upload_benchmark import summarize_events

def raw_batches(path):
    contexts=collections.defaultdict(list)
    batches=collections.defaultdict(list)
    if not path.exists(): return batches
    with path.open() as stream:
        for line in stream:
            if not line.strip(): continue
            event=json.loads(line)
            key=(event["kind"],event["id"])
            contexts[key].append(event)
            if event["phase"]==event["kind"]:
                pending=contexts.pop(key)
                if event["batchId"]: batches[event["batchId"]].extend(pending)
    return batches

def aggregate(values):
    return {"n":len(values),"mean":statistics.mean(values),"median":statistics.median(values),
            "min":min(values),"max":max(values),"stdev":statistics.stdev(values) if len(values)>1 else 0}

def analyze(root, variants):
    rows=[]
    for variant in variants:
        batches=raw_batches(root/variant/"timing.jsonl")
        for path in sorted((root/(variant+"-results")).glob(variant+"-*.json")):
            if path.name.startswith("summary"): continue
            value=json.loads(path.read_text())
            if "result" not in value: continue
            result=value["result"]
            if result["batchId"] in batches:
                result.update(summarize_events(batches[result["batchId"]]))
                result["timing_join_version"]=2
            elif variant!="A0": raise AssertionError("Missing raw timing for "+str(path))
            # JDBC API executeBatch counts once. PostgreSQL counts actual statement executions.
            result["jdbc_execute_calls"]=result.get("sql_calls")
            queries=[q for q in value["sql"] if "pg_stat_statements" not in q["query"].lower()]
            result["postgres_statement_calls"]=sum(q["calls"] for q in queries)
            result["postgres_execution_ms"]=sum(q["executionMs"] for q in queries)
            writes=[q for q in queries if q["query"].lstrip().lower().startswith(("insert ","update ","delete "))]
            result["postgres_write_execution_ms"]=sum(q["executionMs"] for q in writes)
            result["postgres_write_statement_calls"]=sum(q["calls"] for q in writes)
            value["result"]=result;path.write_text(json.dumps(value,indent=2))
            if result["measured"]: rows.append(result)
    grouped=collections.defaultdict(list)
    for row in rows: grouped[(row["variant"],row["scenario"],row["artificial"])].append(row)
    summary={}
    metrics=["client_total_ms","accept_ms","server_total_ms","queue_ms","inter_job_gap_ms","file_ms",
             "parse_ms","db_ms","connection_held_ms","transaction_ms","jdbc_execute_calls",
             "postgres_statement_calls","postgres_execution_ms","postgres_write_execution_ms","postgres_write_statement_calls","other_ms"]
    for (variant,scenario,artificial),samples in grouped.items():
        assert len({s["dataset_hash"] for s in samples})==1,"Mixed input datasets"
        assert all(s["jobs"]==150 and s["status"]=="SUCCESS" for s in samples)
        summary[f"{variant}:{scenario}:{'synthetic' if artificial else 'private'}"]={
            "dataset_hash":samples[0]["dataset_hash"],"success":len(samples),
            **{metric:aggregate([s[metric] for s in samples]) for metric in metrics if all(s.get(metric) is not None for s in samples)},
            "phase_ms":{phase:aggregate([s["phase_ms"].get(phase,0) for s in samples])
                        for phase in sorted({p for s in samples for p in s.get("phase_ms",{})})}
        }
    (root/"summary.json").write_text(json.dumps(summary,indent=2))
    return summary

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("root",type=Path);parser.add_argument("--variants",nargs="+",default=["A","B","C","A0"])
    args=parser.parse_args()
    result=analyze(args.root,args.variants)
    print(json.dumps({key:{"n":value["success"],"clientMs":value["client_total_ms"]["mean"],
                          "serverMs":value.get("server_total_ms",{}).get("mean")} for key,value in result.items()},indent=2))
