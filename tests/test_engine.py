import unittest
from unittest.mock import patch

from marketplace_app import engine


class ListingEngineTests(unittest.TestCase):
    def test_reject_is_streamed_and_written_as_audit_only(self):
        emitted = []
        features = {
            "normalized_product_type": "e_cigarette",
            "risk_signals": ["vape_reference"],
            "is_obfuscated_or_ambiguous": True,
            "confidence_score": 0.99,
            "reason_codes": [],
        }
        rules = [
            {
                "id": 9,
                "rule_name": "prohibited_vape",
                "rule_type": "normalized_product_type",
                "condition_json": {"match": ["e_cigarette"]},
            }
        ]
        with (
            patch.object(engine, "extract_listing_features", return_value=features),
            patch.object(engine, "get_active_policy_version", return_value="test-v1"),
            patch.object(engine, "get_active_prohibited_products", return_value=["e_cigarette"]),
            patch.object(engine, "get_active_policy_records", return_value=rules),
            patch.object(engine, "save_submission") as save_submission,
            patch.object(engine, "save_decision") as save_decision,
        ):
            result = engine.evaluate_listing({"vendor_id": "vendor_test"}, emitted.append)

        self.assertEqual(result["decision"], "reject")
        self.assertEqual(result["policy_version"], "test-v1")
        self.assertEqual([event["stage"] for event in emitted], ["intake", "extraction", "policy", "routing"])
        self.assertFalse(emitted[-1]["properties"]["catalog_write"])
        save_submission.assert_called_once()
        save_decision.assert_called_once()


if __name__ == "__main__":
    unittest.main()
