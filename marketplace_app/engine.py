import json
import uuid
from collections.abc import Callable
from typing import Any

from marketplace_app.db import (
    get_active_policy_records,
    get_active_policy_version,
    get_active_prohibited_products,
    save_decision,
    save_submission,
    upsert_review_queue,
)
from marketplace_app.model_client import extract_listing_features
from marketplace_app.policy import evaluate_policy_features


def evaluate_listing(
    raw_submission: dict[str, Any],
    on_step: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Extract features, apply the active policy, then persist the audit outcome."""

    def emit(stage: str, title: str, detail: str, properties: dict[str, Any]) -> None:
        if on_step is not None:
            on_step({"stage": stage, "title": title, "detail": detail, "properties": properties})

    submission_id = str(uuid.uuid4())
    vendor_id = str(raw_submission.get("vendor_id", "unknown_vendor"))
    emit(
        "intake",
        "Payload received",
        "Seller fields accepted for evaluation.",
        {
            "submission_id": submission_id,
            "vendor_id": vendor_id,
            "title": raw_submission.get("title", ""),
            "declared_category": raw_submission.get("declared_category", ""),
            "price": raw_submission.get("price"),
        },
    )

    features = extract_listing_features(raw_submission)
    emit(
        "extraction",
        "Features extracted",
        "Listing fields normalized into policy features.",
        features,
    )

    # The model provides evidence only. This function owns the disposition.
    policy_result = evaluate_policy_features(
        features,
        set(get_active_prohibited_products()),
        get_active_policy_records(),
    )
    policy_version = get_active_policy_version()
    decision = policy_result["decision"]
    matched_rule_ids = policy_result["matched_rule_ids"]
    matched_rule_names = policy_result["matched_rule_names"]
    reason_codes = policy_result["reason_codes"]
    normalized_type = features.get("normalized_product_type", "other")
    emit(
        "policy",
        "Policy evaluation complete",
        f"{decision.capitalize()}: {len(matched_rule_ids)} matching rule(s).",
        {
            "decision": decision,
            "policy_version": policy_version,
            "matched_rule_ids": matched_rule_ids,
            "matched_rule_names": matched_rule_names,
            "reason_codes": reason_codes,
            "normalized_product_type": normalized_type,
        },
    )

    if decision == "reject":
        review_queue_id = None
        case_note = "High-risk listing blocked before catalog write-through."
    elif decision == "review":
        review_queue_id = upsert_review_queue(
            submission_id,
            "normal",
            "Ambiguous listing requires human review.",
        )
        case_note = "Listing sent to manual review queue."
    else:
        review_queue_id = None
        case_note = "No active policy match found."

    status = {"allow": "accepted", "review": "review", "reject": "quarantined"}[decision]
    save_submission(
        submission_id=submission_id,
        vendor_id=vendor_id,
        raw_payload=raw_submission,
        extracted_payload=features,
        status=status,
    )
    save_decision(
        submission_id=submission_id,
        decision=decision,
        policy_version=policy_version,
        matched_rule_ids=matched_rule_ids,
        reason_codes=reason_codes,
        review_queue_id=review_queue_id,
    )
    emit(
        "routing",
        "Listing routed",
        case_note,
        {
            "decision": decision,
            "status": status,
            "policy_version": policy_version,
            "review_queue_id": review_queue_id,
            "catalog_write": decision == "allow",
        },
    )

    trace = [
        {
            "step": "submission_received",
            "detail": "Seller payload ingested before catalog write-through.",
        },
        {"step": "llm_extraction", "detail": json.dumps(features, ensure_ascii=False)},
        {
            "step": "policy_evaluation",
            "detail": f"Decision: {decision}. Matched rules: {matched_rule_ids or 'none'}",
        },
        {"step": "routing", "detail": case_note},
    ]
    return {
        "submission_id": submission_id,
        "vendor_id": vendor_id,
        "decision": decision,
        "policy_version": policy_version,
        "matched_rule_ids": matched_rule_ids,
        "reason_codes": reason_codes,
        "status": status,
        "review_queue_id": review_queue_id,
        "extracted_payload": features,
        "trace": trace,
    }
