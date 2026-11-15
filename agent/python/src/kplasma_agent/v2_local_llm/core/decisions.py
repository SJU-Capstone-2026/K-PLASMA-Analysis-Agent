"""Translate typed decisions at the local native System One boundary."""

import json
import math


def native_request(body):
    messages = body["input"]
    if not isinstance(messages, list) or len(messages) != 1 or messages[0].get("role") != "user":
        raise ValueError("DECISIONS_INVALID_REQUEST")
    content = messages[0]["content"]
    if not isinstance(content, list) or len(content) != 1 or content[0].get("type") != "input_json":
        raise ValueError("DECISIONS_INVALID_REQUEST")
    state = json.dumps(content[0]["data"], ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    questions = {}
    if not isinstance(body["questions"], list) or not body["questions"]:
        raise ValueError("DECISIONS_INVALID_REQUEST")
    for question in body["questions"]:
        name = question["name"]
        if not isinstance(name, str) or not name or name in questions or question["type"] != "choice":
            raise ValueError("DECISIONS_INVALID_REQUEST")
        if not isinstance(question["instructions"], str) or not question["instructions"]:
            raise ValueError("DECISIONS_INVALID_REQUEST")
        choices = question["choices"]
        if not isinstance(choices, list) or len(choices) < 2:
            raise ValueError("DECISIONS_INVALID_REQUEST")
        criteria = {}
        for choice in choices:
            value = choice["value"]
            if not isinstance(value, str) or not value or value in criteria:
                raise ValueError("DECISIONS_INVALID_REQUEST")
            description = choice["description"]
            if description is not None and not isinstance(description, str):
                raise ValueError("DECISIONS_INVALID_REQUEST")
            criteria[value] = description
        questions[name] = {"type": "choice", "instructions": question["instructions"], "criteria": criteria}
    return {"state": state, "questions": questions}


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("DECISIONS_INVALID_RESPONSE")
        value[key] = item
    return value


def _invalid_number(_):
    raise ValueError("DECISIONS_INVALID_RESPONSE")


def _probability(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and 0 <= value <= 1 and math.isfinite(value))


def normalize_response(raw, questions):
    data = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_invalid_number)
    if not isinstance(data, dict) or not isinstance(data.get("answers"), dict):
        raise ValueError("DECISIONS_INVALID_RESPONSE")
    answers = data["answers"]
    if set(answers) != set(questions):
        raise ValueError("DECISIONS_INVALID_RESPONSE")
    rows = []
    for name, question in questions.items():
        row = answers[name]
        if not isinstance(row, dict) or row.get("type") != "choice":
            raise ValueError("DECISIONS_INVALID_RESPONSE")
        choices = question["criteria"]
        probabilities = row.get("probabilities")
        if (not isinstance(row.get("choice"), str) or row["choice"] not in choices
                or not isinstance(probabilities, dict) or set(probabilities) != set(choices)
                or not all(_probability(value) for value in probabilities.values())
                or not math.isclose(math.fsum(probabilities.values()), 1.0, rel_tol=0, abs_tol=1e-6)):
            raise ValueError("DECISIONS_INVALID_RESPONSE")
        result = {"name": name, "type": "choice", "choice": row["choice"],
                  "probabilities": [{"value": label, "probability": probabilities[label]} for label in choices]}
        if "confidence" in row:
            if row["confidence"] is not None and not _probability(row["confidence"]):
                raise ValueError("DECISIONS_INVALID_RESPONSE")
            result["confidence"] = row["confidence"]
        rows.append(result)
    usage = data.get("usage")
    if usage is not None and not isinstance(usage, dict):
        raise ValueError("DECISIONS_INVALID_RESPONSE")
    return {"answers": rows, "usage": usage}
