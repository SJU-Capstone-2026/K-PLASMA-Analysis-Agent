"""Validate a fixed local corpus without opening questions, annotations or oracle files."""

from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re

from .policy import RECORD_POLICY_VERSION, evidence


FILES = ("retrieval-documents.jsonl", "decision-records.jsonl", "run-snapshots.jsonl")
SCHEMA = "kplasma.synthetic-rag-bundle.v1"
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
CONDITIONS = {"pressure", "sourcePower", "biasPower"}
METRICS = {"ionFlux", "meanIonEnergy", "iedWidth"}
SUPPORTING = {"electronDensity", "electronTemperature"}
SPLITS = {"development", "validation", "holdout"}
BASE_FIELDS = {
    "documentId", "synthetic", "recordId", "runId", "offlineRunVersionId", "referencedRunIds",
    "attribution", "split", "text", "sourceNoteSha256", "sourceRecordSha256",
}
PER_RUN_FIELDS = BASE_FIELDS | {"decision", "createdAt", "conditions"}
SHARED_FIELDS = BASE_FIELDS | {"candidateRunRefs", "classifiableAsPerRunCostEvidence", "noteField"}


class CorpusError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _require(condition, code):
    if not condition:
        raise CorpusError(code)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value):
    return hashlib.sha256(value).hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "CORPUS_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise CorpusError("CORPUS_NONFINITE_NUMBER")


def _json(raw):
    try:
        return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique, parse_constant=_invalid_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise CorpusError("CORPUS_INVALID_JSON") from None


def _rows(raw):
    rows = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        row = _json(line)
        _require(isinstance(row, dict), "CORPUS_ROW_NOT_OBJECT")
        rows.append(row)
    return rows


def _read(root, name):
    # Only callers with fixed filenames reach here. Do not follow a corpus file into an oracle or another directory.
    path = root / name
    try:
        _require(not path.is_symlink() and path.resolve().parent == root,
                 "CORPUS_FILE_OUTSIDE_BUNDLE")
        _require(path.is_file() and path.stat().st_size <= 64 * 1024 * 1024, "CORPUS_FILE_UNAVAILABLE")
        value = path.read_bytes()
        _require(len(value) <= 64 * 1024 * 1024, "CORPUS_FILE_TOO_LARGE")
        return value
    except OSError:
        raise CorpusError("CORPUS_FILE_UNAVAILABLE") from None


def _version(value):
    _require(_text(value) and value.startswith("offline-") and len(value) > 8,
             "CORPUS_OFFLINE_VERSION_REQUIRED")
    return value


def _ref(value, versions):
    if isinstance(value, dict):
        run_id = value.get("runId")
        normal, offline = value.get("runVersionId"), value.get("offlineRunVersionId")
        _require(normal is None or offline is None or normal == offline, "CORPUS_VERSION_ALIAS_MISMATCH")
        version = offline if offline is not None else normal
    elif isinstance(value, (list, tuple)) and len(value) == 2:
        run_id, version = value
    else:
        raise CorpusError("CORPUS_RUN_REF_INVALID")
    _require(_text(run_id), "CORPUS_RUN_REF_INVALID")
    _require(run_id in versions, "CORPUS_UNKNOWN_RUN")
    version = _version(version)
    _require(version in versions[run_id], "CORPUS_UNKNOWN_RUN_VERSION")
    return run_id, version


def _block(value, keys, nullable=()):
    _require(isinstance(value, dict) and set(value) == keys, "CORPUS_SCALAR_FIELDS_INVALID")
    for key in keys:
        number = value[key]
        if number is None and key in nullable:
            continue
        try:
            valid = not isinstance(number, bool) and isinstance(number, (int, float)) and math.isfinite(number)
        except OverflowError:
            valid = False
        _require(valid, "CORPUS_NONFINITE_NUMBER")


def _record_refs(record, versions):
    target = _ref(record.get("targetRunRef"), versions)
    _require(record.get("targetRunId") == target[0], "CORPUS_RECORD_TARGET_MISMATCH")
    raw = record.get("comparedRunRefs")
    _require(isinstance(raw, list) and len(raw) <= 2, "CORPUS_RECORD_REFS_INVALID")
    refs = [target, *(_ref(item, versions) for item in raw)]
    _require(len({ref[0] for ref in refs}) == len(refs), "CORPUS_DUPLICATE_RECORD_RUN")
    _require(record.get("comparedRunIds") == [ref[0] for ref in refs[1:]], "CORPUS_RECORD_REFS_INVALID")
    return refs


