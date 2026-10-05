"""Reference cases and domain verification tests for AI Order Intake & Exception Handling Platform.

Implements the 5 required checks from the brief:
- Check 1: Normal request & bulk discount calculation.
- Check 2: Unknown product flagged with clarification draft.
- Check 3: Ambiguous quantity ('box'/'pack') flagged, not guessed.
- Check 4: Duplicate request blocked without new draft creation.
- Check 5: Reviewer correction updates record to 'reviewed', reruns pricing, and persists across restarts.
"""

import json
import os
from pathlib import Path
import sqlite3
import sys

# Ensure workspace root is in sys.path
WORKSPACE_ROOT = str(Path(__file__).resolve().parent.parent)
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

import pytest
from pydantic import ValidationError

from src.catalog import CATALOG, MatchStatus, get_catalog_item, match_catalog_item
from src.engine import apply_reviewer_correction, process_request
from src.extractor import ExtractedOrderItem, ExtractionPayload
from src.pricing import calculate_line_price, calculate_order_pricing
from src.storage import (
    get_clarification_draft,
    get_order,
    get_order_by_request_id,
    get_review_history,
    init_db,
    list_orders,
)


@pytest.fixture
def test_db(tmp_path):
    """Provides a fresh isolated SQLite database file for testing."""
    db_file = str(tmp_path / "test_orders.db")
    init_db(db_file)
    return db_file


@pytest.fixture
def requests_data():
    """Load requests from data/requests.json."""
    data_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "requests.json")
    with open(data_path, "r", encoding="utf-8") as f:
        return json.load(f)["requests"]


@pytest.fixture
def expected_results_data():
    """Load expected results from data/expected_results.json."""
    data_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "expected_results.json")
    with open(data_path, "r", encoding="utf-8") as f:
        return {item["id"]: item for item in json.load(f)}


# =========================================================================
# CHECK 1: Normal request & bulk discount calculation
# =========================================================================
class TestCheck1NormalAndBulkDiscount:
    def test_normal_order_r1(self, test_db):
        """R1: 2 individual CAB-1 cables at 2000 cents = 4000 cents total (no discount)."""
        req = {
            "id": "R1",
            "order_ref": "O1",
            "text": "Please send 2 individual CAB-1 cables.",
        }
        result = process_request(req, force_replay=True, db_path=test_db)

        assert result["outcome"] == "draft"
        assert result["sku"] == "CAB-1"
        assert result["quantity"] == 2
        assert result["total_cents"] == 4000
        assert result["discount_cents"] == 0

        # Verify DB storage
        stored = get_order("O1", db_path=test_db)
        assert stored is not None
        assert stored["status"] == "draft"
        assert stored["total_cents"] == 4000

    def test_bulk_discount_r5(self, test_db):
        """R5: 10 units of USB-C cable 1 m (CAB-1). 10% discount applies (qty >= 10)."""
        req = {
            "id": "R5",
            "order_ref": "O5",
            "text": "Order 10 units of USB-C cable 1 m.",
        }
        result = process_request(req, force_replay=True, db_path=test_db)

        assert result["outcome"] == "draft"
        assert result["sku"] == "CAB-1"
        assert result["quantity"] == 10
        assert result["gross_cents"] == 20000
        assert result["discount_cents"] == 2000  # 10% of 20000
        assert result["total_cents"] == 18000

    def test_bulk_discount_multi_line_r6(self, test_db):
        """R6: 12 units of CAB-2 (discounted) + 1 unit of HUB-1 (no discount)."""
        req = {
            "id": "R6",
            "order_ref": "O6",
            "text": "Need 12 units of CAB-2 and 1 unit of HUB-1.",
        }
        result = process_request(req, force_replay=True, db_path=test_db)

        assert result["outcome"] == "draft"
        assert len(result["line_items"]) == 2

        cab2_line = next(l for l in result["line_items"] if l["sku"] == "CAB-2")
        assert cab2_line["quantity"] == 12
        assert cab2_line["gross_cents"] == 36000
        assert cab2_line["discount_cents"] == 3600
        assert cab2_line["total_cents"] == 32400

        hub1_line = next(l for l in result["line_items"] if l["sku"] == "HUB-1")
        assert hub1_line["quantity"] == 1
        assert hub1_line["gross_cents"] == 5000
        assert hub1_line["discount_cents"] == 0
        assert hub1_line["total_cents"] == 5000

        assert result["total_cents"] == 37400

    def test_round_half_up_rule(self):
        """Verify strict Decimal ROUND_HALF_UP on half cents."""
        # 15 items at 135 cents each = 2025 cents gross.
        # 10% discount = 202.5 cents -> ROUND_HALF_UP gives 203 cents discount.
        res = calculate_line_price(unit_cents=135, quantity=15)
        assert res["gross_cents"] == 2025
        assert res["discount_cents"] == 203
        assert res["total_cents"] == 1822


