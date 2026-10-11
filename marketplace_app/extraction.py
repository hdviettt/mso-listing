from typing import Any


def heuristic_extract(raw_listing: dict[str, Any]) -> dict[str, Any]:
    """Return a small deterministic fallback when the local model is unavailable."""
    text = " ".join(
        str(raw_listing.get(field, ""))
        for field in ("title", "description", "declared_category")
    ).lower()

    normalized_product_type = "other"
    risk_signals: list[str] = []
    reason_codes: list[str] = []
    term_groups = (
        (("vape", "v@pe", "e-cig", "e cigarette", "electronic cigarette", "disposable vape", "vapor pen", "electronic aromatherapy straw"), "e_cigarette", "vape_reference"),
        (("cocaine", "mdma", "controlled substance", "narcotic", "psychedelic"), "controlled_substance", "controlled_substance_reference"),
        (("gun", "knife", "switchblade", "concealed weapon"), "concealed_weapon", "weapon_reference"),
    )
    for terms, product_type, signal in term_groups:
        if any(term in text for term in terms):
            normalized_product_type = product_type
            risk_signals.append(signal)
            reason_codes.append("prohibited_product")
            break

    ambiguous_terms = ("wellness", "aromatherapy", "cooling", "secret style", "premium flavor", "mini device")
    if any(term in text for term in ambiguous_terms):
        risk_signals.append("euphemistic_language")
        reason_codes.append("deceptive_labeling")

    is_ambiguous = (
        "v@pe" in text
        or "aromatherapy" in text
        or ("wellness" in text and "vape" in text)
        or ("mist" in text and "minis" in text)
        or "hidden" in text
    )
    if not risk_signals and normalized_product_type == "other" and ("pottery" in text or "ceramic" in text):
        normalized_product_type = "pottery"

    return {
        "normalized_product_type": normalized_product_type,
        "risk_signals": sorted(set(risk_signals)),
        "is_obfuscated_or_ambiguous": is_ambiguous,
        "confidence_score": 0.93 if risk_signals else 0.84,
        "reason_codes": sorted(set(reason_codes)),
    }


def validate_extraction(parsed: Any) -> dict[str, Any]:
    """Check the model output contract before passing features to policy logic."""
    if not isinstance(parsed, dict):
        raise ValueError("Extraction response must be a JSON object.")

    product_type = parsed.get("normalized_product_type")
    risk_signals = parsed.get("risk_signals")
    ambiguous = parsed.get("is_obfuscated_or_ambiguous")
    confidence = parsed.get("confidence_score")
    reason_codes = parsed.get("reason_codes")
    if not isinstance(product_type, str) or not product_type.strip():
        raise ValueError("normalized_product_type must be a non-empty string.")
    if not isinstance(risk_signals, list) or not all(isinstance(item, str) for item in risk_signals):
        raise ValueError("risk_signals must be an array of strings.")
    if not isinstance(ambiguous, bool):
        raise ValueError("is_obfuscated_or_ambiguous must be a boolean.")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise ValueError("confidence_score must be a number between 0 and 1.")
    if not isinstance(reason_codes, list) or not all(isinstance(item, str) for item in reason_codes):
        raise ValueError("reason_codes must be an array of strings.")

    return {
        "normalized_product_type": product_type.strip().lower(),
        "risk_signals": sorted(set(item.strip().lower() for item in risk_signals)),
        "is_obfuscated_or_ambiguous": ambiguous,
        "confidence_score": round(float(confidence), 2),
        "reason_codes": sorted(set(item.strip().lower() for item in reason_codes)),
    }

