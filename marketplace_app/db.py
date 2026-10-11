import json
import sqlite3
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "marketplace_policy.db"
POLICY_BUNDLE_PATH = PROJECT_ROOT / "config" / "policies" / "active.json"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database() -> None:
    conn = get_connection()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS policy_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_name TEXT NOT NULL UNIQUE,
            effective_from TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            effective_to TIMESTAMP NULL,
            created_by TEXT DEFAULT 'ops_admin'
        );

        CREATE TABLE IF NOT EXISTS prohibited_products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            policy_version_id INTEGER NOT NULL,
            normalized_product_type TEXT NOT NULL,
            category TEXT NOT NULL,
            risk_level TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(policy_version_id) REFERENCES policy_versions(id)
        );

        CREATE INDEX IF NOT EXISTS idx_prohibited_type_active
        ON prohibited_products(normalized_product_type, is_active);

        CREATE TABLE IF NOT EXISTS policy_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            policy_version_id INTEGER NOT NULL,
            rule_name TEXT NOT NULL,
            rule_type TEXT NOT NULL,
            condition_json TEXT NOT NULL,
            severity TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(policy_version_id) REFERENCES policy_versions(id)
        );

        CREATE TABLE IF NOT EXISTS listing_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id TEXT NOT NULL UNIQUE,
            vendor_id TEXT NOT NULL,
            raw_payload TEXT NOT NULL,
            extracted_payload TEXT,
            status TEXT NOT NULL DEFAULT 'received',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS moderation_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id TEXT NOT NULL,
            decision TEXT NOT NULL,
            policy_version TEXT NOT NULL,
            matched_rule_ids TEXT,
            reason_codes TEXT,
            review_queue_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(submission_id) REFERENCES listing_submissions(submission_id)
        );

        CREATE TABLE IF NOT EXISTS review_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id TEXT NOT NULL,
            priority TEXT NOT NULL DEFAULT 'normal',
            reviewer_status TEXT NOT NULL DEFAULT 'pending',
            case_note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(submission_id)
        );
        """
    )
    seed_default_policy(conn)
    conn.commit()
    conn.close()


def load_policy_bundle() -> dict[str, Any]:
    """Load and validate the editable policy bundle before importing it into SQLite."""
    bundle = json.loads(POLICY_BUNDLE_PATH.read_text(encoding="utf-8-sig"))
    required = {"version_name", "created_by", "prohibited_products", "rules"}
    if not isinstance(bundle, dict) or not required.issubset(bundle):
        raise ValueError(f"Policy bundle must include: {', '.join(sorted(required))}.")
    if not isinstance(bundle["version_name"], str) or not bundle["version_name"].strip():
        raise ValueError("Policy bundle version_name must be a non-empty string.")
    if not isinstance(bundle["prohibited_products"], list) or not isinstance(bundle["rules"], list):
        raise ValueError("Policy bundle prohibited_products and rules must be arrays.")

    for product in bundle["prohibited_products"]:
        fields = ("normalized_product_type", "category", "risk_level")
        if not isinstance(product, dict) or any(not isinstance(product.get(field), str) for field in fields):
            raise ValueError("Each prohibited_products entry needs normalized_product_type, category, and risk_level strings.")

    supported_rule_types = {"normalized_product_type", "risk_signal"}
    for rule in bundle["rules"]:
        if not isinstance(rule, dict):
            raise ValueError("Each rules entry must be an object.")
        if not all(isinstance(rule.get(field), str) for field in ("rule_name", "rule_type", "severity")):
            raise ValueError("Each rule needs rule_name, rule_type, and severity strings.")
        if rule["rule_type"] not in supported_rule_types:
            raise ValueError(f"Unsupported policy rule_type: {rule['rule_type']}.")
        if not isinstance(rule.get("match"), list) or not all(isinstance(item, str) for item in rule["match"]):
            raise ValueError("Each rule match value must be an array of strings.")
    return bundle

def seed_default_policy(conn: sqlite3.Connection) -> None:
    """Import a policy version once; versions stay immutable after they are seeded."""
    bundle = load_policy_bundle()
    version_name = bundle["version_name"]
    version_row = conn.execute(
        "SELECT id FROM policy_versions WHERE version_name = ?", (version_name,)
    ).fetchone()

    if version_row is None:
        conn.execute(
            "UPDATE policy_versions SET effective_to = CURRENT_TIMESTAMP WHERE effective_to IS NULL"
        )
        cur = conn.execute(
            "INSERT INTO policy_versions (version_name, created_by) VALUES (?, ?)",
            (version_name, bundle["created_by"]),
        )
        policy_version_id = cur.lastrowid
        conn.executemany(
            """INSERT INTO prohibited_products
               (policy_version_id, normalized_product_type, category, risk_level, is_active)
               VALUES (?, ?, ?, ?, 1)""",
            [
                (policy_version_id, item["normalized_product_type"], item["category"], item["risk_level"])
                for item in bundle["prohibited_products"]
            ],
        )
        conn.executemany(
            """INSERT INTO policy_rules
               (policy_version_id, rule_name, rule_type, condition_json, severity, is_active)
               VALUES (?, ?, ?, ?, ?, 1)""",
            [
                (
                    policy_version_id,
                    rule["rule_name"],
                    rule["rule_type"],
                    json.dumps({"match": rule["match"]}),
                    rule["severity"],
                )
                for rule in bundle["rules"]
            ],
        )
    else:
        policy_version_id = version_row["id"]

    conn.execute(
        "UPDATE policy_versions SET effective_to = CURRENT_TIMESTAMP WHERE effective_to IS NULL AND id != ?",
        (policy_version_id,),
    )
    conn.execute(
        "UPDATE policy_versions SET effective_to = NULL WHERE id = ?", (policy_version_id,)
    )

def save_submission(submission_id: str, vendor_id: str, raw_payload: dict[str, Any], extracted_payload: dict[str, Any], status: str) -> None:
    conn = get_connection()
    conn.execute(
        "INSERT INTO listing_submissions (submission_id, vendor_id, raw_payload, extracted_payload, status) VALUES (?, ?, ?, ?, ?)",
        (
            submission_id,
            vendor_id,
            json.dumps(raw_payload, ensure_ascii=False),
            json.dumps(extracted_payload, ensure_ascii=False),
            status,
        ),
    )
    conn.commit()
    conn.close()


def save_decision(submission_id: str, decision: str, policy_version: str, matched_rule_ids: list[int], reason_codes: list[str], review_queue_id: str | None) -> None:
    conn = get_connection()
    conn.execute(
        "INSERT INTO moderation_decisions (submission_id, decision, policy_version, matched_rule_ids, reason_codes, review_queue_id) VALUES (?, ?, ?, ?, ?, ?)",
        (
            submission_id,
            decision,
            policy_version,
            json.dumps(matched_rule_ids),
            json.dumps(reason_codes),
            review_queue_id,
        ),
    )
    conn.commit()
    conn.close()


def upsert_review_queue(submission_id: str, priority: str, case_note: str | None) -> str:
    conn = get_connection()
    existing = conn.execute(
        "SELECT id FROM review_queue WHERE submission_id = ?",
        (submission_id,),
    ).fetchone()
    if existing is not None:
        queue_id = existing["id"]
        conn.execute(
            "UPDATE review_queue SET priority = ?, case_note = ?, updated_at = CURRENT_TIMESTAMP WHERE submission_id = ?",
            (priority, case_note, submission_id),
        )
    else:
        cur = conn.execute(
            "INSERT INTO review_queue (submission_id, priority, reviewer_status, case_note) VALUES (?, ?, 'pending', ?)",
            (submission_id, priority, case_note),
        )
        queue_id = cur.lastrowid
    conn.commit()
    conn.close()
    return str(queue_id)


def list_recent_submissions(limit: int = 10) -> list[dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT submission_id, vendor_id, status, raw_payload, extracted_payload, created_at
        FROM listing_submissions
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def list_decisions(limit: int = 10) -> list[dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT submission_id, decision, policy_version, matched_rule_ids, reason_codes, review_queue_id, created_at
        FROM moderation_decisions
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_active_policy_version() -> str:
    conn = get_connection()
    row = conn.execute(
        "SELECT version_name FROM policy_versions WHERE effective_to IS NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if row is None:
        raise RuntimeError("No active policy version is configured.")
    return str(row["version_name"])


def get_active_prohibited_products() -> list[str]:
    conn = get_connection()
    rows = conn.execute(
        """SELECT p.normalized_product_type FROM prohibited_products p
           JOIN policy_versions v ON v.id = p.policy_version_id
           WHERE p.is_active = 1 AND v.effective_to IS NULL"""
    ).fetchall()
    conn.close()
    return [row["normalized_product_type"] for row in rows]

def get_active_policy_records() -> list[dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT p.id, p.policy_version_id, p.rule_name, p.rule_type, p.condition_json, p.severity
        FROM policy_rules p
        JOIN policy_versions v ON v.id = p.policy_version_id
        WHERE p.is_active = 1 AND v.effective_to IS NULL
        ORDER BY p.id ASC
        """
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_policy_catalog() -> dict[str, Any]:
    conn = get_connection()
    rules = conn.execute(
        """
        SELECT p.id, p.policy_version_id, p.rule_name, p.rule_type, p.condition_json, p.severity, p.is_active
        FROM policy_rules p
        JOIN policy_versions v ON v.id = p.policy_version_id
        WHERE p.is_active = 1 AND v.effective_to IS NULL
        ORDER BY p.id ASC
        """
    ).fetchall()
    prohibited = conn.execute(
        """
        SELECT p.id, p.policy_version_id, p.normalized_product_type, p.category, p.risk_level, p.is_active
        FROM prohibited_products p
        JOIN policy_versions v ON v.id = p.policy_version_id
        WHERE p.is_active = 1 AND v.effective_to IS NULL
        ORDER BY p.id ASC
        """
    ).fetchall()
    conn.close()
    return {
        "rules": [dict(row) for row in rules],
        "prohibited_products": [dict(row) for row in prohibited],
    }







