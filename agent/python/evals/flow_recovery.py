"""Attribute observed repair calls, separately from the final correctness grade."""

from datetime import datetime


def classify(attempts, final_pass):
    ordered = sorted(attempts, key=lambda row: (datetime.fromisoformat(row["deadline"]), row["id"]))
    decisions = []
    triggered = []
    for index, row in enumerate(ordered):
        data = (row.get("outcome") or {}).get("data") or {}
        if row["kind"] == "PLAN_REVIEW":
            decisions.append(
                {
                    "attemptId": row["id"],
                    "key": row["attempt_key"],
                    "status": data.get("status"),
                    "reason": data.get("reason"),
                    "planRevision": data.get("plan_revision"),
                    "checks": data.get("checks", []),
                }
            )
            if data.get("status") in ("ISSUE", "UNCLEAR") and index + 1 < len(ordered):
                following = ordered[index + 1]
                if following["kind"] == "REPLAN":
                    triggered.append(
                        {
                            "reviewAttemptId": row["id"],
                            "reviewStatus": data["status"],
                            "replanAttemptId": following["id"],
                            "replanKey": following["attempt_key"],
                        }
                    )
    replans = [row for row in ordered if row["kind"] == "REPLAN"]
    if not final_pass:
        category = "failed"
    elif triggered:
        category = "passed_after_decisions_replan"
    elif replans:
        category = "passed_after_other_replan"
    else:
        category = "passed_without_replan"
    return {
        "category": category,
        "finalPass": final_pass,
        "replans": len(replans),
        "planReviews": decisions,
        "decisionTriggeredReplans": triggered,
        "decisionsCaughtIssue": any(item["status"] in ("ISSUE", "UNCLEAR") for item in decisions),
        "decisionsReplanRecovered": bool(triggered) and final_pass,
        "answerRewriteCalls": sum(row["kind"] == "ANSWER_REWRITE" for row in ordered),
    }


if __name__ == "__main__":

    def row(index, kind, status=None):
        return {
            "id": str(index),
            "attempt_key": str(index),
            "kind": kind,
            "deadline": f"2026-11-09T00:00:{index:02d}+00:00",
            "outcome": {"data": {"status": status}},
        }

    sequence = [
        row(1, "PLAN_INITIAL"),
        row(2, "PLAN_REVIEW", "ISSUE"),
        row(3, "REPLAN"),
        row(4, "PLAN_REVIEW", "PASS"),
    ]
    assert classify(sequence, True)["category"] == "passed_after_decisions_replan"
    assert classify(sequence, False)["decisionsReplanRecovered"] is False
    assert (
        classify([row(1, "PLAN_INITIAL"), row(2, "REPLAN"), row(3, "PLAN_REVIEW", "PASS")], True)["category"]
        == "passed_after_other_replan"
    )
    assert (
        classify([row(1, "PLAN_INITIAL"), row(2, "REPLAN"), row(3, "PLAN_REVIEW", "ISSUE")], True)[
            "decisionTriggeredReplans"
        ]
        == []
    )
    assert classify([row(1, "PLAN_INITIAL"), row(2, "PLAN_REVIEW", "UNAVAILABLE")], False)["replans"] == 0
    assert (
        classify([row(1, "PLAN_INITIAL"), row(2, "PLAN_REVIEW", "PASS"), row(3, "ANSWER_REWRITE")], True)[
            "category"
        ]
        == "passed_without_replan"
    )
    print(
        "PASS: rejection-before-replan, final correctness, other repair, exhausted repair, and answer rewrite are distinct."
    )
