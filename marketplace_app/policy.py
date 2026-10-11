import json
from typing import Any


def evaluate_policy_features(
    features: dict[str, Any],
    prohibited_products: set[str],
    rules: list[dict[str, Any]],
) -> dict[str, Any]:
    """Apply deterministic policy rules to already-extracted listing features."""
    product_type = features.get("normalized_product_type", "other")
    decision = "reject" if product_type in prohibited_products else "allow"
    matched_rule_ids: list[int] = []
    matched_rule_names: list[str] = []
    reason_codes = set(features.get("reason_codes", []))

    if product_type in prohibited_products:
        reason_codes.add("prohibited_product")

    for rule in rules:
        condition = rule["condition_json"]
        if isinstance(condition, str):
            condition = json.loads(condition)
        matches = condition.get("match", [])
        rule_type = rule["rule_type"]
        if rule_type == "normalized_product_type":
            matched = product_type in matches
        elif rule_type == "risk_signal":
            matched = any(signal in features.get("risk_signals", []) for signal in matches)
        else:
            matched = False

        if matched:
            matched_rule_ids.append(rule["id"])
            matched_rule_names.append(rule["rule_name"])
            decision = "reject"

    if features.get("is_obfuscated_or_ambiguous") and decision == "allow":
        decision = "review"
        reason_codes.add("deceptive_labeling")

    return {
        "decision": decision,
        "matched_rule_ids": sorted(set(matched_rule_ids)),
        "matched_rule_names": matched_rule_names,
        "reason_codes": sorted(reason_codes),
    }