# =========================================================================
# CHECK 2: Unknown product flagged with clarification draft
# =========================================================================
class TestCheck2UnknownProduct:
    def test_unknown_product_r2(self, test_db):
        """R2: 'Moon adapter' is not in catalog -> needs-clarification with email draft."""
        req = {
            "id": "R2",
            "order_ref": "O2",
            "text": "Please send one Moon adapter.",
        }
        result = process_request(req, force_replay=True, db_path=test_db)

        assert result["outcome"] == "needs-clarification"
        assert "unknown product" in result["reason"].lower()

        # Check automated inquiry email draft in storage
        draft = get_clarification_draft("O2", db_path=test_db)
        assert draft is not None
        assert "Clarification needed for Order Ref #O2" in draft["subject"]
        assert "Moon adapter" in draft["draft_email"]
        assert "CAB-1" in draft["draft_email"]  # Mentions official catalog options

        # Verify DB status
        stored = get_order("O2", db_path=test_db)
        assert stored["status"] == "needs-clarification"
        assert stored["total_cents"] == 0


# =========================================================================
# CHECK 3: Ambiguous quantity ('box'/'pack') flagged, not guessed
# =========================================================================
class TestCheck3AmbiguousQuantity:
    def test_box_quantity_r3(self, test_db):
        """R3: 'Send two boxes of the usual cable.' Must NOT guess box unit counts."""
        req = {
            "id": "R3",
            "order_ref": "O3",
            "text": "Send two boxes of the usual cable.",
        }
        result = process_request(req, force_replay=True, db_path=test_db)

        assert result["outcome"] == "needs-clarification"
        assert "box" in result["reason"].lower() or "ambiguous" in result["reason"].lower()

        # Verify quantity was not inferred as arbitrary number
        stored = get_order("O3", db_path=test_db)
        assert stored["status"] == "needs-clarification"
        assert stored["line_items"] == []

    def test_pack_quantity_r7(self, test_db):
        """R7: 'Please supply a pack of USB hub.' Must flag 'pack' as ambiguous quantity."""
        req = {
            "id": "R7",
            "order_ref": "O7",
            "text": "Please supply a pack of USB hub.",
        }
        result = process_request(req, force_replay=True, db_path=test_db)

        assert result["outcome"] == "needs-clarification"
        assert "pack" in result["reason"].lower()

    def test_box_quantity_known_sku_r9(self, test_db):
        """R9: 'Ship 3 boxes of CAB-1...' Even with known SKU, 'box' must NOT be converted."""
        req = {
            "id": "R9",
            "order_ref": "O9",
            "text": "Ship 3 boxes of CAB-1 to our warehouse.",
        }
        result = process_request(req, force_replay=True, db_path=test_db)

        assert result["outcome"] == "needs-clarification"
        assert "box" in result["reason"].lower()


