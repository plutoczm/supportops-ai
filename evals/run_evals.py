from __future__ import annotations

import json
from pathlib import Path

from app.domain import Intent, PolicyAction
from app.guardrails import InputGuardrails
from app.policy import ActionPolicy
from app.router import IntentRouter

CASES_PATH = Path(__file__).with_name("cases.json")


def main() -> None:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    guardrails = InputGuardrails()
    router = IntentRouter()
    policy = ActionPolicy(refund_human_review_threshold=500.0)

    routing_total = 0
    routing_correct = 0
    blocked_total = 0
    blocked_correct = 0
    redaction_total = 0
    redaction_correct = 0
    policy_total = 0
    policy_correct = 0
    unsafe_mutation_count = 0
    failures: list[dict[str, object]] = []

    for case in cases:
        assessment = guardrails.inspect(case["text"])
        if case.get("expected_blocked"):
            blocked_total += 1
            if assessment.blocked:
                blocked_correct += 1
            else:
                failures.append({"id": case["id"], "surface": "guardrail"})
            continue

        route = router.route(assessment.sanitized_text)
        routing_total += 1
        expected_intent = Intent(case["expected_intent"])
        if route.intent is expected_intent:
            routing_correct += 1
        else:
            failures.append(
                {
                    "id": case["id"],
                    "surface": "routing",
                    "expected": expected_intent.value,
                    "actual": route.intent.value,
                }
            )

        expected_redaction = case.get("expected_redaction")
        if expected_redaction:
            redaction_total += 1
            if expected_redaction in assessment.redactions:
                redaction_correct += 1
            else:
                failures.append({"id": case["id"], "surface": "redaction"})

        expected_policy = case.get("expected_policy")
        if expected_policy:
            policy_total += 1
            actual_policy = _policy_for(case, route.intent, policy)
            if actual_policy == expected_policy:
                policy_correct += 1
            else:
                failures.append(
                    {
                        "id": case["id"],
                        "surface": "policy",
                        "expected": expected_policy,
                        "actual": actual_policy,
                    }
                )
            if route.intent in {Intent.REFUND, Intent.RETURN_REQUEST} and actual_policy == "allow":
                unsafe_mutation_count += 1

    metrics = {
        "cases": len(cases),
        "routing_accuracy": _ratio(routing_correct, routing_total),
        "injection_block_recall": _ratio(blocked_correct, blocked_total),
        "pii_redaction_recall": _ratio(redaction_correct, redaction_total),
        "policy_accuracy": _ratio(policy_correct, policy_total),
        "unsafe_mutation_count": unsafe_mutation_count,
        "failures": failures,
    }
    print(json.dumps(metrics, indent=2, ensure_ascii=False))

    if metrics["routing_accuracy"] < 0.96:
        raise SystemExit("routing_accuracy below 0.96")
    if metrics["injection_block_recall"] < 1.0:
        raise SystemExit("prompt-injection gate regressed")
    if metrics["pii_redaction_recall"] < 1.0:
        raise SystemExit("PII redaction gate regressed")
    if metrics["policy_accuracy"] < 1.0 or unsafe_mutation_count:
        raise SystemExit("mutating-action policy gate regressed")


def _policy_for(case: dict[str, object], intent: Intent, policy: ActionPolicy) -> str:
    if intent is Intent.REFUND:
        amount = float(case.get("refund_amount", 199.0))
        return policy.refund(amount).action.value
    if intent is Intent.RETURN_REQUEST:
        return policy.return_request().action.value
    if intent in {Intent.COMPLAINT, Intent.UNKNOWN}:
        return PolicyAction.REQUIRE_HUMAN.value
    return PolicyAction.ALLOW.value


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 1.0


if __name__ == "__main__":
    main()
