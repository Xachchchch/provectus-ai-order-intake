"""Catalog definitions and deterministic matcher for AI Order Intake."""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class MatchStatus(Enum):
    EXACT_SKU = "exact_sku"
    EXACT_DESCRIPTION = "exact_description"
    AMBIGUOUS = "ambiguous"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CatalogItem:
    sku: str
    name: str
    unit_cents: int
    aliases: Tuple[str, ...] = ()


# Official Fictional Catalog defined in tasks/orders/domain.md & seed.json
CATALOG: Dict[str, CatalogItem] = {
    "CAB-1": CatalogItem(
        sku="CAB-1",
        name="USB-C cable 1 m",
        unit_cents=2000,
        aliases=(
            "usb-c cable 1 m",
            "usb-c cable 1m",
            "1m usb-c cable",
            "1 meter usb-c cable",
            "usb c cable 1m",
            "usb c cable 1 m",
            "cables (cab-1)",
        ),
    ),
    "CAB-2": CatalogItem(
        sku="CAB-2",
        name="USB-C cable 2 m",
        unit_cents=3000,
        aliases=(
            "usb-c cable 2 m",
            "usb-c cable 2m",
            "2m usb-c cable",
            "2 meter usb-c cable",
            "usb c cable 2m",
            "usb c cable 2 m",
            "cables (cab-2)",
        ),
    ),
    "HUB-1": CatalogItem(
        sku="HUB-1",
        name="USB hub",
        unit_cents=5000,
        aliases=(
            "usb hub",
            "usb hubs",
            "usb-hub",
        ),
    ),
}


def normalize_text(text: str) -> str:
    """Normalize text for consistent string matching."""
    return " ".join(text.lower().replace("-", " ").replace("_", " ").split())


def get_catalog_item(sku: str) -> Optional[CatalogItem]:
    """Retrieve catalog item by exact SKU (case-insensitive)."""
    return CATALOG.get(sku.strip().upper())


def match_catalog_item(text: str) -> Tuple[Optional[CatalogItem], MatchStatus, str]:
    """
    Deterministically matches input text to a catalog item by SKU or unambiguous description.
    
    Returns:
        (CatalogItem, MatchStatus, details_message)
    """
    if not text or not text.strip():
        return None, MatchStatus.UNKNOWN, "No product specified"

    raw = text.strip()
    norm = normalize_text(raw)

    # 1. Exact SKU check
    for sku, item in CATALOG.items():
        if raw.upper() == sku or norm == normalize_text(sku):
            return item, MatchStatus.EXACT_SKU, f"Matched exact SKU {sku}"

    # 2. Exact or Alias Description check
    for sku, item in CATALOG.items():
        if norm == normalize_text(item.name):
            return item, MatchStatus.EXACT_DESCRIPTION, f"Matched exact catalog name '{item.name}' ({sku})"
        for alias in item.aliases:
            if norm == normalize_text(alias):
                return item, MatchStatus.EXACT_DESCRIPTION, f"Matched catalog alias '{alias}' ({sku})"

    # 3. Check for ambiguous descriptions (e.g., "USB-C cable" without length, "the usual cable")
    ambiguous_keywords = [
        "the usual cable",
        "usual cable",
        "usb c cable",
        "usb-c cable",
        "usb c cables",
        "usb-c cables",
        "cable",
        "cables",
    ]
    if norm in [normalize_text(kw) for kw in ambiguous_keywords]:
        matching_skus = ["CAB-1", "CAB-2"]
        return None, MatchStatus.AMBIGUOUS, f"Ambiguous product description: matches multiple items ({', '.join(matching_skus)})"

    # Check if string matches multiple SKUs partially
    matching_items = []
    for sku, item in CATALOG.items():
        if re.search(r"\b" + re.escape(normalize_text(sku)) + r"\b", norm):
            matching_items.append(item)

    if len(matching_items) == 1:
        return matching_items[0], MatchStatus.EXACT_DESCRIPTION, f"Matched unambiguous description '{matching_items[0].name}' ({matching_items[0].sku})"
    elif len(matching_items) > 1:
        skus = [it.sku for it in matching_items]
        return None, MatchStatus.AMBIGUOUS, f"Ambiguous product description: matches multiple items ({', '.join(skus)})"

    # 4. Unknown product
    return None, MatchStatus.UNKNOWN, f"Unknown product: '{raw}'"


