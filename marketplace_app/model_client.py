import json
import logging
import os
from pathlib import Path
from typing import Any
from urllib import error, request

from marketplace_app.extraction import heuristic_extract, validate_extraction

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = PROJECT_ROOT / "config" / "prompts" / "listing_extraction.txt"


def load_extraction_prompt(raw_listing: dict[str, Any]) -> str:
    """Read the editable prompt at request time so prompt changes need no code edit."""
    template = PROMPT_PATH.read_text(encoding="utf-8-sig")
    return template.replace("{listing_json}", json.dumps(raw_listing, ensure_ascii=False, indent=2))


def extract_listing_features(raw_listing: dict[str, Any]) -> dict[str, Any]:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model_name = os.getenv("OLLAMA_MODEL", "llama3.1")
    payload = {
        "model": model_name,
        "format": "json",
        "stream": False,
        "prompt": load_extraction_prompt(raw_listing),
        "options": {"temperature": 0.0},
    }

    try:
        encoded_payload = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{base_url}/api/generate",
            data=encoded_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=10) as response:
            body = json.loads(response.read().decode("utf-8"))
        return validate_extraction(json.loads(body["response"]))
    except (error.URLError, TimeoutError, OSError, ValueError, KeyError, TypeError) as exc:
        logger.warning("Local model extraction unavailable; using heuristic fallback: %s", exc)
        return heuristic_extract(raw_listing)
