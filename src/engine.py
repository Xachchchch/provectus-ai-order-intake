"""Core processing engine for AI Order Intake & Exception Handling."""

from typing import Any, Dict, List, Optional
import os

from src.catalog import CATALOG, MatchStatus, get_catalog_item, match_catalog_item
from src.extractor import extract_order_information
from src.pricing import calculate_order_pricing
from src.storage import (
    DEFAULT_DB_PATH,
    apply_manual_correction,
    get_clarification_draft,
    get_order,
    list_orders,
    save_clarification_draft,
    save_order,
)


def generate_clarification_email(
    request_id: str,
    order_ref: str,
    issues: List[Dict[str, Any]],
) -> Dict[str, str]:
    """
    Generate an automated, customer-friendly inquiry email draft for flagged orders.
    """
    subject = f"Action Required: Clarification needed for Order Ref #{order_ref}"

    bullet_points = []
    for issue in issues:
        reason = issue.get("reason", "Clarification needed")
        product = issue.get("product", "item")
        qty = issue.get("quantity")

        if "unknown product" in reason.lower():
            bullet_points.append(
                f"- Unknown product '{product}': Our catalog currently offers:\n"
                f"    * CAB-1: USB-C cable 1 m ($20.00)\n"
                f"    * CAB-2: USB-C cable 2 m ($30.00)\n"
                f"    * HUB-1: USB hub ($50.00)\n"
                f"  Please confirm if you would like one of these items or a different specification."
            )
        elif "box" in reason.lower() or "pack" in reason.lower() or "ambiguous quantity" in reason.lower():
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
    Process a single order request through the end-to-end pipeline:
    1. Duplicate Detection: Same order_ref describes the same order.
       Reprocessing an identical request is recorded as a duplicate and DOES NOT create a new draft.
    2. Information Extraction (LLM with offline replay cache & Pydantic validation).
    3. Deterministic Validation against catalog & domain rules.
    4. Deterministic Pricing calculation or Clarification Drafting.
    5. Persistence to SQLite database with status and cache metadata.
    """
    request_id = request["id"]
    order_ref = request["order_ref"]
    text = request["text"]

    # 1. Duplicate check: Same order_ref describes the same order.
    # Reprocessing an identical request must not create a second draft.
    existing_order = get_order(order_ref, db_path=db_path)
    if existing_order and existing_order["request_id"] != request_id:
        duplicate_data = {
            "request_id": request_id,
            "order_ref": order_ref,
            "raw_text": text,
            "status": "duplicate",
            "line_items": [],
            "gross_cents": 0,
            "discount_cents": 0,
            "total_cents": 0,
            "notes": f"Duplicate request of {existing_order['request_id']} (order_ref '{order_ref}'). Blocked from creating new draft.",
            "is_cached": True,
            "model": "rule_based_dedup",
        }
        save_order(duplicate_data, db_path=db_path)

        return {
            "id": request_id,
            "order_ref": order_ref,
            "outcome": "duplicate",
            "same_order_as": existing_order["request_id"],
            "new_drafts": 0,
            "message": f"Duplicate request for order_ref '{order_ref}'; already processed as '{existing_order['request_id']}'.",
        }

    # 2. Extract structured fields using LLM or offline replay cache
    extracted = extract_order_information(
        request_id=request_id,
        order_ref=order_ref,
        text=text,
        force_replay=force_replay,
    )

    is_cached = extracted.get("is_cached", True)
    model_name = extracted.get("model", "llama-3.3-70b-versatile")

    # Check for extraction failure (unparseable or model error)
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
        }
        save_order(order_data, db_path=db_path)
        return {
            "id": request_id,
            "order_ref": order_ref,
            "outcome": "failed",
            "reason": err_msg,
            "error": err_msg,
        }

    items = extracted.get("items", [])
    if not items:
        # No items detected
        issue = {
            "reason": "no items extracted from request text",
            "product": "unspecified",
            "quantity": None,
        }
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
        }

    # 3. Deterministic Catalog Matching & Quantity Validation
    issues = []
    valid_line_items = []

    for item in items:
        raw_product = item.get("raw_product_text", "")
        extracted_sku = item.get("extracted_sku")
        qty = item.get("extracted_quantity")
        is_qty_ambiguous = item.get("is_quantity_ambiguous", False)
        ambiguity_reason = item.get("ambiguity_reason")

        item_has_issue = False

        # Quantity ambiguity check
        if is_qty_ambiguous:
            issues.append(
                {
                    "reason": ambiguity_reason or "ambiguous quantity (box/pack/vague unit)",
                    "product": raw_product,
                    "quantity": item.get("raw_quantity_text"),
                }
            )
            item_has_issue = True
        elif qty is None or qty <= 0:
            issues.append(
                {
                    "reason": "ambiguous or invalid quantity (must be a positive whole number)",
                    "product": raw_product,
                    "quantity": item.get("raw_quantity_text"),
                }
            )
            item_has_issue = True

        # Product matching check
        catalog_item = None
        if extracted_sku:
            catalog_item = get_catalog_item(extracted_sku)

        if not catalog_item:
            matched_item, status, msg = match_catalog_item(raw_product)
            if status in (MatchStatus.EXACT_SKU, MatchStatus.EXACT_DESCRIPTION):
                catalog_item = matched_item
            elif status == MatchStatus.AMBIGUOUS:
                issues.append(
                    {
                        "reason": msg,
                        "product": raw_product,
                        "quantity": qty,
                    }
                )
                item_has_issue = True
            else:
                issues.append(
                    {
                        "reason": "unknown product",
                        "product": raw_product,
                        "quantity": qty,
                    }
                )
                item_has_issue = True

        if not item_has_issue and catalog_item and qty and qty > 0:
            valid_line_items.append(
                {
                    "sku": catalog_item.sku,
                    "name": catalog_item.name,
                    "unit_cents": catalog_item.unit_cents,
                    "quantity": qty,
                }
            )

    # 4. Status decision: If ANY issue exists -> needs-clarification
    if issues:
        draft_info = generate_clarification_email(request_id, order_ref, issues)
        save_clarification_draft(draft_info, db_path=db_path)

        combined_reason = "; ".join(iss["reason"] for iss in issues)
        flagged_product = issues[0]["product"]
        flagged_qty = issues[0].get("quantity")

        order_data = {
            "request_id": request_id,
            "order_ref": order_ref,
            "raw_text": text,
            "status": "needs-clarification",
            "line_items": [],
            "gross_cents": 0,
            "discount_cents": 0,
            "total_cents": 0,
            "notes": f"Flagged: {combined_reason}",
            "is_cached": is_cached,
            "model": model_name,
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
    """Process a batch of incoming order requests."""
    results = []
    for req in requests:
        res = process_request(req, force_replay=force_replay, db_path=db_path)
        results.append(res)
    return results


def apply_reviewer_correction(
    order_ref: str,
    corrected_items: List[Dict[str, Any]],
    reviewer: str = "human_reviewer",
    comment: str = "Manual reviewer correction",
    db_path: str = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """Applies a human reviewer correction, reruns deterministic pricing, and sets status to 'reviewed'."""
    return apply_manual_correction(
        order_ref=order_ref,
        corrected_items=corrected_items,
        reviewer=reviewer,
        comment=comment,
        db_path=db_path,
    )