# =========================================================================
# CHECK 4: Duplicate request blocked without new draft creation
# =========================================================================
class TestCheck4DuplicatePrevention:
    def test_duplicate_order_ref_blocked(self, test_db):
        """R1 and R4 share order_ref 'O1'. Processing R4 must block and NOT create duplicate draft."""
        req1 = {
            "id": "R1",
            "order_ref": "O1",
            "text": "Please send 2 individual CAB-1 cables.",
        }
        res1 = process_request(req1, force_replay=True, db_path=test_db)
        assert res1["outcome"] == "draft"

        # Initially 1 draft in database
        orders_before = list_orders(db_path=test_db)
        assert len(orders_before) == 1
        assert orders_before[0]["status"] == "draft"

        req4 = {
            "id": "R4",
            "order_ref": "O1",
            "text": "Please send 2 individual CAB-1 cables.",
        }
        res4 = process_request(req4, force_replay=True, db_path=test_db)

        assert res4["outcome"] == "duplicate"
        assert res4["same_order_as"] == "R1"
        assert res4["new_drafts"] == 0

        # Verify drafts count did NOT inflate (still exactly 1 draft)
        all_orders = list_orders(db_path=test_db)
        drafts = [o for o in all_orders if o["status"] == "draft"]
        duplicates = [o for o in all_orders if o["status"] == "duplicate"]

        assert len(drafts) == 1, "Duplicate must NOT create a secondary draft!"
        assert len(duplicates) == 1, "Duplicate must be recorded for visibility in operations queue!"
        assert duplicates[0]["request_id"] == "R4"


# =========================================================================
# CHECK 5: Reviewer correction sets status to 'reviewed', reruns pricing & persists
# =========================================================================
class TestCheck5ReviewerCorrection:
    def test_reviewer_correction_and_persistence(self, test_db):
        """
        R10 has unknown product 'Solar connectors'.
        Reviewer manually corrects to HUB-1 (qty 15).
        Status must update to 'reviewed' (distinguishing it from an unreviewed draft).
        """
        # Step 1: Initial submission is flagged
        req10 = {
            "id": "R10",
            "order_ref": "O10",
            "text": "Please send 15 Solar connectors.",
        }
        res10 = process_request(req10, force_replay=True, db_path=test_db)
        assert res10["outcome"] == "needs-clarification"

        # Step 2: Apply manual reviewer correction
        corrected_items = [{"sku": "HUB-1", "quantity": 15}]
        updated_order = apply_reviewer_correction(
            order_ref="O10",
            corrected_items=corrected_items,
            reviewer="sarah_ops",
            comment="Customer confirmed over phone they meant USB hub HUB-1",
            db_path=test_db,
        )

        # Status must be 'reviewed'
        assert updated_order["status"] == "reviewed"
        # 15 * 5000 cents = 75000 gross. 10% bulk discount (qty >= 10) = 7500 -> net 67500
        assert updated_order["gross_cents"] == 75000
        assert updated_order["discount_cents"] == 7500
        assert updated_order["total_cents"] == 67500
        assert len(updated_order["line_items"]) == 1
        assert updated_order["line_items"][0]["sku"] == "HUB-1"

        # Step 3: Verify audit trail
        history = get_review_history("O10", db_path=test_db)
        assert len(history) == 1
        assert history[0]["reviewer"] == "sarah_ops"
        assert "manual_correction" in history[0]["action"]

        # Step 4: Simulate restart - open new raw connection directly
        fresh_conn = sqlite3.connect(test_db)
        fresh_conn.row_factory = sqlite3.Row
        cur = fresh_conn.cursor()
        cur.execute("SELECT status, total_cents, discount_cents FROM orders WHERE order_ref = 'O10'")
        row = cur.fetchone()
        fresh_conn.close()

        assert row is not None
        assert row["status"] == "reviewed"
        assert row["total_cents"] == 67500
        assert row["discount_cents"] == 7500


