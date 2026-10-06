"""Core processing engine for AI Order Intake & Exception Handling."""

from enum import Enum
import os
import re
from typing import Any, Dict, List, Optional

from src.catalog import CATALOG, MatchStatus, get_catalog_item, lookup_catalog_tool, match_catalog_item
from src.extractor import ExtractionError, extract_order_information
from src.pricing import calculate_order_pricing
from src.storage import (
    DEFAULT_DB_PATH,
    apply_manual_correction,
    get_clarification_draft,
    get_order,
    get_order_by_request_id,
    list_orders,
    save_clarification_draft,
    save_order,
    get_orders_by_order_ref
)


class ExceptionCode(str, Enum):
    """Structured, queryable exception codes for database persistence and analytics."""
    CLEAN_DRAFT = "CLEAN_DRAFT"
    AMBIGUOUS_CONTAINER_QUANTITY = "AMBIGUOUS_CONTAINER_QUANTITY"
    UNKNOWN_CATALOG_PRODUCT = "UNKNOWN_CATALOG_PRODUCT"
    AMBIGUOUS_PRODUCT_DESCRIPTION = "AMBIGUOUS_PRODUCT_DESCRIPTION"
    DUPLICATE_ORDER_REF = "DUPLICATE_ORDER_REF"
    AMENDED_ORDER_REF_CONFLICT = "AMENDED_ORDER_REF_CONFLICT"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
}


def _quantity_supported(qty: int, raw_quantity_text: Optional[str]) -> bool:
    """True only if the customer's own quantity wording contains the number the model extracted."""
    text = (raw_quantity_text or "").lower()
    if re.search(rf"(?<![\d.]){qty}(?!\d|\.\d)", text):
        return True
    return any(v == qty and re.search(rf"\b{w}\b", text) for w, v in _NUMBER_WORDS.items())

def generate_clarification_email(
    request_id: str,
    order_ref: str,
    issues: List[Dict[str, Any]],
) -> Dict[str, str]:
    """Generate an automated customer inquiry email draft for flagged orders."""
    subject = f"Action Required: Clarification needed for Order Ref #{order_ref}"

    bullet_points = []
    for issue in issues:
        reason = issue.get("reason", "Clarification needed")
        product = issue.get("product", "item")
        qty = issue.get("quantity")

        if "amended" in reason.lower() or "conflict" in reason.lower():
            bullet_points.append(
                f"- Order Revision Conflict: An earlier submission exists for Order Ref #{order_ref}. "
                f"Your latest message contains modified details. Please confirm the authoritative item list and quantities."
            )
        elif "unknown product" in reason.lower():
            bullet_points.append(
                f"- Unknown product '{product}': Our catalog currently offers:\n"
                f"    * CAB-1: USB-C cable 1 m ($20.00)\n"
                f"    * CAB-2: USB-C cable 2 m ($30.00)\n"
                f"    * HUB-1: USB hub ($50.00)\n"
                f"  Please confirm if you would like one of these items or a different specification."
            )
        elif "box" in reason.lower() or "pack" in reason.lower() or "ambiguous quantity" in reason.lower() or "container" in reason.lower():
            bullet_points.append(
                f"- Ambiguous quantity '{qty}' for '{product}': As per company intake rules, we do not "
                f"infer packaging or box counts. Please specify the exact positive whole number of individual units."
            )
        elif "multiple items" in reason.lower() or "ambiguous product" in reason.lower():
            bullet_points.append(
                f"- Ambiguous product '{product}': This matches multiple catalog items (e.g. CAB-1 for 1 m vs CAB-2 for 2 m). "
                f"Please specify the desired cable length or SKU."
            )
        else:
            bullet_points.append(f"- Item '{product}': {reason}")

    issues_text = "\n\n".join(bullet_points)

    body = f"""Dear Customer,

Thank you for your order submission (Ref: {order_ref}).

Before we can finalize your order into a confirmed draft, we kindly require clarification regarding the following item(s):

{issues_text}

Please reply directly to this email with your preferred specifications and unit counts, and our fulfillment team will immediately update your order.

Best regards,
Order Operations Team
Customer Intake & Fulfillment
"""
    combined_reason = "; ".join(issue.get("reason", "") for issue in issues)

    return {
        "request_id": request_id,
        "order_ref": order_ref,
        "subject": subject,
        "draft_email": body.strip(),
        "reason": combined_reason,
    }


