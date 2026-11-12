"""V3-owned corpus builder for server-attested, immutable record inventories.

Backend-attested records are frozen in the request manifest before retrieval.
Actual DB versions stay separate from numerical answer inventories when cited.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from uuid import UUID

from .corpus import Corpus
from . import policy


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _refs(values):
    result = []
    def visit(value):
        if isinstance(value, dict):
            if value.get("runId") and value.get("runVersionId"):
                ref = {"runId": value["runId"], "runVersionId": value["runVersionId"]}
                if ref not in result:
                    result.append(ref)
            else:
                for item in value.values():
                    visit(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)
    visit(values)
    return result


def _record_refs(record):
    if record.get("version") == 2:
        return _refs(record.get("candidates", []))
    return _refs([record.get("targetRunRef"), record.get("comparedRunRefs", [])])


class BackendCorpus(Corpus):
    """UUID scope for server-attested data; the offline file loader stays strict."""

    def scoped_documents(self, run_ids, version_scope="history", run_refs=None):
        if version_scope not in {"history", "exact"}:
            raise ValueError("INVALID_RAG_VERSION_SCOPE")
        ordered = list(dict.fromkeys(run_ids))
        if any(run not in self.run_versions for run in ordered):
            raise ValueError("UNKNOWN_RAG_RUN")
        supplied = _refs(run_refs or [])
        if any(r["runId"] not in ordered or r["runVersionId"] not in self.run_versions[r["runId"]]
               for r in supplied):
            raise ValueError("UNKNOWN_RAG_RUN_VERSION")
        wanted = {(r["runId"], r["runVersionId"]) for r in supplied}
        if version_scope == "exact" and {r[0] for r in wanted} != set(ordered):
            raise ValueError("RAG_EXACT_REFS_REQUIRED")
        result = []
        for document in self.documents:
            refs = _record_refs(self.records_by_id[document["recordId"]])
            matched = {r["runId"] for r in refs if
                       ((r["runId"], r["runVersionId"]) in wanted if version_scope == "exact"
                        else r["runId"] in ordered)}
            if not matched:
                continue
            subject = (document.get("runId"), document.get("offlineRunVersionId"))
            direct = subject in wanted if version_scope == "exact" else subject[0] in ordered
            role = ("SHARED_UNASSIGNED" if document["attribution"] == "SHARED_UNASSIGNED"
                    else "SUBJECT" if direct else "REFERENCE_ONLY")
            result.append({**deepcopy(document), "scopeRole": role,
                           "matchedRunIds": [r for r in ordered if r in matched]})
        return result


def live_corpus(records, registered_refs, *, synthetic):
    """Build from authenticated server data, never from a user-provided corpus path."""
    records = deepcopy(list(records))
    ids = [r.get("reviewId") or r.get("id") for r in records]
    if any(not isinstance(i, str) or not i for i in ids) or len(ids) != len(set(ids)):
        raise ValueError("INVALID_DECISION_RECORD_INVENTORY")
    versions: dict[str, set[str]] = {}
    all_refs = _refs(registered_refs) + [ref for r in records for ref in _record_refs(r)]
    for ref in all_refs:
        UUID(ref["runVersionId"])
        versions.setdefault(ref["runId"], set()).add(ref["runVersionId"])
    docs = []
    for record in records:
        record_id = record.get("reviewId") or record["id"]
        refs = _record_refs(record)
        subjects = [c["runId"] for c in record.get("candidates", [])] if record.get("version") == 2 else [record["targetRunId"]]
        for run_id in subjects:
            entry = policy.evidence([record], run_id)[0]
            text = entry["note"]
            if not text.strip():
                continue
            docs.append({"documentId": record_id + ":" + run_id, "recordId": record_id,
                         "runId": run_id, "offlineRunVersionId": entry["runVersionId"],
                         "referencedRunIds": [r["runId"] for r in refs], "attribution": "PER_RUN",
                         "decision": entry["decision"], "createdAt": entry["createdAt"],
                         "conditions": entry["conditions"], "text": text, "synthetic": synthetic,
                         "sourceNoteSha256": hashlib.sha256(text.encode()).hexdigest(),
                         "sourceRecordSha256": digest(record)})
        candidates = record.get("candidates", [])
        shared = record.get("overallComment", "")
        if record.get("version") == 2 and len(candidates) > 1 and isinstance(shared, str) and shared.strip():
            docs.append({"documentId": record_id + ":SHARED", "recordId": record_id,
                         "runId": None, "offlineRunVersionId": None, "referencedRunIds": [r["runId"] for r in refs],
                         "candidateRunRefs": refs, "attribution": "SHARED_UNASSIGNED",
                         "classifiableAsPerRunCostEvidence": False, "noteField": "overallComment",
                         "text": shared, "synthetic": synthetic,
                         "sourceNoteSha256": hashlib.sha256(shared.encode()).hexdigest(),
                         "sourceRecordSha256": digest(record)})
    rows = tuple({"runId": run, "runVersionId": sorted(aliases)[0]} for run, aliases in sorted(versions.items()))
    fingerprint = digest({"records": records, "registeredRefs": sorted(all_refs, key=canonical)})
    return BackendCorpus(tuple(docs), tuple(records), rows, fingerprint,
                  {"source": "FENCED_BACKEND_MANIFEST", "synthetic": synthetic, "appImportReady": True},
                  {d["documentId"]: d for d in docs}, dict(zip(ids, records, strict=True)), versions)


