"""LLM extractor with native function calling, Pydantic validation, and strict offline replay."""

import json
import os
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError, model_validator


CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cached_responses")


# ---------------------------------------------------------------------------
# Custom exception - raised instead of silently falling back to regex
# ---------------------------------------------------------------------------
class ExtractionError(Exception):
    """Raised when no cached response exists and no LLM API key is configured."""


# ---------------------------------------------------------------------------
# Native OpenAI / Groq Tool Schema for the catalog lookup
# ---------------------------------------------------------------------------
CATALOG_LOOKUP_TOOL = {
    "type": "function",
    "function": {
        "name": "lookup_catalog",
        "description": (
            "Searches the official product catalog by SKU or product name to verify "
            "availability, canonical SKU, and unit pricing."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Product SKU (e.g. CAB-1) or natural language description (e.g. USB hub)",
                }
            },
            "required": ["query"],
        },
    },
}


# ---------------------------------------------------------------------------
# Container / vague-quantity terms - deterministic Pydantic guard
# ---------------------------------------------------------------------------
CONTAINER_TERMS = {
    "box", "boxes", "pack", "packs", "crate", "crates",
    "case", "cases", "several", "bundle", "a couple",
}


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------
class ExtractedOrderItem(BaseModel):
    raw_product_text: str = Field(description="Raw text snippet representing the requested product")
    raw_quantity_text: str = Field(description="Raw text snippet representing the quantity")
    extracted_sku: Optional[str] = Field(default=None, description="Exact catalog SKU if identified")
    extracted_quantity: Optional[int] = Field(default=None, description="Positive whole number of units or null")
    is_quantity_ambiguous: bool = Field(default=False, description="True if container or vague quantity term was used")
    ambiguity_reason: Optional[str] = Field(default=None, description="Reason why quantity is ambiguous")

    @model_validator(mode="after")
    def enforce_container_ambiguity_guard(self) -> "ExtractedOrderItem":
        text_to_check = f"{self.raw_quantity_text} {self.raw_product_text}".lower()
        for term in CONTAINER_TERMS:
            if re.search(r"\b" + re.escape(term) + r"\b", text_to_check):
                self.extracted_quantity = None
                self.is_quantity_ambiguous = True
                if not self.ambiguity_reason:
                    self.ambiguity_reason = (
                        f"Quantity expressed in container term '{term}' "
                        "which cannot be inferred as units."
                    )
                break
        return self