# =========================================================================
# PYDANTIC SCHEMA VALIDATION TESTS
# =========================================================================
def test_pydantic_schema_validation():
    """Verify that ExtractedOrderItem and ExtractionPayload enforce valid schema."""
    valid_payload = {
        "request_id": "R1",
        "order_ref": "O1",
        "raw_text": "2 cables",
        "items": [
            {
                "raw_product_text": "cables",
                "raw_quantity_text": "2",
                "extracted_sku": "CAB-1",
                "extracted_quantity": 2,
                "is_quantity_ambiguous": False,
            }
        ],
        "confidence": 0.95,
        "is_cached": True,
        "model": "llama-3.3-70b-versatile",
    }
    validated = ExtractionPayload.model_validate(valid_payload)
    assert validated.request_id == "R1"
    assert validated.items[0].extracted_quantity == 2

    # Invalid payload missing required fields
    with pytest.raises(ValidationError):
        ExtractionPayload.model_validate({"request_id": "R1"})


# =========================================================================
# COMPREHENSIVE SUITE: All 10 Seed Cases Match Expectations
# =========================================================================
def test_all_10_requests_end_to_end(test_db, requests_data, expected_results_data):
    """Processes R1 through R10 sequentially and asserts matching behavior."""
    for req in requests_data:
        req_id = req["id"]
        exp = expected_results_data[req_id]

        res = process_request(req, force_replay=True, db_path=test_db)
        assert res["outcome"] == exp["outcome"], f"Mismatch on {req_id}: expected {exp['outcome']}, got {res['outcome']}"

        if exp["outcome"] == "draft":
            assert res["total_cents"] == exp["total_cents"]
            if "discount_cents" in exp:
                assert res["discount_cents"] == exp["discount_cents"]

        elif exp["outcome"] == "duplicate":
            assert res["new_drafts"] == 0
            assert res["same_order_as"] == exp["same_order_as"]

        elif exp["outcome"] == "needs-clarification":
            assert "draft_email" in res


# =========================================================================
# ADDITIONAL VERIFICATIONS: Idempotency & Explicit Failure
# =========================================================================

def test_reprocessing_idempotency_does_not_overwrite_reviewed(test_db):
    """Verifies that re-ingesting requests does not overwrite a human reviewer's work."""
    # Step 1: Ingest R10 (initially needs clarification)
    r10 = {"id": "R10", "order_ref": "O10", "text": "Please send 15 Solar connectors."}
    process_request(r10, force_replay=True, db_path=test_db)

    # Step 2: Reviewer resolves it to HUB-1
    apply_reviewer_correction("O10", [{"sku": "HUB-1", "quantity": 15}], reviewer="ops_lead", db_path=test_db)
    order_before = get_order("O10", db_path=test_db)
    assert order_before["status"] == "reviewed"

    # Step 3: Re-ingest R10
    reingest_res = process_request(r10, force_replay=True, db_path=test_db)
    assert reingest_res["outcome"] == "reviewed"
    assert reingest_res["new_drafts"] == 0

    # Verify status is STILL 'reviewed' and total_cents remained 67500
    order_after = get_order("O10", db_path=test_db)
    assert order_after["status"] == "reviewed"
    assert order_after["total_cents"] == 67500


def test_failed_extraction_path_emits_failed_status(test_db, monkeypatch):
    """Verifies that an unhandled LLM failure creates an explicit 'failed' status, not silent fallback."""
    from src import engine

    def mock_broken_extractor(*args, **kwargs):
        return {
            "request_id": "ERR_1",
            "order_ref": "O_ERR",
            "raw_text": "broken",
            "status": "failed",
            "error_message": "Simulated upstream 500 API Gateway Timeout",
            "is_cached": False,
            "model": "simulated_error",
        }

    monkeypatch.setattr(engine, "extract_order_information", mock_broken_extractor)

    bad_req = {"id": "ERR_1", "order_ref": "O_ERR", "text": "broken text"}
    result = engine.process_request(bad_req, force_replay=True, db_path=test_db)

    assert result["outcome"] == "failed"
    stored = get_order("O_ERR", db_path=test_db)
    assert stored["status"] == "failed"
    assert "Simulated upstream 500" in stored["notes"]

