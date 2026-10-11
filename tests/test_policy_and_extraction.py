import unittest

from marketplace_app.extraction import heuristic_extract, validate_extraction
from marketplace_app.policy import evaluate_policy_features


class ExtractionTests(unittest.TestCase):
    def test_heuristic_identifies_disguised_vape_language(self):
        features = heuristic_extract({
            "title": "Electronic aromatherapy straw",
            "description": "Hidden vapor stick",
        })
        self.assertEqual(features["normalized_product_type"], "e_cigarette")
        self.assertIn("vape_reference", features["risk_signals"])
        self.assertTrue(features["is_obfuscated_or_ambiguous"])

    def test_model_output_requires_a_real_boolean(self):
        with self.assertRaisesRegex(ValueError, "must be a boolean"):
            validate_extraction({
                "normalized_product_type": "other",
                "risk_signals": [],
                "is_obfuscated_or_ambiguous": "false",
                "confidence_score": 0.8,
                "reason_codes": [],
            })

    def test_model_output_rejects_confidence_outside_range(self):
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            validate_extraction({
                "normalized_product_type": "other",
                "risk_signals": [],
                "is_obfuscated_or_ambiguous": False,
                "confidence_score": 1.5,
                "reason_codes": [],
            })


class PolicyEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.rules = [
            {
                "id": 3,
                "rule_name": "prohibited_vape",
                "rule_type": "normalized_product_type",
                "condition_json": {"match": ["e_cigarette"]},
            },
            {
                "id": 4,
                "rule_name": "euphemistic_listing",
                "rule_type": "risk_signal",
                "condition_json": '{"match": ["euphemistic_language"]}',
            },
        ]

    def test_clear_listing_is_allowed(self):
        result = evaluate_policy_features(
            {"normalized_product_type": "pottery", "risk_signals": [], "reason_codes": []},
            {"e_cigarette"},
            self.rules,
        )
        self.assertEqual(result["decision"], "allow")
        self.assertEqual(result["matched_rule_ids"], [])

    def test_prohibited_type_is_rejected_and_matches_policy(self):
        result = evaluate_policy_features(
            {"normalized_product_type": "e_cigarette", "risk_signals": [], "reason_codes": []},
            {"e_cigarette"},
            self.rules,
        )
        self.assertEqual(result["decision"], "reject")
        self.assertEqual(result["matched_rule_ids"], [3])
        self.assertIn("prohibited_product", result["reason_codes"])

    def test_ambiguous_listing_goes_to_review_without_policy_match(self):
        result = evaluate_policy_features(
            {
                "normalized_product_type": "other",
                "risk_signals": [],
                "reason_codes": [],
                "is_obfuscated_or_ambiguous": True,
            },
            {"e_cigarette"},
            self.rules,
        )
        self.assertEqual(result["decision"], "review")
        self.assertIn("deceptive_labeling", result["reason_codes"])

    def test_matching_risk_signal_is_rejected(self):
        result = evaluate_policy_features(
            {
                "normalized_product_type": "other",
                "risk_signals": ["euphemistic_language"],
                "reason_codes": [],
            },
            {"e_cigarette"},
            self.rules,
        )
        self.assertEqual(result["decision"], "reject")
        self.assertEqual(result["matched_rule_ids"], [4])


if __name__ == "__main__":
    unittest.main()