class ExtractionPayload(BaseModel):
    request_id: str
    order_ref: str
    raw_text: str
    items: List[ExtractedOrderItem] = Field(default_factory=list)
    confidence: float = 1.0
    is_cached: bool = False
    model: str = "unknown"
    cached_at: Optional[str] = None
    tool_calls_log: List[Dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Extraction prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are an accurate, strict order intake information extractor.
Given a customer's raw order request text, extract all requested items and quantities.
You have access to a 'lookup_catalog' tool - call it for EVERY product mentioned to
verify the canonical SKU and pricing BEFORE producing the final JSON.

CRITICAL RULES:
1. Extract exact product names or SKU codes mentioned.
2. Quantities must be positive whole numbers of individual units.
3. NEVER guess or infer how many items a container contains (e.g. "box", "pack", "crate",
   "bundle", "case", "several", "a couple").
   If any such vague or container term is used, set "extracted_quantity": null,
   "is_quantity_ambiguous": true, and "ambiguity_reason" describing the ambiguity.
4. If an exact SKU from the catalog (CAB-1, CAB-2, HUB-1) is identified via the lookup,
   populate "extracted_sku", otherwise set "extracted_sku": null.
5. Return ONLY a valid JSON object matching the requested schema after all tool calls are done.
"""


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------
def load_cached_response(request_id: str, cache_dir: str = CACHE_DIR) -> Optional[Dict[str, Any]]:
    cache_file = os.path.join(cache_dir, f"{request_id}.json")
    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
        raw_data["is_cached"] = True
        if "model" not in raw_data:
            raw_data["model"] = "llama-3.3-70b-versatile"
        raw_data.setdefault("tool_calls_log", [])
        payload = ExtractionPayload.model_validate(raw_data)
        return payload.model_dump()
    return None


def save_cached_response(request_id: str, data: Dict[str, Any], cache_dir: str = CACHE_DIR) -> None:
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, f"{request_id}.json")
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Live LLM extraction with native tool calling
# ---------------------------------------------------------------------------
def _run_live_extraction(
    client: Any,
    model: str,
    request_id: str,
    order_ref: str,
    text: str,
) -> Dict[str, Any]:
    from src.catalog import lookup_catalog_tool

    system_prompt = (
        "You are an accurate, strict order intake information extractor.\n"
        "Given a customer's raw order request text, extract all requested items and quantities.\n"
        "You have access to a 'lookup_catalog' tool. Call 'lookup_catalog' ONLY for the specific products "
        "mentioned in the customer text to verify the canonical SKU and pricing.\n"
        "Do not query products that are not requested.\n"
        "Once all requested products are verified via lookup_catalog, stop calling tools and output the final JSON immediately.\n\n"
        "CRITICAL RULES:\n"
        "1. Extract exact product names or SKU codes mentioned.\n"
        "2. Quantities must be positive whole numbers of individual units.\n"
        "3. NEVER infer container quantities ('box', 'pack', 'crate', 'several'). Set extracted_quantity: null, is_quantity_ambiguous: true.\n"
        "4. Return ONLY a valid JSON object matching the requested schema."
    )

    user_content = (
        f'Extract order details for request:\n'
        f'Request ID: {request_id}\n'
        f'Order Reference: {order_ref}\n'
        f'Customer text: "{text}"\n\n'
        f'Return JSON matching schema:\n'
        f'{{\n'
        f'  "request_id": "{request_id}",\n'
        f'  "order_ref": "{order_ref}",\n'
        f'  "raw_text": "{text}",\n'
        f'  "items": [\n'
        f'    {{\n'
        f'      "raw_product_text": "<text>",\n'
        f'      "raw_quantity_text": "<text>",\n'
        f'      "extracted_sku": "<SKU or null>",\n'
        f'      "extracted_quantity": <int or null>,\n'
        f'      "is_quantity_ambiguous": <bool>,\n'
        f'      "ambiguity_reason": "<reason or null>"\n'
        f'    }}\n'
        f'  ],\n'
        f'  "confidence": 0.95\n'
        f'}}\n'
    )

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    tool_calls_log: List[Dict[str, Any]] = []
    seen_queries = set()

    for _round in range(6):
        response = client.chat.completions.create(
            model=model,
            temperature=0.0,
            messages=messages,
            tools=[CATALOG_LOOKUP_TOOL],
            tool_choice="auto",
        )

        choice = response.choices[0]
        assistant_msg = choice.message
        messages.append(assistant_msg)

        if assistant_msg.tool_calls:
            for tc in assistant_msg.tool_calls:
                fn_args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                query = fn_args.get("query", "")
                tool_result = lookup_catalog_tool(query)
                tool_calls_log.append({
                    "tool_call_id": tc.id,
                    "function": tc.function.name,
                    "arguments": fn_args,
                    "result": tool_result,
                })
                
                content_payload = tool_result
                if query in seen_queries:
                    content_payload = {
                        **tool_result,
                        "instruction": "Item already verified. Stop calling tools and output the final JSON now."
                    }
                seen_queries.add(query)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(content_payload),
                })
        else:
            # Model completed tool calling rounds and returned the final JSON output
            content = assistant_msg.content or "{}"
            content = content.strip()
            if content.startswith("```"):
                lines = content.splitlines()
                if lines and lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                content = "\n".join(lines).strip()

            try:
                raw_json = json.loads(content)
            except json.JSONDecodeError:
                first_brace = content.find("{")
                last_brace = content.rfind("}")
                if first_brace != -1 and last_brace != -1:
                    raw_json = json.loads(content[first_brace : last_brace + 1])
                else:
                    raise

            raw_json["is_cached"] = False
            raw_json["model"] = model
            raw_json["tool_calls_log"] = tool_calls_log
            validated_payload = ExtractionPayload.model_validate(raw_json)
            return validated_payload.model_dump()

    raise ExtractionError(
        f"LLM did not produce a final answer after tool-call rounds for {request_id}."
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def extract_order_information(
    request_id: str,
    order_ref: str,
    text: str,
    force_replay: bool = False,
    cache_dir: str = CACHE_DIR,
) -> Dict[str, Any]:
    """
    Extract order items and quantities from raw text.

    Resolution order:
    1. force_replay=True -> load from cache, raise ExtractionError if not cached.
    2. Cache hit -> return cached payload.
    3. API key present -> live LLM call with native tool calling -> cache -> return.
    4. No cache + no API key -> raise ExtractionError (NO silent regex fallback).
    """
    groq_key = os.getenv("GROQ_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    if force_replay:
        cached = load_cached_response(request_id, cache_dir=cache_dir)
        if cached:
            return cached
        raise ExtractionError(
            f"force_replay=True but no cached response found for '{request_id}'."
        )

    cached = load_cached_response(request_id, cache_dir=cache_dir)
    if cached:
        return cached

    if not groq_key and not openai_key:
        raise ExtractionError(
            f"No cached response found for '{request_id}' and no active LLM API key "
            "(GROQ_API_KEY or OPENAI_API_KEY) is set. "
            "Provide an API key or add a pre-generated cache file."
        )

    try:
        from openai import OpenAI

        if groq_key:
            client = OpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1")
            model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        else:
            client = OpenAI(api_key=openai_key)
            model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        result = _run_live_extraction(client, model, request_id, order_ref, text)
        save_cached_response(request_id, result, cache_dir=cache_dir)
        return result

    except ValidationError as val_err:
        return {
            "request_id": request_id,
            "order_ref": order_ref,
            "raw_text": text,
            "status": "failed",
            "error_type": "pydantic_validation_error",
            "error_message": str(val_err),
            "is_cached": False,
            "model": locals().get("model", "unknown"),
        }
    except ExtractionError:
        raise
    except Exception as exc:
        return {
            "request_id": request_id,
            "order_ref": order_ref,
            "raw_text": text,
            "status": "failed",
            "error_type": "llm_invocation_error",
            "error_message": str(exc),
            "is_cached": False,
            "model": locals().get("model", "unknown"),
        }
