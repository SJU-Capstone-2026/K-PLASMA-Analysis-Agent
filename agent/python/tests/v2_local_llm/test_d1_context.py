"""Selection changes only tool contracts and fails closed to the original wire state."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from kplasma_agent.v2_local_llm.comparison_catalog import FIELD_META
from kplasma_agent.v2_local_llm.core.d1_context import VERSION, context_identity, project_state
from kplasma_agent.v2_local_llm.core.d1_input import PROFILES, prepare_d1_input
from kplasma_agent.v2_local_llm.core.plan_checks import KINDS, build_check_specs, review_questions
from kplasma_agent.v2_local_llm.core.plan_review import build_plan_review_context
from v2_local_llm.plan_review_cases import cases, plan


def payload(case_id="P06", profile="en-compact-no-view"):
    case = next(item for item in cases() if item.id == case_id)
    source = build_plan_review_context(case.good, 1, case.question, [], case.context, {})
    return prepare_d1_input(source, review_questions(source), role="plan_review", profile=profile)[0]


def wire(value):
    return json.dumps(value, ensure_ascii=False, indent=2)


def check_metadata(state, meta):
    assert meta["version"] == VERSION
    assert meta["state_sha256"] == sha256(state.encode()).hexdigest()
    assert isinstance(meta["tool_ids"], list) and isinstance(meta["metric_ids"], list)


@pytest.mark.parametrize("profile", PROFILES)
def test_pressure_filter_preserves_everything_except_selected_contracts(profile):
    source = payload(profile=profile)
    before = deepcopy(source)
    original = wire(source)
    selected, meta = project_state(original, "filter.search.pressure")
    actual = json.loads(selected)
    assert meta["action"] == "selected"
    check_metadata(selected, meta)
    assert source == before
    assert {k: v for k, v in actual.items() if k != "tool_contracts"} == {
        k: v for k, v in before.items() if k != "tool_contracts"}
    contracts = actual["tool_contracts"]
    assert contracts["reverse_search"] == before["tool_contracts"]["reverse_search"]
    assert contracts["bindings"] == before["tool_contracts"]["bindings"]
    assert set(contracts["compare_runs"]["fields"]) == {"pressure", "sourcePower", "biasPower"}
    for name, field in contracts["compare_runs"]["fields"].items():
        assert field == before["tool_contracts"]["compare_runs"]["fields"][name]
        if "definition_ref" in field:
            ref = field["definition_ref"]
            assert contracts["compare_runs"]["field_definitions"][ref] == before[
                "tool_contracts"]["compare_runs"]["field_definitions"][ref]


@pytest.mark.parametrize("name", ["request.tasks", "request.filter_coverage",
    "request.confirmation_coverage", "outputs.compare", "selection_count.choose"])
def test_previously_full_checks_are_selected_without_changing_original_fields(name):
    original = wire(payload("P13")) + "\n  "
    selected, meta = project_state(original, name)
    assert selected != original
    assert meta["action"] == "selected"
    before, actual = json.loads(original), json.loads(selected)
    assert {k: v for k, v in actual.items() if k != "tool_contracts"} == {
        k: v for k, v in before.items() if k != "tool_contracts"}
    check_metadata(selected, meta)


@pytest.mark.parametrize("original", ["ordinary unit input", '{"unit": "ready"}',
    '{"interpretations": []}', "[]"])
def test_non_plan_requests_are_untouched(original):
    selected, meta = project_state(original, "unit")
    assert selected == original and meta["action"] == "full"


@pytest.mark.parametrize("corruption", ["unknown_check", "spec", "metric", "contract",
    "registry", "definition", "reference", "context", "version"])
def test_uncertainty_returns_exact_original(corruption):
    source = payload("P08")
    name = "targets.compare"
    if corruption == "unknown_check":
        name = "targets.absent"
    elif corruption == "spec":
        source["check_specs"][-4]["paths"] = [["steps", 999]]
    elif corruption == "metric":
        source["plan"]["steps"][-1]["inputs"]["fields"] = ["new.metric"]
    elif corruption == "contract":
        source["tool_contracts"]["reverse_search"]["operators"].append("approx")
    elif corruption == "registry":
        source["tool_contracts"]["compare_runs"]["fields"]["new.metric"] = {"unit": "x"}
    elif corruption == "definition":
        source["tool_contracts"]["compare_runs"]["field_definitions"].clear()
    elif corruption == "reference":
        source["plan"]["steps"][-1]["inputs"]["runs"]["step_id"] = "absent"
    elif corruption == "context":
        source["plan"]["steps"][-1]["inputs"]["runs"] = {
            "kind": "context_ref", "key": "absent"}
    else:
        source["schema_version"] = 99
    original = wire(source) + "\n"
    selected, meta = project_state(original, name)
    assert selected == original and meta["action"] == "fallback"
    check_metadata(selected, meta)


@pytest.mark.parametrize("case_id,name,tools", [
    ("P08", "targets.compare", {"compare_runs", "reverse_search"}),
    ("P09", "targets.compare", {"compare_runs", "reverse_search", "await_input"}),
    ("P07", "filter.search.ionFlux", {"compare_runs", "reverse_search", "derive"}),
    ("P11", "baseline.compare", {"compare_runs", "await_input"}),
])
def test_prior_tools_and_future_selection_references_are_preserved(case_id, name, tools):
    source = payload(case_id)
    selected, meta = project_state(wire(source), name)
    assert meta["action"] == "selected"
    actual = json.loads(selected)["tool_contracts"]
    assert tools <= set(actual)
    assert "bindings" in actual


@pytest.mark.parametrize("metric", list(FIELD_META))
def test_comparison_keeps_whole_confusion_group(metric):
    source = payload("P08")
    source["plan"]["steps"][-1]["inputs"]["fields"] = [metric]
    source["check_specs"] = build_check_specs(source["plan"])
    selected, meta = project_state(wire(source), "targets.compare")
    assert meta["action"] == "selected"
    fields = json.loads(selected)["tool_contracts"]["compare_runs"]["fields"]
    plot = FIELD_META[metric]["plotId"]
    group = {name for name, item in FIELD_META.items() if item["plotId"] == plot} if plot else (
        {"pressure", "sourcePower", "biasPower"} if metric in {"pressure", "sourcePower", "biasPower"}
        else {"ionFlux", "meanIonEnergy", "iedWidth"})
    assert group <= fields.keys()
    for name, field in fields.items():
        assert field == source["tool_contracts"]["compare_runs"]["fields"][name]


def test_forward_input_names_map_to_registered_comparison_ids():
    source = payload()
    source["plan"] = plan("인공 조회", [{"id": "lookup", "kind": "tool", "tool": "forward_lookup",
        "inputs": {}}]).model_dump(mode="json")
    source["check_specs"] = build_check_specs(source["plan"])
    selected, meta = project_state(wire(source), "filter.lookup.source_power")
    assert meta["action"] == "selected"
    assert {"pressure", "sourcePower", "biasPower"} <= set(meta["metric_ids"])
    assert "forward_lookup" in meta["tool_ids"]


def test_empty_ordering_goals_keep_all_searchable_metric_definitions():
    source = payload()
    selected, meta = project_state(wire(source), "ordering.search")
    assert meta["action"] == "selected"
    assert set(json.loads(selected)["tool_contracts"]["compare_runs"]["fields"]) == {
        "pressure", "sourcePower", "biasPower", "ionFlux", "meanIonEnergy", "iedWidth"}


def test_identity_pins_source_files_and_rejects_unknown_modes():
    full = context_identity("full")
    selected = context_identity("per_check")
    assert full == {**selected, "mode": "full"}
    assert full["version"] == VERSION
    for key in ("selector_sha256", "registry_sha256", "projection_sha256", "dependency_sha256"):
        assert len(full[key]) == 64 and int(full[key], 16) >= 0
    with pytest.raises(ValueError, match="LOCAL_D1_CONTEXT_CONFIG_INVALID"):
        context_identity("automatic")


def test_unreviewed_registry_extension_falls_back(monkeypatch):
    source = payload()
    original = wire(source)
    monkeypatch.setitem(FIELD_META, "new.metric", {"plotId": "current", "unit": "V"})
    selected, meta = project_state(original, "filter.search.pressure")
    assert selected == original and meta["action"] == "fallback"


@pytest.mark.parametrize("relative_path", ["metric_registry.py", "contracts.py", "core/contracts.py",
                                          "core/plan_checks.py", "core/plan_review.py"])
def test_identity_changes_when_imported_contract_dependency_changes(monkeypatch, relative_path):
    before = context_identity("per_check")
    original = Path.read_bytes
    suffix = "/v2_local_llm/" + relative_path

    def changed_bytes(path):
        contents = original(path)
        return contents + b"\n# synthetic source revision" if str(path).endswith(suffix) else contents

    monkeypatch.setattr(Path, "read_bytes", changed_bytes)
    after = context_identity("per_check")
    assert after["dependency_sha256"] != before["dependency_sha256"]
    assert {k: v for k, v in after.items() if k != "dependency_sha256"} == {
        k: v for k, v in before.items() if k != "dependency_sha256"}


@pytest.mark.parametrize("case", cases(), ids=lambda case: case.id)
@pytest.mark.parametrize("bad", [False, True])
def test_existing_pairs_never_change_plan_checks_policy_or_user_text(case, bad):
    source = build_plan_review_context(
        case.bad if bad else case.good, 1, case.question, [], case.context, {})
    source = prepare_d1_input(source, review_questions(source), role="plan_review",
                              profile="en-compact-no-view")[0]
    original = wire(source)
    before = deepcopy(source)
    for spec in source["check_specs"]:
        selected, meta = project_state(original, spec["name"])
        check_metadata(selected, meta)
        assert meta["action"] == "selected"
        actual = json.loads(selected)
        assert {k: v for k, v in actual.items() if k != "tool_contracts"} == {
            k: v for k, v in source.items() if k != "tool_contracts"}
        if meta["action"] != "selected":
            assert selected == original
    assert source == before


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("name", ["request.tasks", "request.filter_coverage",
                                  "request.confirmation_coverage"])
def test_global_profiles_are_fixed_even_when_requested_work_is_absent(profile, name):
    source = payload("P06", profile)
    other = payload("P13", profile)
    selected, meta = project_state(wire(source), name)
    alternate, _ = project_state(wire(other), name)
    contracts = json.loads(selected)["tool_contracts"]
    assert meta["action"] == "selected"
    assert contracts == json.loads(alternate)["tool_contracts"]
    original = source["tool_contracts"]
    if name == "request.tasks":
        assert contracts.keys() == original.keys()
        assert set(contracts["compare_runs"]["fields"]) == set(FIELD_META)
        assert "field_definitions" not in contracts["compare_runs"]
        for field, item in contracts["compare_runs"]["fields"].items():
            assert item == {k: v for k, v in original["compare_runs"]["fields"][field].items()
                            if k not in {"definition", "definition_ref"}}
    elif name == "request.filter_coverage":
        assert {"forward_lookup", "reverse_search", "bindings"} <= contracts.keys()
        assert set(contracts["compare_runs"]["fields"]) == {
            "pressure", "sourcePower", "biasPower", "ionFlux", "meanIonEnergy", "iedWidth"}
    else:
        assert set(contracts) == {"await_input", "compare_runs", "bindings"}
        assert "fields" not in contracts["compare_runs"]
        assert "field_definitions" not in contracts["compare_runs"]
        assert contracts["await_input"] == original["await_input"]


@pytest.mark.parametrize("profile", PROFILES)
def test_outputs_keep_all_definitions_including_metrics_omitted_from_plan(profile):
    source = payload("P08", profile)
    assert source["plan"]["steps"][-1]["inputs"]["fields"] == ["pressure"]
    selected, meta = project_state(wire(source), "outputs.compare")
    contracts = json.loads(selected)["tool_contracts"]
    assert meta["action"] == "selected"
    assert set(contracts) == {"compare_runs", "bindings"}
    assert contracts["compare_runs"] == source["tool_contracts"]["compare_runs"]
    assert set(meta["metric_ids"]) == set(FIELD_META)


def test_all_thirteen_kinds_have_a_selected_policy():
    covered = set()
    for case in cases():
        source = payload(case.id)
        for spec in source["check_specs"]:
            _, meta = project_state(wire(source), spec["name"])
            assert meta["action"] == "selected", spec
            covered.add(spec["kind"])
    assert covered == KINDS.keys()
    assert VERSION == "d1-context-2"


def test_selection_count_needs_no_metric_definitions_or_candidate_execution():
    source = payload("P13")
    selected, meta = project_state(wire(source), "selection_count.choose")
    contracts = json.loads(selected)["tool_contracts"]
    assert meta["action"] == "selected" and meta["metric_ids"] == []
    assert set(contracts) == {"await_input", "bindings"}


def test_literal_only_operation_selects_without_inventing_metrics():
    source = payload()
    source["plan"] = plan("인공 계산", [{"id": "calc", "kind": "derive", "operation": "min",
        "inputs": {"values": [{"kind": "literal", "value": value, "unit": "eV",
            "source": {"message_key": "question", "quote": "인공 계산"}} for value in [150, 160]]}}
        ]).model_dump(mode="json")
    source["check_specs"] = build_check_specs(source["plan"])
    selected, meta = project_state(wire(source), "operation.calc")
    assert meta["action"] == "selected" and meta["metric_ids"] == []
    assert set(json.loads(selected)["tool_contracts"]) == {"derive", "bindings"}


def test_unknown_kind_retains_exact_fallback():
    source = payload()
    source["check_specs"][0]["kind"] = "new_kind"
    original = wire(source)
    selected, meta = project_state(original, "request.tasks")
    assert selected == original and meta["action"] == "fallback"
