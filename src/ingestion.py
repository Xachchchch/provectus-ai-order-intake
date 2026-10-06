"""Data ingestion pipeline for parsing email-style order request files."""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


def parse_email_file(file_path: str) -> Dict[str, Any]:
    """
    Parses an individual email-style text file into structured order request metadata.

    File structure expected:
        Order-Ref: <O1>
        Request-ID: <R1>
        Subject: <Subject text>

        <Raw customer order text body>
    """
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.splitlines()
    headers: Dict[str, str] = {}
    body_lines: List[str] = []
    in_headers = True

    for line in lines:
        if in_headers:
            if not line.strip():
                # First empty line separates headers from body
                in_headers = False
                continue
            if ":" in line:
                key, val = line.split(":", 1)
                headers[key.strip().lower()] = val.strip()
            else:
                # If non-header line before empty line, consider headers finished
                in_headers = False
                body_lines.append(line)
        else:
            body_lines.append(line)

    filename = os.path.basename(file_path)
    # Derive fallbacks if headers are absent
    name_parts = os.path.splitext(filename)[0].split("_")
    default_req_id = name_parts[0] if len(name_parts) > 0 else filename
    default_order_ref = name_parts[1] if len(name_parts) > 1 else default_req_id

    req_id = headers.get("request-id") or default_req_id
    order_ref = headers.get("order-ref") or default_order_ref
    subject = headers.get("subject", "Order Submission")
    body = "\n".join(body_lines).strip()

    return {
        "id": req_id,
        "order_ref": order_ref,
        "subject": subject,
        "text": body,
        "filename": filename,
        "source": "email_file",
    }


def _extract_sort_key(req: Dict[str, Any]) -> int:
    """Helper to sort request IDs numerically (e.g. R1 -> 1, R10 -> 10)."""
    match = re.search(r"\d+", req["id"])
    return int(match.group()) if match else 999999


def load_email_requests_from_dir(dir_path: str = "data/emails") -> List[Dict[str, Any]]:
    """
    Loads all .txt email request files from a directory, extracts headers and body,
    assigns stable identities, and preserves original metadata in deterministic order.
    """
    resolved_path = Path(dir_path)
    if not resolved_path.is_absolute():
        resolved_path = Path(__file__).resolve().parent.parent / dir_path

    if not resolved_path.exists() or not resolved_path.is_dir():
        return []

    txt_files = [f for f in resolved_path.glob("*.txt") if f.is_file()]
    requests: List[Dict[str, Any]] = []

    for file_path in txt_files:
        parsed = parse_email_file(str(file_path))
        requests.append(parsed)

    # Sort stably by request id number (R1, R2, ..., R10)
    requests.sort(key=_extract_sort_key)
    return requests