def process_request(
    request: Dict[str, Any],
    force_replay: bool = True,
    db_path: str = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """
    Process a single order request through the end-to-end pipeline.
    Maintains idempotency, duplicate blocking, amendment detection, and explicit catalog evidence.
    """
    request_id = request["id"]
    order_ref = request["order_ref"]
    text = request["text"]

    # 0. Idempotency Guard: If this request_id was already processed, preserve existing state
    existing_by_req_id = get_order_by_request_id(request_id, db_path=db_path)
    if existing_by_req_id and existing_by_req_id["status"] != "failed":
        return {
            "id": request_id,
            "order_ref": order_ref,
            "outcome": existing_by_req_id["status"],
            "current_status": existing_by_req_id["status"],
            "total_cents": existing_by_req_id["total_cents"],
            "new_drafts": 0,
            "exception_code": existing_by_req_id.get("exception_code", ""),
            "catalog_evidence": existing_by_req_id.get("catalog_evidence", []),
            "message": f"Request {request_id} already processed with status '{existing_by_req_id['status']}'.",
        }

   # Check for unreadable/corrupt input files
    if request.get("is_corrupt"):
        err = request.get("error", "unreadable input file")
        save_order(
            {
                "request_id": request_id,
                "order_ref": order_ref,
                "raw_text": text,
                "status": "failed",
                "line_items": [],
                "gross_cents": 0,
                "discount_cents": 0,
                "total_cents": 0,
                "notes": f"Unusable input: {err}",
                "is_cached": False,
                "model": "none",
                "catalog_evidence": [],
                "exception_code": ExceptionCode.EXTRACTION_FAILED.value,
            },
            db_path=db_path,
        )
        return {
            "id": request_id,
            "order_ref": order_ref,
            "outcome": "failed",
            "reason": f"Unusable input: {err}",
            "exception_code": ExceptionCode.EXTRACTION_FAILED.value,
        }


    # 1. Deduplication & Amendment Reprocessing Check (Domain Rule 4)
    existing_order = get_order(order_ref, db_path=db_path)
    if existing_order and existing_order["request_id"] != request_id:
        is_identical = (text.strip() == existing_order["raw_text"].strip())

        if is_identical:
            # Identical submission -> True Duplicate (status='duplicate')
            dup_data = {
                "request_id": request_id,
                "order_ref": order_ref,
                "raw_text": text,
                "status": "duplicate",
                "line_items": [],
                "gross_cents": 0,
                "discount_cents": 0,
                "total_cents": 0,
                "notes": f"Duplicate submission of request {existing_order['request_id']} (order_ref '{order_ref}').",
                "is_cached": True,
                "model": "system_dedup",
                "catalog_evidence": [],
                "exception_code": ExceptionCode.DUPLICATE_ORDER_REF.value,
            }
            save_order(dup_data, db_path=db_path)
            return {
                "id": request_id,
                "order_ref": order_ref,
                "outcome": "duplicate",
                "same_order_as": existing_order["request_id"],
                "new_drafts": 0,
                "exception_code": ExceptionCode.DUPLICATE_ORDER_REF.value,
                "message": f"Duplicate request for order_ref '{order_ref}'; identical to '{existing_order['request_id']}'.",
            }
        else:
            # Modified text under same order_ref -> Conflicting Amendment (status='needs-clarification')
            conflict_issue = {
                "reason": "Amended order request conflicting with existing submission under identical order_ref",
                "product": "conflicting_amendment",
                "quantity": None,
            }
            draft_info = generate_clarification_email(request_id, order_ref, [conflict_issue])
            save_clarification_draft(draft_info, db_path=db_path)

            conflict_data = {
                "request_id": request_id,
                "order_ref": order_ref,
                "raw_text": text,
                "status": "needs-clarification",
                "line_items": [],
                "gross_cents": 0,
                "discount_cents": 0,
                "total_cents": 0,
                "notes": f"Customer submitted an amended request with conflicting text under existing order_ref '{order_ref}'. Manual review required.",
                "is_cached": True,
                "model": "system_amendment",
                "catalog_evidence": [],
                "exception_code": ExceptionCode.AMENDED_ORDER_REF_CONFLICT.value,
            }
            save_order(conflict_data, db_path=db_path)
            return {
                "id": request_id,
                "order_ref": order_ref,
                "outcome": "needs-clarification",
                "reason": "Amended order request conflicting with existing submission",
                "draft_email": draft_info["draft_email"],
                "exception_code": ExceptionCode.AMENDED_ORDER_REF_CONFLICT.value,
                "new_drafts": 0,
            }
    # 2. Information Extraction
    try:
        extracted = extract_order_information(
            request_id=request_id,
            order_ref=order_ref,
            text=text,
            force_replay=force_replay,
        )
    except ExtractionError as exc:
        # No cache and no API key - explicit failure, no silent regex fallback
        err_msg = str(exc)
        order_data = {
            "request_id": request_id,
            "order_ref": order_ref,
            "raw_text": text,
            "status": "failed",
            "line_items": [],
            "gross_cents": 0,
            "discount_cents": 0,
            "total_cents": 0,
            "notes": f"Extraction failed: {err_msg}",
            "is_cached": False,
            "model": "none",
            "catalog_evidence": [],
            "exception_code": ExceptionCode.EXTRACTION_FAILED.value,
        }
        save_order(order_data, db_path=db_path)
        return {
            "id": request_id,
            "order_ref": order_ref,
            "outcome": "failed",
            "reason": err_msg,
            "error": err_msg,
            "exception_code": ExceptionCode.EXTRACTION_FAILED.value,
        }

    is_cached = extracted.get("is_cached", True)
    model_name = extracted.get("model", "openai/gpt-oss-120b")

    if extracted.get("status") == "failed":
        err_msg = extracted.get("error_message", "Unknown extraction failure")
        order_data = {
            "request_id": request_id,
            "order_ref": order_ref,
            "raw_text": text,
            "status": "failed",
            "line_items": [],
            "gross_cents": 0,
            "discount_cents": 0,
            "total_cents": 0,
            "notes": f"Extraction failed: {err_msg}",
            "is_cached": is_cached,
            "model": model_name,
            "catalog_evidence": [],
            "exception_code": ExceptionCode.EXTRACTION_FAILED.value,
        }
        save_order(order_data, db_path=db_path)
        return {
            "id": request_id,
            "order_ref": order_ref,
            "outcome": "failed",
            "reason": err_msg,
            "error": err_msg,
            "exception_code": ExceptionCode.EXTRACTION_FAILED.value,
        }

    items = extracted.get("items", [])
    if not items:
        issue = {"reason": "no items extracted from request text", "product": "unspecified", "quantity": None}
        draft_info = generate_clarification_email(request_id, order_ref, [issue])
        save_clarification_draft(draft_info, db_path=db_path)
        order_data = {
            "request_id": request_id,
            "order_ref": order_ref,
            "raw_text": text,
            "status": "needs-clarification",
            "line_items": [],
            "gross_cents": 0,
            "discount_cents": 0,
            "total_cents": 0,
            "notes": "No items extracted",
            "is_cached": is_cached,
            "model": model_name,
            "catalog_evidence": [],
            "exception_code": ExceptionCode.UNKNOWN_CATALOG_PRODUCT.value,
        }
        save_order(order_data, db_path=db_path)
        return {
            "id": request_id,
            "order_ref": order_ref,
            "outcome": "needs-clarification",
            "reason": "no items extracted",
            "draft_email": draft_info["draft_email"],
            "is_cached": is_cached,
            "model": model_name,
            "exception_code": ExceptionCode.UNKNOWN_CATALOG_PRODUCT.value,
        }

    # 3. Deterministic Local Catalog Lookup & Quantity Validation
    issues = []
    valid_line_items = []
    catalog_evidence = []
    assigned_exception_code: Optional[ExceptionCode] = None

    for item in items:
        raw_product = item.get("raw_product_text", "")
        extracted_sku = item.get("extracted_sku")
        qty = item.get("extracted_quantity")
        is_qty_ambiguous = item.get("is_quantity_ambiguous", False)
        ambiguity_reason = item.get("ambiguity_reason")

        item_has_issue = False

        # Quantity validation: check ambiguity, source-text support, and positive integers
        if is_qty_ambiguous:
            issues.append(
                {
                    "reason": ambiguity_reason or "ambiguous quantity (box/pack/vague unit)",
                    "product": raw_product,
                    "quantity": item.get("raw_quantity_text"),
                }
            )
            item_has_issue = True
            if not assigned_exception_code:
                assigned_exception_code = ExceptionCode.AMBIGUOUS_CONTAINER_QUANTITY
        elif qty is not None and qty > 0 and not _quantity_supported(qty, item.get("raw_quantity_text")):
            # Catches model hallucinations where extracted number does not appear in customer text
            issues.append(
                {
                    "reason": "ambiguous quantity (stated number could not be confirmed in the request text)",
                    "product": raw_product,
                    "quantity": item.get("raw_quantity_text"),
                }
            )
            item_has_issue = True
            if not assigned_exception_code:
                assigned_exception_code = ExceptionCode.AMBIGUOUS_CONTAINER_QUANTITY
        elif qty is None or qty <= 0:
            issues.append(
                {
                    "reason": "ambiguous or invalid quantity (must be a positive whole number)",
                    "product": raw_product,
                    "quantity": item.get("raw_quantity_text"),
                }
            )
            item_has_issue = True
            if not assigned_exception_code:
                assigned_exception_code = ExceptionCode.AMBIGUOUS_CONTAINER_QUANTITY

        # The customer's own words decide the match; the model's extracted_sku is only a hint
        lookup_result = lookup_catalog_tool(raw_product)
        if (
            lookup_result["matched"]
            and extracted_sku
            and extracted_sku.strip().upper() != lookup_result["sku"]
        ):
            lookup_result = {
                **lookup_result,
                "matched": False,
                "match_rule": "ambiguous_multi_match",
                "evidence": (
                    f"Ambiguous product: proposed SKU {extracted_sku} disagrees with "
                    f"catalog match {lookup_result['sku']} for '{raw_product}'"
                ),
            }

        catalog_evidence.append(lookup_result)

        if lookup_result["matched"]:
            matched_sku = lookup_result["sku"]
            catalog_item = get_catalog_item(matched_sku)
        else:
            catalog_item = None
            if lookup_result["match_rule"] == "ambiguous_multi_match":
                issues.append({"reason": lookup_result["evidence"], "product": raw_product, "quantity": qty})
                item_has_issue = True
                if not assigned_exception_code:
                    assigned_exception_code = ExceptionCode.AMBIGUOUS_PRODUCT_DESCRIPTION
            else:
                issues.append({"reason": "unknown product", "product": raw_product, "quantity": qty})
                item_has_issue = True
                if not assigned_exception_code:
                    assigned_exception_code = ExceptionCode.UNKNOWN_CATALOG_PRODUCT

        if not item_has_issue and catalog_item and qty and qty > 0:
            valid_line_items.append(
                {
                    "sku": catalog_item.sku,
                    "name": catalog_item.name,
                    "unit_cents": catalog_item.unit_cents,
                    "quantity": qty,
                }
            )

    # 4. Status decision: Needs clarification vs Clean draft
    if issues:
        draft_info = generate_clarification_email(request_id, order_ref, issues)
        save_clarification_draft(draft_info, db_path=db_path)

        combined_reason = "; ".join(iss["reason"] for iss in issues)
        flagged_product = issues[0]["product"]
        flagged_qty = issues[0].get("quantity")
        final_code = assigned_exception_code.value if assigned_exception_code else ExceptionCode.UNKNOWN_CATALOG_PRODUCT.value

        # Preserve any already-resolved valid line items so the reviewer does not have to
        # re-enter them manually. Orders where ALL items have issues keep an empty list.
        preserved_lines = valid_line_items if valid_line_items else []

        order_data = {
            "request_id": request_id,
            "order_ref": order_ref,
            "raw_text": text,
            "status": "needs-clarification",
            "line_items": preserved_lines,
            "gross_cents": 0,
            "discount_cents": 0,
            "total_cents": 0,  # Explicitly 0 for unapproved exception orders
            "notes": f"Flagged: {combined_reason}",
            "is_cached": is_cached,
            "model": model_name,
            "catalog_evidence": catalog_evidence,
            "exception_code": final_code,
        }
        save_order(order_data, db_path=db_path)

        res = {
            "id": request_id,
            "order_ref": order_ref,
            "outcome": "needs-clarification",
            "reason": combined_reason,
            "flagged_item": flagged_product,
            "draft_email": draft_info["draft_email"],
            "is_cached": is_cached,
            "model": model_name,
            "catalog_evidence": catalog_evidence,
            "exception_code": final_code,
        }
        if flagged_qty:
            res["flagged_quantity"] = flagged_qty
        return res

    # 5. Pricing calculation for valid orders -> draft
    pricing = calculate_order_pricing(valid_line_items)

    order_data = {
        "request_id": request_id,
        "order_ref": order_ref,
        "raw_text": text,
        "status": "draft",
        "line_items": pricing["line_items"],
        "gross_cents": pricing["gross_cents"],
        "discount_cents": pricing["discount_cents"],
        "total_cents": pricing["total_cents"],
        "notes": "Automated draft ready for fulfillment",
        "is_cached": is_cached,
        "model": model_name,
        "catalog_evidence": catalog_evidence,
        "exception_code": ExceptionCode.CLEAN_DRAFT.value,
    }
    save_order(order_data, db_path=db_path)

    res = {
        "id": request_id,
        "order_ref": order_ref,
        "outcome": "draft",
        "line_items": pricing["line_items"],
        "gross_cents": pricing["gross_cents"],
        "discount_cents": pricing["discount_cents"],
        "total_cents": pricing["total_cents"],
        "is_cached": is_cached,
        "model": model_name,
        "catalog_evidence": catalog_evidence,
        "exception_code": ExceptionCode.CLEAN_DRAFT.value,
    }
    if len(pricing["line_items"]) == 1:
        res["sku"] = pricing["line_items"][0]["sku"]
        res["quantity"] = pricing["line_items"][0]["quantity"]

    return res


def batch_process(
    requests: List[Dict[str, Any]],
    force_replay: bool = True,
    db_path: str = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    """Process a batch of incoming order requests with per-request fault isolation."""
    results = []
    for req in requests:
        try:
            res = process_request(req, force_replay=force_replay, db_path=db_path)
        except Exception as exc:  # One bad request must never crash the entire batch
            res = {
                "id": req.get("id", "unknown"),
                "order_ref": req.get("order_ref", "unknown"),
                "outcome": "failed",
                "reason": f"Unhandled processing error: {exc}",
                "exception_code": ExceptionCode.EXTRACTION_FAILED.value,
            }
        results.append(res)
    return results


def apply_reviewer_correction(
    order_ref: str,
    corrected_items: List[Dict[str, Any]],
    reviewer: str = "human_reviewer",
    comment: str = "Manual reviewer correction",
    db_path: str = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """Applies a human reviewer correction across all line items, reruns pricing, sets status to 'reviewed'."""
    return apply_manual_correction(
        order_ref=order_ref,
        corrected_items=corrected_items,
        reviewer=reviewer,
        comment=comment,
        db_path=db_path,
    )