def _check_scalars(snapshot, source):
    _block(snapshot.get("conditions"), CONDITIONS)
    _block(snapshot.get("metrics"), METRICS, {"iedWidth"})
    _require(snapshot["conditions"] == source["conditions"] and snapshot["metrics"] == source["metrics"],
             "CORPUS_RECORD_SCALAR_MISMATCH")


def _check_record(record, versions, sources):
    _require(record.get("decision") in {"ADOPT", "HOLD", "REJECT"}, "CORPUS_RECORD_DECISION_INVALID")
    _require(_text(record.get("comment")), "CORPUS_RECORD_COMMENT_INVALID")
    created = record.get("createdAt")
    try:
        _require(_text(created) and "T" in created, "CORPUS_RECORD_TIME_INVALID")
        _require(datetime.fromisoformat(created.replace("Z", "+00:00")).tzinfo is not None,
                 "CORPUS_RECORD_TIME_INVALID")
    except ValueError:
        raise CorpusError("CORPUS_RECORD_TIME_INVALID") from None
    refs = _record_refs(record, versions)
    if record.get("version") is None:
        _require(all(record.get(name) is None for name in ("id", "candidates", "overallComment", "question", "objectives")),
                 "CORPUS_REV_HAS_EXP_FIELDS")
        _require(record.get("analysisType") in {"FORWARD", "REVERSE", "EXPLANATION"}, "CORPUS_REV_ANALYSIS_INVALID")
        _require(record.get("analysisType") != "EXPLANATION" or len(refs) == 2, "CORPUS_REV_BASELINE_REQUIRED")
        snapshots = record.get("runSnapshots")
        _require(isinstance(snapshots, list) and len(snapshots) == len(refs), "CORPUS_RECORD_SNAPSHOTS_INVALID")
        for snapshot, ref in zip(snapshots, refs):
            _require(_ref(snapshot, versions) == ref, "CORPUS_RECORD_SNAPSHOT_ORDER")
            _check_scalars(snapshot, sources[ref[0]])
            _block(snapshot.get("supportingMetrics"), SUPPORTING)
            _require(snapshot["supportingMetrics"] == sources[ref[0]]["supportingMetrics"],
                     "CORPUS_RECORD_SCALAR_MISMATCH")
    else:
        _require(type(record.get("version")) is int and record["version"] == 2, "CORPUS_RECORD_VERSION_INVALID")
        _require(record.get("id") == record["reviewId"] and record["decision"] == "ADOPT",
                 "CORPUS_EXP_IDENTITY_INVALID")
        _require(record.get("analysisType") == "REVERSE" and record.get("processMode") == "GOAL_RECOMMENDATION",
                 "CORPUS_EXP_ANALYSIS_INVALID")
        _require(all(record.get(name) is None for name in ("constraints", "runSnapshots", "evidenceKinds", "limitations")),
                 "CORPUS_EXP_HAS_REV_FIELDS")
        _require(_text(record.get("overallComment")) and record["overallComment"] == record["comment"],
                 "CORPUS_EXP_COMMENT_INVALID")
        candidates = record.get("candidates")
        _require(isinstance(candidates, list) and 1 <= len(candidates) <= 3 and len(candidates) == len(refs),
                 "CORPUS_EXP_CANDIDATES_INVALID")
        for index, (candidate, ref) in enumerate(zip(candidates, refs)):
            _require(_ref(candidate, versions) == ref, "CORPUS_RECORD_SNAPSHOT_ORDER")
            _require(candidate.get("decision") == "ADOPT" if index == 0
                     else candidate.get("decision") in {"HOLD", "REJECT"}, "CORPUS_EXP_DECISION_INVALID")
            _require(isinstance(candidate.get("note"), str), "CORPUS_EXP_NOTE_INVALID")
            _check_scalars(candidate, sources[ref[0]])
    return refs


