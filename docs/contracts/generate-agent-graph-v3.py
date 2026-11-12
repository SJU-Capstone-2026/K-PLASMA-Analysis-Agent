"""Export public V3 contracts from owned Python models; no model/data access."""
import json
from pathlib import Path
from kplasma_agent.v3.core.contracts import PlanDraft, GraphV3AnswerSnapshotV1

root=Path(__file__).resolve().parents[2]
target=root/"docs/contracts"
hash_string={"type":"string","pattern":"^[0-9a-f]{64}$"}
nullable_string={"type":["string","null"]}
options={"type":"object","additionalProperties":False,
    "required":["rulesEnabled","ragEnabled","configDigest"],
    "properties":{"rulesEnabled":{"type":"boolean"},"ragEnabled":{"type":"boolean"},"configDigest":hash_string}}
ref={"$ref":"#/$defs/RunRef"}
strings={"type":"array","uniqueItems":True,"items":{"type":"string"}}
rules={"type":"object","additionalProperties":False,
    "required":["policy","action","threshold","perRun","excludedRunIds","remainingRunIds","completeAggregation"],
    "properties":{
        "policy":{"enum":["disabled","cost-regex-1","cost-regex-2"]},"action":{"type":"string"},
        "threshold":{"type":["number","null"]},"completeAggregation":{"type":"boolean"},
        "aggregationScope":{"const":"ALL_RECORDS_FOR_RUN_ID_INCLUDING_HISTORY"},
        "excludedRunIds":strings,"remainingRunIds":strings,
        "perRun":{"type":"array","items":{"type":"object","additionalProperties":False,
            "required":["runId","count","status","mixed","costRejectionRecordIds"],
            "properties":{"runId":{"type":"string"},"count":{"type":"integer","minimum":0},
                "status":{"type":"string"},"mixed":{"type":"boolean"},"costRejectionRecordIds":strings}}}},
    "allOf":[{"if":{"properties":{"policy":{"const":"disabled"}}},"then":{"properties":{
        "action":{"const":"DISABLED"},"threshold":{"type":"null"},"perRun":{"maxItems":0},
        "excludedRunIds":{"maxItems":0},"completeAggregation":{"const":False}}}}]}
citation={"type":"object","additionalProperties":False,
    "required":["citationId","documentId","recordId","subjectRunId","recordRunVersionId","attribution","quote",
        "score","decision","createdAt","sourceNoteSha256","sourceRecordSha256"],
    "properties":{"citationId":{"type":"string","maxLength":96},"documentId":{"type":"string","maxLength":300},
        "recordId":{"type":"string","maxLength":200},"subjectRunId":nullable_string,
        "recordRunVersionId":{"type":["string","null"],"format":"uuid"},
        "attribution":{"enum":["PER_RUN","REFERENCE_ONLY","SHARED_UNASSIGNED"]},
        "quote":{"type":"string","maxLength":2000},"score":{"type":["number","null"]},
        "decision":{"enum":["ADOPT","REJECT","HOLD",None]},"createdAt":{"type":["string","null"],"format":"date-time"},
        "sourceNoteSha256":hash_string,"sourceRecordSha256":hash_string},
    "allOf":[{"if":{"properties":{"attribution":{"const":"SHARED_UNASSIGNED"}}},"then":{"properties":{
        "subjectRunId":{"type":"null"},"recordRunVersionId":{"type":"null"},"decision":{"type":"null"}}}}]}
evidence={"type":"object","additionalProperties":False,
    "required":["schemaVersion","kind","status","synthetic","answer","scopeRunRefs","citations","rules","retrieval","snapshotFingerprint","limitations"],
    "properties":{"schemaVersion":{"const":1},"kind":{"const":"decision_rag"},
        "status":{"type":"string","pattern":"^[A-Z_]+$"},"synthetic":{"type":"boolean"},
        "answer":{"type":"string","minLength":1,"maxLength":65536},
        "scopeRunRefs":{"type":"array","uniqueItems":True,"items":ref},
        "citations":{"type":"array","maxItems":5,"items":citation},"rules":rules,
        "retrieval":{"type":"object","required":["totalInScope","returned"],"properties":{
            "totalInScope":{"type":"integer","minimum":0},"returned":{"type":"integer","minimum":0,"maximum":5},
            "model":{"type":"string"},"strategy":{"type":"string"},"similarityIsProbability":{"const":False}}},
        "snapshotFingerprint":hash_string,"limitations":{"type":"array","items":{"type":"string"}}}}
answer=GraphV3AnswerSnapshotV1.model_json_schema()
answer={"$schema":"https://json-schema.org/draft/2020-12/schema",**answer}
answer["$comment"]="Activated graph v3, answer schema 1. Distinct from graph-v1 answer schema 3 in agent-answer-v3.schemas.yaml. Runtime verifies frozen source records/quotes/hashes, exact Run ownership, request switches, and saved step equality beyond JSON shape."
answer["$defs"]["V3OptionsSnapshot"]=options
answer["$defs"]["DecisionEvidence"]=evidence
answer["properties"]["executionMode"]={"$ref":"#/$defs/V3OptionsSnapshot"}
answer["properties"]["decisionEvidence"]={"type":"array","maxItems":16,"items":{"$ref":"#/$defs/DecisionEvidence"}}
if "executionMode" not in answer["required"]:answer["required"].append("executionMode")
plan={"$schema":"https://json-schema.org/draft/2020-12/schema",**PlanDraft.model_json_schema()}
plan["$comment"]="Graph v3 plan schema 2. Runtime removes decision_records when both features are OFF, restricts action per request, and validates SourceQuote against the user request before accepting the plan."
for name,value in (("agent-graph-v3.answer.schema.json",answer),("agent-graph-v3.plan.schema.json",plan)):
    (target/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(name)