def lookup_catalog_tool(query: str) -> Dict[str, Any]:
    """
    Dedicated local catalog lookup tool that strictly searches the catalog.
    Records the source query, matching rule, and catalog entry details supporting the proposal.

    Rule categories:
        - 'exact_sku'
        - 'unambiguous_alias'
        - 'ambiguous_multi_match'
        - 'unknown_product'
    """
    if not query or not query.strip():
        return {
            "query": query,
            "matched": False,
            "sku": None,
            "name": None,
            "unit_cents": None,
            "match_rule": "unknown_product",
            "evidence": "No product query provided",
        }

    raw = query.strip()
    norm = normalize_text(raw)

    # 1. Exact SKU check
    for sku, item in CATALOG.items():
        if raw.upper() == sku or norm == normalize_text(sku):
            return {
                "query": query,
                "matched": True,
                "sku": item.sku,
                "name": item.name,
                "unit_cents": item.unit_cents,
                "match_rule": "exact_sku",
                "evidence": f"Matched exact SKU {sku} ({item.name}, ${item.unit_cents / 100:.2f})",
            }

    # 2. Exact or Alias Description check
    for sku, item in CATALOG.items():
        if norm == normalize_text(item.name):
            return {
                "query": query,
                "matched": True,
                "sku": item.sku,
                "name": item.name,
                "unit_cents": item.unit_cents,
                "match_rule": "unambiguous_alias",
                "evidence": f"Matched catalog name '{item.name}' -> {sku} (${item.unit_cents / 100:.2f})",
            }
        for alias in item.aliases:
            if norm == normalize_text(alias):
                return {
                    "query": query,
                    "matched": True,
                    "sku": item.sku,
                    "name": item.name,
                    "unit_cents": item.unit_cents,
                    "match_rule": "unambiguous_alias",
                    "evidence": f"Matched catalog alias '{alias}' -> {sku} (${item.unit_cents / 100:.2f})",
                }

    # 3. Check for ambiguous descriptions
    ambiguous_keywords = [
        "the usual cable",
        "usual cable",
        "usb c cable",
        "usb-c cable",
        "usb c cables",
        "usb-c cables",
        "cable",
        "cables",
    ]
    if norm in [normalize_text(kw) for kw in ambiguous_keywords]:
        matching_skus = ["CAB-1", "CAB-2"]
        return {
            "query": query,
            "matched": False,
            "sku": None,
            "name": None,
            "unit_cents": None,
            "match_rule": "ambiguous_multi_match",
            "evidence": f"Ambiguous product description: matches multiple catalog SKUs ({', '.join(matching_skus)})",
        }

    # Partial matches
    matching_items = []
    for sku, item in CATALOG.items():
        if re.search(r"\b" + re.escape(normalize_text(sku)) + r"\b", norm):
            matching_items.append(item)

    if len(matching_items) == 1:
        item = matching_items[0]
        return {
            "query": query,
            "matched": True,
            "sku": item.sku,
            "name": item.name,
            "unit_cents": item.unit_cents,
            "match_rule": "unambiguous_alias",
            "evidence": f"Matched unambiguous description '{item.name}' -> {item.sku} (${item.unit_cents / 100:.2f})",
        }
    elif len(matching_items) > 1:
        skus = [it.sku for it in matching_items]
        return {
            "query": query,
            "matched": False,
            "sku": None,
            "name": None,
            "unit_cents": None,
            "match_rule": "ambiguous_multi_match",
            "evidence": f"Ambiguous product description: matches multiple items ({', '.join(skus)})",
        }

    # 4. Unknown product
    return {
        "query": query,
        "matched": False,
        "sku": None,
        "name": None,
        "unit_cents": None,
        "match_rule": "unknown_product",
        "evidence": f"Unknown product: '{raw}' (not found in catalog)",
    }

