import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from marketplace_app import db


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PolicyVersionImportTests(unittest.TestCase):
    def test_new_bundle_becomes_active_without_deleting_old_version(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            database_path = temporary_path / "test-policy.db"
            policy_path = temporary_path / "active.json"
            policy_path.write_text(
                (PROJECT_ROOT / "config" / "policies" / "active.json").read_text(encoding="utf-8-sig"),
                encoding="utf-8",
            )

            with patch.object(db, "DB_PATH", database_path), patch.object(
                db, "POLICY_BUNDLE_PATH", policy_path
            ):
                db.initialize_database()
                self.assertEqual(db.get_active_policy_version(), "v1")

                policy_path.write_text(
                    json.dumps(
                        {
                            "version_name": "v2",
                            "created_by": "test",
                            "prohibited_products": [
                                {
                                    "normalized_product_type": "test_item",
                                    "category": "test",
                                    "risk_level": "high",
                                }
                            ],
                            "rules": [
                                {
                                    "rule_name": "test_rule",
                                    "rule_type": "normalized_product_type",
                                    "match": ["test_item"],
                                    "severity": "high",
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                db.initialize_database()

                self.assertEqual(db.get_active_policy_version(), "v2")
                self.assertEqual(
                    [row["rule_name"] for row in db.get_active_policy_records()],
                    ["test_rule"],
                )
                self.assertEqual(db.get_active_prohibited_products(), ["test_item"])
                conn = db.get_connection()
                version_count = conn.execute("SELECT COUNT(*) FROM policy_versions").fetchone()[0]
                conn.close()
                self.assertEqual(version_count, 2)


if __name__ == "__main__":
    unittest.main()
