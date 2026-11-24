"""Compile writer-selected values into the existing private answer contract."""

from typing import Annotated, Literal

from pydantic import Field, create_model

from ..answer_stream import AnswerStreamProjector
from .composition import fill_value_references
from .contracts import ClosedModel, DataAnswerDraft, Identifier


class TextSegment(ClosedModel):
    kind: Literal["text"]
    text: str


class SelectedValues:
    def __init__(self, context):
        self.evidence_bindings = {f"E{index}": evidence["id"]
                                  for index, evidence in enumerate(context.get("evidence", []), 1)}
        self.evidence_choices = [{"ref": ref, "evidence_id": identifier}
                                 for ref, identifier in self.evidence_bindings.items()]
        citations = (list[Literal[tuple(self.evidence_bindings)]] if self.evidence_bindings else
                     Annotated[list[Identifier], Field(max_length=0)])
        self.bindings = {}
        for evidence in context.get("evidence", []):
            for part in evidence.get("value_parts", []):
                identifier = evidence["id"]
                if any(char in identifier + part for char in "{}|"):
                    raise ValueError("invalid evidence value address")
                self.bindings[f"V{len(self.bindings) + 1}"] = (identifier, part)
        self.choices = [{"ref": ref, "evidence_id": identifier, "part": part}
                        for ref, (identifier, part) in self.bindings.items()]
        segment = TextSegment
        if self.bindings:
            reference = create_model("EvidenceSegment", __base__=ClosedModel,
                kind=(Literal["evidence"], ...), ref=(Literal[tuple(self.bindings)], ...))
            segment = TextSegment | reference
        interpretation = create_model("SelectedInterpretation", __base__=ClosedModel,
            id=(Identifier, ...), evidence_ids=(citations, ...), segments=(list[segment], ...),
            assumptions=(list[list[segment]], ...))
        limitation = create_model("SelectedLimitation", __base__=ClosedModel,
            id=(Identifier, ...), evidence_ids=(citations, ...), segments=(list[segment], ...))
        self.output_model = create_model("SelectedDataAnswerDraft", __base__=ClosedModel,
            fact_ids=(citations, ...), interpretations=(list[interpretation], ...),
            limitations=(list[limitation], ...))

    def reference(self, ref):
        if ref not in self.bindings:
            raise ValueError("unknown selected value")
        identifier, part = self.bindings[ref]
        return "{{value:" + identifier + "|" + part + "}}", identifier

    def text(self, value):
        if "{{value" in value:
            raise ValueError("value references must use evidence segments")
        return value

    def _compile_segments(self, segments):
        text, identifiers, literal = [], [], ""
        for segment in segments:
            if segment["kind"] == "text":
                literal += segment["text"]
                self.text(literal)
                text.append(self.text(segment["text"]))
            else:
                literal = ""
                reference, identifier = self.reference(segment["ref"])
                text.append(reference)
                identifiers.append(identifier)
        return "".join(text), identifiers

    def compile(self, data):
        result = self.output_model.model_validate(data).model_dump(mode="json")
        result["fact_ids"] = [self.evidence_bindings[ref] for ref in result["fact_ids"]]
        for group in ("interpretations", "limitations"):
            for item in result[group]:
                item["text"], selected = self._compile_segments(item.pop("segments"))
                if group == "interpretations":
                    assumptions = []
                    for segments in item["assumptions"]:
                        text, identifiers = self._compile_segments(segments)
                        assumptions.append(text)
                        selected.extend(identifiers)
                    item["assumptions"] = assumptions
                item["evidence_ids"] = list(dict.fromkeys([
                    *(self.evidence_bindings[ref] for ref in item["evidence_ids"]), *selected]))
        return DataAnswerDraft.model_validate(result).model_dump(mode="json")

    def projector(self, on_block, *, numeric_values):
        return SelectedValueProjector(self, on_block, numeric_values=numeric_values)


class SelectedValueProjector(AnswerStreamProjector):
    def __init__(self, selection, on_block, *, numeric_values):
        super().__init__("data_request", on_block, evidence_ids=[identifier for identifier, _ in
                         selection.bindings.values()], numeric_values=numeric_values)
        self.selection = selection

    def _segments_prefix(self, prefix):
        text, index = "", 0
        while True:
            path = (*prefix, index)
            kind_path = (*path, "kind")
            if kind_path not in self.decoder.complete:
                return text
            kind = self.decoder.strings[kind_path]
            if kind == "text":
                value = self.selection.text(self.decoder.strings.get((*path, "text"), ""))
                text += value
            elif kind == "evidence":
                if (*path, "ref") not in self.decoder.complete:
                    return text
                reference, identifier = self.selection.reference(self.decoder.strings[(*path, "ref")])
                text += fill_value_references(reference, [identifier], self.numeric_values,
                                              evidence_ids=self.evidence_ids)
            else:
                raise ValueError("unknown answer segment kind")
            if path not in self.decoder.complete:
                return text
            index += 1

    def feed(self, delta):
        if self.invalid:
            return
        try:
            self.decoder.feed(delta)
            prefixes = {}
            for path in self.decoder.strings:
                if len(path) >= 5 and path[0] in {"interpretations", "limitations"} and path[2] == "segments":
                    prefixes[path[:3]] = (*path[:2], "text")
                elif len(path) >= 6 and path[0] == "interpretations" and path[2] == "assumptions":
                    prefixes[path[:4]] = path[:4]
            for prefix, public in prefixes.items():
                text = self.selection.text(self._segments_prefix(prefix))
                if prefix not in self.decoder.complete:
                    for size in range(len("{{value") - 1, 0, -1):
                        if text.endswith("{{value"[:size]):
                            text = text[:-size]
                            break
                previous = self.published.get(public, "")
                if text.startswith(previous) and len(text) > len(previous):
                    self.on_block(".".join(map(str, public)), text[len(previous):])
                    self.published[public] = text
        except (ValueError, KeyError, TypeError):
            self.invalid = True
