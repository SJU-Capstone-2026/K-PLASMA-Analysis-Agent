"""Expose only server-attested exact Run names as pinned planning references."""


def named_run_context(context, question=None):
    refs = context.get("namedRunReferences", [])
    bindings = context.get("namedRunBindings", [])
    if not isinstance(refs, list) or not isinstance(bindings, list) or len(refs) > 150 or len(bindings) > 150:
        raise ValueError("INVALID_NAMED_RUN_CONTEXT")
    if not refs and not bindings:
        return {}
    if any(not isinstance(ref, dict) or set(ref) != {"runId", "runVersionId"}
           or any(not isinstance(ref.get(key), str) or not ref[key] for key in ("runId", "runVersionId"))
           for ref in refs):
        raise ValueError("INVALID_NAMED_RUN_CONTEXT")
    values = {"named_runs": refs, "namedRunReferences": refs}
    attested = []
    for item in bindings:
        if not isinstance(item, dict):
            raise ValueError("INVALID_NAMED_RUN_CONTEXT")
        name, ref, source = item.get("name"), item.get("ref"), item.get("source")
        if (not isinstance(name, str) or not name or ref not in refs or not isinstance(source, dict)
                or source.get("message_key") != "question" or not isinstance(source.get("quote"), str)
                or source["quote"].casefold() != name.casefold() or ref["runId"] != name
                or (question is not None and source["quote"] not in question)):
            raise ValueError("INVALID_NAMED_RUN_CONTEXT")
        key = "named:" + name
        if key in values and values[key] != ref:
            raise ValueError("INVALID_NAMED_RUN_CONTEXT")
        values[key] = ref
        attested.append({"name": name, "context_key": key, "ref": ref, "source": source})
    if any(ref not in [item["ref"] for item in attested] for ref in refs):
        raise ValueError("INVALID_NAMED_RUN_CONTEXT")
    values["named_run_bindings"] = attested
    return values
