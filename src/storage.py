"""SQLite persistence layer (orders.db) storing order state, review history, and clarification drafts."""

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.catalog import get_catalog_item
from src.pricing import calculate_order_pricing

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "orders.db")


def get_db_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Initialize SQLite database tables and apply backward-compatible schema migrations."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    request_id TEXT PRIMARY KEY,
                    order_ref TEXT NOT NULL,
                    raw_text TEXT NOT NULL,
                    status TEXT NOT NULL,
                    line_items_json TEXT NOT NULL,
                    gross_cents INTEGER NOT NULL,
                    discount_cents INTEGER NOT NULL,
                    total_cents INTEGER NOT NULL,
                    notes TEXT,
                    is_cached INTEGER DEFAULT 1,
                    model TEXT DEFAULT 'llama-3.3-70b-versatile',
                    catalog_evidence_json TEXT DEFAULT '[]',
                    exception_code TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            # Schema migration checks if existing DB lacks new columns
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(orders)")
            cols = [row["name"] for row in cursor.fetchall()]
            if "catalog_evidence_json" not in cols:
                conn.execute("ALTER TABLE orders ADD COLUMN catalog_evidence_json TEXT DEFAULT '[]'")
            if "exception_code" not in cols:
                conn.execute("ALTER TABLE orders ADD COLUMN exception_code TEXT DEFAULT ''")

            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_orders_order_ref ON orders (order_ref)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS clarification_drafts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    order_ref TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    draft_email TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS review_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_ref TEXT NOT NULL,
                    action TEXT NOT NULL,
                    previous_state TEXT,
                    new_state TEXT,
                    reviewer TEXT NOT NULL,
                    comment TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
    finally:
        conn.close()


def _deserialize_order_row(r: sqlite3.Row) -> Dict[str, Any]:
    """Helper to convert sqlite row to rich order dict with deserialized JSON."""
    d = dict(r)
    d["line_items"] = json.loads(d.get("line_items_json") or "[]")
    d["is_cached"] = bool(d.get("is_cached", 1))
    try:
        d["catalog_evidence"] = json.loads(d.get("catalog_evidence_json") or "[]")
    except Exception:
        d["catalog_evidence"] = []
    d["exception_code"] = d.get("exception_code") or ""
    return d


def save_order(order_data: Dict[str, Any], db_path: str = DEFAULT_DB_PATH) -> None:
    """
    Insert or update order in SQLite database keyed by request_id.
    Guarantees immutability of created_at on conflict / update.
    """
    init_db(db_path)
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection(db_path)

    # Serialize catalog evidence
    catalog_evidence = order_data.get("catalog_evidence", [])
    if isinstance(catalog_evidence, (list, dict)):
        catalog_evidence_json = json.dumps(catalog_evidence)
    else:
        catalog_evidence_json = str(catalog_evidence)

    exception_code = order_data.get("exception_code", "")

    try:
        with conn:
            conn.execute(
                """
                INSERT INTO orders (
                    request_id, order_ref, raw_text, status,
                    line_items_json, gross_cents, discount_cents, total_cents,
                    notes, is_cached, model, catalog_evidence_json, exception_code,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(request_id) DO UPDATE SET
                    order_ref=excluded.order_ref,
                    raw_text=excluded.raw_text,
                    status=excluded.status,
                    line_items_json=excluded.line_items_json,
                    gross_cents=excluded.gross_cents,
                    discount_cents=excluded.discount_cents,
                    total_cents=excluded.total_cents,
                    notes=excluded.notes,
                    is_cached=excluded.is_cached,
                    model=excluded.model,
                    catalog_evidence_json=excluded.catalog_evidence_json,
                    exception_code=excluded.exception_code,
                    updated_at=excluded.updated_at
                """,
                (
                    order_data["request_id"],
                    order_data["order_ref"],
                    order_data["raw_text"],
                    order_data["status"],
                    json.dumps(order_data.get("line_items", [])),
                    order_data.get("gross_cents", 0),
                    order_data.get("discount_cents", 0),
                    order_data.get("total_cents", 0),
                    order_data.get("notes", ""),
                    1 if order_data.get("is_cached", True) else 0,
                    order_data.get("model", "llama-3.3-70b-versatile"),
                    catalog_evidence_json,
                    exception_code,
                    order_data.get("created_at", now),
                    now,
                ),
            )
    finally:
        conn.close()