@dataclass(frozen=True)
class Corpus:
    documents: tuple[dict, ...]
    records: tuple[dict, ...]
    runs: tuple[dict, ...]
    fingerprint: str
    manifest: dict
    documents_by_id: dict
    records_by_id: dict
    run_versions: dict[str, set[str]]

    @classmethod
    def load(cls, bundle: Path):
        try:
            return cls._load(bundle)
        except CorpusError:
            raise
        except (TypeError, ValueError, KeyError, AttributeError, OverflowError, RecursionError):
            # Malformed source values are never included in public diagnostics.
            raise CorpusError("CORPUS_SCHEMA_INVALID") from None

    @classmethod
    def _load(cls, bundle: Path):
        root = Path(bundle).resolve()
        manifest = _json(_read(root, "manifest.json"))
        _require(isinstance(manifest, dict) and manifest.get("schemaVersion") == SCHEMA,
                 "CORPUS_MANIFEST_SCHEMA_INVALID")
        _require(manifest.get("synthetic") is True and manifest.get("appImportReady") is False,
                 "CORPUS_NOT_OFFLINE_SYNTHETIC")
        _require(manifest.get("retrieverInput") == FILES[0], "CORPUS_RETRIEVER_INPUT_INVALID")
        rule = manifest.get("referenceRule")
        _require(isinstance(rule, dict) and rule.get("policy") == RECORD_POLICY_VERSION
                 and isinstance(rule.get("sha256"), str) and SHA256.fullmatch(rule["sha256"]),
                 "CORPUS_POLICY_METADATA_INVALID")
        expected = manifest.get("dataFileSha256")
        _require(isinstance(expected, dict), "CORPUS_HASHES_REQUIRED")
        payloads, hashes = {}, {}
        for name in FILES:
            payloads[name] = _read(root, name)
            hashes[name] = _hash(payloads[name])
            _require(hashes[name] == expected.get(name), "CORPUS_FILE_HASH_MISMATCH")
        runs = _rows(payloads[FILES[2]])
        versions, source_runs = {}, {}
        for run in runs:
            run_id = run.get("runId")
            _require(_text(run_id) and run_id not in versions, "CORPUS_SOURCE_RUN_ID_INVALID")
            primary = _version(run.get("offlineRunVersionId"))
            aliases = run.get("offlineVersionAliases", [])
            _require(isinstance(aliases, list), "CORPUS_SOURCE_ALIASES_INVALID")
            values = [_version(alias) for alias in aliases]
            _require(len(set(values)) == len(values), "CORPUS_SOURCE_ALIAS_DUPLICATE")
            _require(run.get("appImportReady", False) is False, "CORPUS_NOT_OFFLINE_SYNTHETIC")
            _block(run.get("conditions"), CONDITIONS)
            _block(run.get("metrics"), METRICS, {"iedWidth"})
            _block(run.get("supportingMetrics"), SUPPORTING)
            versions[run_id] = {primary, *values}
            source_runs[run_id] = run
        envelopes = _rows(payloads[FILES[1]])
        records, records_by_id, envelope_by_id, refs_by_id = [], {}, {}, {}
        for envelope in envelopes:
            _require(envelope.get("synthetic") is True and envelope.get("appImportReady") is False,
                     "CORPUS_NOT_OFFLINE_SYNTHETIC")
            record = envelope.get("record")
            _require(isinstance(record, dict), "CORPUS_RECORD_INVALID")
            record_id = record.get("reviewId")
            _require(_text(record_id) and len(record_id) <= 200 and record_id not in records_by_id,
                     "CORPUS_RECORD_ID_INVALID")
            _require(envelope.get("split") in SPLITS, "CORPUS_SPLIT_INVALID")
            refs_by_id[record_id] = _check_record(record, versions, source_runs)
            records.append(record)
            records_by_id[record_id], envelope_by_id[record_id] = record, envelope
        documents = _rows(payloads[FILES[0]])
        documents_by_id = {}
        for document in documents:
            identifier, record_id = document.get("documentId"), document.get("recordId")
            _require(_text(identifier) and identifier not in documents_by_id, "CORPUS_DOCUMENT_ID_INVALID")
            _require(document.get("synthetic") is True, "CORPUS_DOCUMENT_NOT_SYNTHETIC")
            _require(isinstance(record_id, str) and record_id in records_by_id, "CORPUS_DOCUMENT_SOURCE_MISSING")
            record, envelope = records_by_id[record_id], envelope_by_id[record_id]
            _require(document.get("split") == envelope["split"], "CORPUS_DOCUMENT_SPLIT_MISMATCH")
            text = document.get("text")
            _require(isinstance(text, str), "CORPUS_DOCUMENT_TEXT_INVALID")
            _require(document.get("sourceNoteSha256") == _hash(text.encode("utf-8")), "CORPUS_NOTE_HASH_MISMATCH")
            _require(document.get("sourceRecordSha256") == _hash(_canonical(record).encode("utf-8")),
                     "CORPUS_RECORD_HASH_MISMATCH")
            refs = refs_by_id[record_id]
            _require(document.get("referencedRunIds") == [ref[0] for ref in refs], "CORPUS_DOCUMENT_REFERENCES_INVALID")
            if document.get("attribution") == "PER_RUN":
                _require(set(document) == PER_RUN_FIELDS, "CORPUS_DOCUMENT_FIELDS_INVALID")
                ref = _ref(document, versions)
                entry = evidence([record], ref[0])
                _require(len(entry) == 1 and entry[0]["runVersionId"] == ref[1], "CORPUS_DOCUMENT_ATTRIBUTION_INVALID")
                entry = entry[0]
                _require(identifier == record_id + ":" + ref[0] and text == entry["note"],
                         "CORPUS_DOCUMENT_ATTRIBUTION_INVALID")
                _require(document["decision"] == entry["decision"] and document["createdAt"] == entry["createdAt"]
                         and document["conditions"] == entry["conditions"], "CORPUS_DOCUMENT_METADATA_MISMATCH")
            elif document.get("attribution") == "SHARED_UNASSIGNED":
                _require(set(document) == SHARED_FIELDS, "CORPUS_DOCUMENT_FIELDS_INVALID")
                _require(document["runId"] is None and document["offlineRunVersionId"] is None
                         and document["classifiableAsPerRunCostEvidence"] is False
                         and document["noteField"] == "overallComment", "CORPUS_SHARED_ATTRIBUTION_INVALID")
                candidates = record.get("candidates")
                _require(record.get("version") == 2 and isinstance(candidates, list) and len(candidates) > 1,
                         "CORPUS_SHARED_SOURCE_INVALID")
                _require(identifier == record_id + ":SHARED" and text == record["overallComment"],
                         "CORPUS_SHARED_SOURCE_INVALID")
                _require(isinstance(document.get("candidateRunRefs"), list)
                         and [_ref(value, versions) for value in document["candidateRunRefs"]] == refs,
                         "CORPUS_SHARED_REFERENCES_INVALID")
            else:
                raise CorpusError("CORPUS_DOCUMENT_ATTRIBUTION_INVALID")
            documents_by_id[identifier] = document
        summary = manifest.get("summary", {})
        _require(isinstance(summary, dict), "CORPUS_MANIFEST_SCHEMA_INVALID")
        for key, count in (("runSnapshots", len(runs)), ("decisionRecords", len(records)),
                           ("searchableDocuments", len(documents))):
            _require(key not in summary or summary[key] == count, "CORPUS_COUNT_MISMATCH")
        identity = {"files": hashes, "policy": {"policy": rule["policy"], "sha256": rule["sha256"]}, "schema": SCHEMA}
        return cls(tuple(documents), tuple(records), tuple(runs), _hash(_canonical(identity).encode("utf-8")),
                   manifest, documents_by_id, records_by_id, versions)

    def scoped_documents(self, run_ids: Sequence[str], version_scope="history", run_refs=None):
        _require(version_scope in {"history", "exact"}, "CORPUS_VERSION_SCOPE_INVALID")
        _require(isinstance(run_ids, Sequence) and not isinstance(run_ids, (str, bytes))
                 and all(_text(run_id) for run_id in run_ids), "CORPUS_RUN_SCOPE_INVALID")
        ordered = list(dict.fromkeys(run_ids))
        _require(all(run_id in self.run_versions for run_id in ordered), "CORPUS_UNKNOWN_RUN")
        if not ordered:
            return []
        supplied: set[tuple[str, str]] | None = None
        if run_refs is not None:
            _require(isinstance(run_refs, Sequence) and not isinstance(run_refs, (str, bytes)), "CORPUS_RUN_SCOPE_INVALID")
            supplied = {_ref(value, self.run_versions) for value in run_refs}
            _require(all(ref[0] in ordered for ref in supplied), "CORPUS_REF_OUTSIDE_SCOPE")
        wanted_refs = supplied or set()
        if version_scope == "exact":
            _require(bool(supplied), "CORPUS_EXACT_REFS_REQUIRED")
            _require({ref[0] for ref in wanted_refs} == set(ordered), "CORPUS_EXACT_REFS_REQUIRED")
        result = []
        for document in self.documents:
            refs = _record_refs(self.records_by_id[document["recordId"]], self.run_versions)
            matched = {ref[0] for ref in refs if (ref in wanted_refs if version_scope == "exact" else ref[0] in ordered)}
            if not matched:
                continue
            if document["attribution"] == "SHARED_UNASSIGNED":
                role = "SHARED_UNASSIGNED"
            else:
                subject = (document["runId"], document["offlineRunVersionId"])
                direct = subject in wanted_refs if version_scope == "exact" else subject[0] in ordered
                role = "SUBJECT" if direct else "REFERENCE_ONLY"
            selected = deepcopy(document)
            selected["scopeRole"] = role
            selected["matchedRunIds"] = [run_id for run_id in ordered if run_id in matched]
            result.append(selected)
        return result
