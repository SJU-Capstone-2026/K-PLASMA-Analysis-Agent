"""Validate shared synthetic texts without a DB, API key or model call."""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parent
CASE_KEYS = {"id", "category", "question", "attachedRunIds", "userActions"}
RECORD_KEYS = {"reviewId", "id", "version", "targetRunId", "targetRunRef", "comparedRunIds",
               "comparedRunRefs", "decision", "comment", "createdAt", "queryText", "question",
               "overallComment", "candidates", "runSnapshots"}
TEXT_KEYS = ("comment", "overallComment", "question", "queryText")
DOC_KEYS = ("documentId", "recordId", "runId", "offlineRunVersionId", "referencedRunIds", "attribution",
            "decision", "createdAt", "text", "synthetic", "sourceNoteSha256", "candidateRunRefs",
            "classifiableAsPerRunCostEvidence", "noteField")


def read(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def keep(value, keys):
    return {key: value[key] for key in keys if key in value}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_ref(ref):
    if ref is None:
        return
    require(isinstance(ref, dict) and set(ref) == {"runId", "runVersionId"}, "Unexpected Run-ref payload")
    require(isinstance(ref["runId"], str) and ref["runId"], "Missing Run ID")
    UUID(ref["runVersionId"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-corpus", action="store_true",
                        help="Also verify note documents using the implementation PR's corpus builder.")
    parser.add_argument("--implementation-root", type=Path,
                        help="Optional checkout containing implementation PR #36.")
    args = parser.parse_args()
    manifest = read("manifest.json")
    for name, expected in manifest["fileSha256"].items():
        require(Path(name).name == name, "Unexpected manifest path")
        require(digest((ROOT / name).read_bytes()) == expected, "File hash mismatch: " + name)
    cases = read("evaluation-questions.json")["cases"]
    history = read("synthetic-judgment-history.json")
    records = history["records"]
    require(history["synthetic"] is True, "Missing synthetic label")
    require(len(cases) == manifest["questionCount"] == 12, "Question count changed")
    require(len(records) == manifest["recordCount"] == 360, "Record count changed")
    for case in cases:
        require(set(case) == CASE_KEYS, "Unexpected question payload")
        require(isinstance(case["question"], str) and case["question"], "Missing question")
        for action in case["userActions"]:
            require(set(action) == {"kind", "selectedRunIds"} and action["kind"] == "run_selection",
                    "Unexpected selection payload")
    ids = [row.get("reviewId") or row.get("id") for row in records]
    require(len(set(ids)) == 360 and all(isinstance(key, str) and key.startswith("SYN-") for key in ids),
            "Missing or duplicate synthetic record IDs")
    for row in records:
        require(set(row) <= RECORD_KEYS, "Unexpected record payload")
        check_ref(row.get("targetRunRef"))
        for ref in row.get("comparedRunRefs", []):
            check_ref(ref)
        for ref in row.get("runSnapshots", []):
            check_ref(ref)
        for candidate in row.get("candidates", []):
            require(set(candidate) <= {"runId", "runVersionId", "decision", "note"},
                    "Unexpected candidate payload")
            check_ref(keep(candidate, ("runId", "runVersionId")))
        for key in TEXT_KEYS:
            require(key not in row or isinstance(row[key], str), "Non-text memo field")
    question_texts = [{"id": case["id"], "question": case["question"]} for case in cases]
    memo_texts = [{"recordId": row.get("reviewId") or row["id"], "fields": keep(row, TEXT_KEYS),
                   "candidateNotes": [keep(c, ("runId", "note")) for c in row.get("candidates", [])]}
                  for row in records]
    require(digest(canonical(question_texts)) == manifest["originalQuestionTextSha256"], "Question text changed")
    require(digest(canonical(memo_texts)) == manifest["originalMemoTextsSha256"], "Memo text changed")
    combined = canonical([cases, records]).decode()
    require(not re.search(r"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{24,}|C:[/\\]+Users[/\\]+)", combined),
            "Unexpected secret or private path")
    result = {"status": "PASS", "questionCount": 12, "syntheticRecordCount": 360,
              "originalTextHashesMatch": True, "modelApiCalls": 0}
    if args.check_corpus:
        implementation = args.implementation_root or ROOT.parents[2]
        sys.path.insert(0, str(implementation / "agent/python/src"))
        try:
            from kplasma_agent.v3.decision_rag.live_corpus import live_corpus
        except ImportError as error:
            raise SystemExit("--check-corpus requires a checkout containing implementation PR #36.") from error
        corpus = live_corpus(records, [], synthetic=True)
        documents = [keep(doc, DOC_KEYS) for doc in corpus.documents]
        require(len(documents) == manifest["noteDocumentCount"] == 556, "Note-document count changed")
        require(digest(canonical(documents)) == manifest["originalNoteDocumentsSha256"], "Note documents changed")
        result["noteDocumentsMatched"] = len(documents)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