def get_order(order_ref: str, db_path: str = DEFAULT_DB_PATH) -> Optional[Dict[str, Any]]:
    """
    Retrieve active primary order by order_ref.
    Prefers non-duplicate orders (draft, reviewed, needs-clarification).
    """
    init_db(db_path)
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM orders 
            WHERE order_ref = ? AND status != 'duplicate' 
            ORDER BY created_at ASC LIMIT 1
            """,
            (order_ref,),
        )
        row = cursor.fetchone()
        if not row:
            # Fallback if only duplicate exists
            cursor.execute("SELECT * FROM orders WHERE order_ref = ? LIMIT 1", (order_ref,))
            row = cursor.fetchone()
        if not row:
            return None
        return _deserialize_order_row(row)
    finally:
        conn.close()


def get_order_by_request_id(request_id: str, db_path: str = DEFAULT_DB_PATH) -> Optional[Dict[str, Any]]:
    """Retrieve order strictly by request_id."""
    init_db(db_path)
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders WHERE request_id = ?", (request_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return _deserialize_order_row(row)
    finally:
        conn.close()


def list_orders(status_filter: Optional[str] = None, db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """List all orders, optionally filtered by status."""
    init_db(db_path)
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        if status_filter and status_filter.lower() != "all":
            cursor.execute("SELECT * FROM orders WHERE status = ? ORDER BY created_at ASC", (status_filter,))
        else:
            cursor.execute("SELECT * FROM orders ORDER BY created_at ASC")
        rows = cursor.fetchall()
        return [_deserialize_order_row(r) for r in rows]
    finally:
        conn.close()


def get_orders_metrics(db_path: str = DEFAULT_DB_PATH) -> Dict[str, int]:
    """
    Computes order counts distinguishing net valid orders from blocked duplicates.
    Total Orders Ingested = count of orders where status != 'duplicate'.
    Duplicate Submissions Blocked = count of orders where status == 'duplicate'.
    """
    orders = list_orders(db_path=db_path)
    total_raw = len(orders)
    net_valid = sum(1 for o in orders if o["status"] != "duplicate")
    duplicates = sum(1 for o in orders if o["status"] == "duplicate")
    drafts = sum(1 for o in orders if o["status"] == "draft")
    reviewed = sum(1 for o in orders if o["status"] == "reviewed")
    clarifications = sum(1 for o in orders if o["status"] == "needs-clarification")
    failed = sum(1 for o in orders if o["status"] == "failed")
    return {
        "total_raw": total_raw,
        "net_valid": net_valid,
        "duplicates": duplicates,
        "drafts": drafts,
        "reviewed": reviewed,
        "clarifications": clarifications,
        "failed": failed,
    }


def save_clarification_draft(draft: Dict[str, Any], db_path: str = DEFAULT_DB_PATH) -> int:
    """Save an automated inquiry email draft into database."""
    init_db(db_path)
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection(db_path)
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO clarification_drafts (
                    request_id, order_ref, subject, draft_email, reason, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    draft["request_id"],
                    draft["order_ref"],
                    draft["subject"],
                    draft["draft_email"],
                    draft["reason"],
                    now,
                ),
            )
            return cursor.lastrowid
    finally:
        conn.close()


def get_clarification_draft(order_ref: str, db_path: str = DEFAULT_DB_PATH) -> Optional[Dict[str, Any]]:
    """Get the latest clarification draft for an order."""
    init_db(db_path)
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM clarification_drafts WHERE order_ref = ? ORDER BY id DESC LIMIT 1",
            (order_ref,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def record_review_action(
    order_ref: str,
    action: str,
    previous_state: str,
    new_state: str,
    reviewer: str,
    comment: str = "",
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    """Record an audit trail event in review_history."""
    init_db(db_path)
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO review_history (
                    order_ref, action, previous_state, new_state, reviewer, comment, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (order_ref, action, previous_state, new_state, reviewer, comment, now),
            )
    finally:
        conn.close()


def get_review_history(order_ref: Optional[str] = None, db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """Retrieve audit trail of review actions."""
    init_db(db_path)
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        if order_ref:
            cursor.execute(
                "SELECT * FROM review_history WHERE order_ref = ? ORDER BY id ASC",
                (order_ref,),
            )
        else:
            cursor.execute("SELECT * FROM review_history ORDER BY id ASC")
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def apply_manual_correction(
    order_ref: str,
    corrected_items: List[Dict[str, Any]],
    reviewer: str = "human_reviewer",
    comment: str = "Manual reviewer correction",
    db_path: str = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """
    Applies a reviewer manual correction to an existing order:
    1. Re-prices items deterministically using catalog unit prices and bulk discount rules across all lines.
    2. Updates status to 'reviewed' (strictly distinguishing a human-reviewed order from an unreviewed draft).
    3. Records the event in review_history with previous and new states.
    4. Persists changes to SQLite while preserving original created_at.
    """
    current_order = get_order(order_ref, db_path=db_path)
    if not current_order:
        raise ValueError(f"Order {order_ref} not found")

    prepared_lines = []
    catalog_evidence = []
    for item in corrected_items:
        sku = item["sku"].strip().upper()
        cat_item = get_catalog_item(sku)
        if not cat_item:
            raise ValueError(f"Cannot apply correction: SKU '{sku}' not in catalog")
        quantity = int(item["quantity"])
        prepared_lines.append(
            {
                "sku": cat_item.sku,
                "name": cat_item.name,
                "unit_cents": cat_item.unit_cents,
                "quantity": quantity,
            }
        )
        catalog_evidence.append(
            {
                "query": sku,
                "sku": cat_item.sku,
                "name": cat_item.name,
                "unit_cents": cat_item.unit_cents,
                "match_rule": "manual_review",
                "evidence": f"Operator confirmed catalog item {cat_item.sku} ({cat_item.name}, ${cat_item.unit_cents / 100:.2f})",
            }
        )

    pricing_result = calculate_order_pricing(prepared_lines)

    previous_state = json.dumps(
        {
            "status": current_order["status"],
            "line_items": current_order["line_items"],
            "total_cents": current_order["total_cents"],
        }
    )

    new_order_data = {
        "request_id": current_order["request_id"],
        "order_ref": current_order["order_ref"],
        "raw_text": current_order["raw_text"],
        "status": "reviewed",  # Strictly distinguished from unreviewed 'draft'
        "line_items": pricing_result["line_items"],
        "gross_cents": pricing_result["gross_cents"],
        "discount_cents": pricing_result["discount_cents"],
        "total_cents": pricing_result["total_cents"],
        "notes": f"Reviewed & corrected by {reviewer}: {comment}",
        "is_cached": current_order.get("is_cached", True),
        "model": current_order.get("model", "llama-3.3-70b-versatile"),
        "catalog_evidence": catalog_evidence,
        "exception_code": "CLEAN_DRAFT",
        "created_at": current_order["created_at"],
    }

    save_order(new_order_data, db_path=db_path)

    new_state = json.dumps(
        {
            "status": "reviewed",
            "line_items": pricing_result["line_items"],
            "total_cents": pricing_result["total_cents"],
        }
    )

    record_review_action(
        order_ref=order_ref,
        action="manual_correction",
        previous_state=previous_state,
        new_state=new_state,
        reviewer=reviewer,
        comment=comment,
        db_path=db_path,
    )

    return get_order(order_ref, db_path=db_path)
