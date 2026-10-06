"""Fault-tolerant data ingestion pipeline for customer email requests."""

import os
import re
from pathlib import Path
from typing import Any, Dict, List


def parse_email_file(file_path: str) -> Dict[str, Any]:
    """
    Parses an individual email file safely with exception isolation.
    Preserves original request, assigns stable identity, and reports corrupt input.
    """
    filename = os.path.basename(file_path)
    name_parts = os.path.splitext(filename)[0].split("_")
    default_req_id = name_parts[0] if len(name_parts) > 0 else filename
    default_order_ref = name_parts[1] if len(name_parts) > 1 else default_req_id

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.splitlines()
        headers: Dict[str, str] = {}
        body_lines: List[str] = []
        in_headers = True

        for line in lines:
            if in_headers:
                if not line.strip():
                    in_headers = False
                    continue
                if ":" in line:
                    key, val = line.split(":", 1)
                    headers[key.strip().lower()] = val.strip()
                else:
                    in_headers = False
                    body_lines.append(line)
            else:
                body_lines.append(line)

        req_id = headers.get("request-id") or default_req_id
        order_ref = headers.get("order-ref") or default_order_ref
        body = "\n".join(body_lines).strip() or content.strip()

        return {
            "id": req_id,
            "order_ref": order_ref,
            "text": body,
            "filename": filename,
            "source": "email_file",
            "is_corrupt": False,
        }

    except Exception as exc:
        return {
            "id": default_req_id,
            "order_ref": default_order_ref,
            "text": f"CORRUPTED_FILE: {str(exc)}",
            "filename": filename,
            "source": "email_file",
            "is_corrupt": True,
            "error": str(exc),
        }


def load_email_requests_from_dir(dir_path: str = "data/emails") -> List[Dict[str, Any]]:
    """Loads all email request files stably without crashing on bad inputs."""
    resolved_path = Path(dir_path)
    if not resolved_path.is_absolute():
        resolved_path = Path(__file__).resolve().parent.parent / dir_path

    if not resolved_path.exists() or not resolved_path.is_dir():
        return []

    txt_files = sorted(
        [f for f in resolved_path.glob("*.txt") if f.is_file()],
        key=lambda x: int(re.search(r"\d+", x.name).group()) if re.search(r"\d+", x.name) else 999
    )

    return [parse_email_file(str(f)) for f in txt_files]
