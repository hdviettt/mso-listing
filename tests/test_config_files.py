import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ConfigurationFileTests(unittest.TestCase):
    def test_active_policy_bundle_has_supported_rule_types(self):
        policy_path = PROJECT_ROOT / "config" / "policies" / "active.json"
        policy = json.loads(policy_path.read_text(encoding="utf-8-sig"))
        self.assertTrue(policy["version_name"])
        self.assertTrue(policy["prohibited_products"])
        self.assertTrue(policy["rules"])
        self.assertTrue(
            all(rule["rule_type"] in {"normalized_product_type", "risk_signal"} for rule in policy["rules"])
        )

    def test_extraction_prompt_keeps_listing_placeholder(self):
        prompt_path = PROJECT_ROOT / "config" / "prompts" / "listing_extraction.txt"
        prompt = prompt_path.read_text(encoding="utf-8-sig")
        self.assertIn("{listing_json}", prompt)
        self.assertIn("Do not make a moderation decision", prompt)


if __name__ == "__main__":
    unittest.main()
