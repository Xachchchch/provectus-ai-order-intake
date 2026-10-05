"""Deterministic pricing arithmetic using integer cents and Decimal ROUND_HALF_UP."""

from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Any


def calculate_line_price(unit_cents: int, quantity: int) -> Dict[str, Any]:
    """
    Calculate price for a single line item.
    
    Rules:
    - Quantities are positive whole numbers of individual items.
    - If quantity >= 10, apply a 10% discount to this line only.
    - Round the discount to the nearest cent, with halves rounded up (ROUND_HALF_UP).
    """
    if quantity <= 0:
        raise ValueError(f"Quantity must be a positive whole number, got {quantity}")
    if unit_cents < 0:
        raise ValueError(f"Unit cents must be non-negative, got {unit_cents}")

    gross_cents = unit_cents * quantity

    if quantity >= 10:
        # 10% bulk discount on this line
        # Using Decimal arithmetic with exact half-up rounding
        gross_decimal = Decimal(str(gross_cents))
        discount_rate = Decimal("0.10")
        raw_discount = gross_decimal * discount_rate
        discount_cents = int(raw_discount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    else:
        discount_cents = 0

    net_cents = gross_cents - discount_cents

    return {
        "quantity": quantity,
        "unit_cents": unit_cents,
        "gross_cents": gross_cents,
        "discount_cents": discount_cents,
        "total_cents": net_cents,
    }


def calculate_order_pricing(line_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Calculate overall order pricing across all line items.
    
    Returns priced lines and order totals in integer cents.
    """
    priced_lines = []
    total_gross = 0
    total_discount = 0
    total_net = 0

    for item in line_items:
        unit_cents = item["unit_cents"]
        quantity = item["quantity"]
        sku = item["sku"]
        name = item.get("name", "")

        line_calc = calculate_line_price(unit_cents, quantity)
        priced_line = {
            "sku": sku,
            "name": name,
            "quantity": quantity,
            "unit_cents": unit_cents,
            "gross_cents": line_calc["gross_cents"],
            "discount_cents": line_calc["discount_cents"],
            "total_cents": line_calc["total_cents"],
        }
        priced_lines.append(priced_line)

        total_gross += line_calc["gross_cents"]
        total_discount += line_calc["discount_cents"]
        total_net += line_calc["total_cents"]

    return {
        "line_items": priced_lines,
        "gross_cents": total_gross,
        "discount_cents": total_discount,
        "total_cents": total_net,
    }
