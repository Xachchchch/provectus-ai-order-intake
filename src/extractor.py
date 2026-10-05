"""LLM extractor with offline replay caching, Pydantic validation, and explicit cache labeling."""

import json
import os
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ValidationError


CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cached_responses")

# Pydantic Schemas for Strict Data Validation
class ExtractedOrderItem(BaseModel):
    raw_product_text: str = Field(description="Raw text snippet representing the requested product")
    raw_quantity_text: str = Field(description="Raw text snippet representing the quantity")
    extracted_sku: Optional[str] = Field(default=None, description="Exact catalog SKU if identified")
    extracted_quantity: Optional[int] = Field(default=None, description="Positive whole number of units or null")
    is_quantity_ambiguous: bool = Field(default=False, description="True if container or vague quantity term was used")
    ambiguity_reason: Optional[str] = Field(default=None, description="Reason why quantity is ambiguous")


class ExtractionPayload(BaseModel):
    request_id: str
    order_ref: str
    raw_text: str
    items: List[ExtractedOrderItem] = Field(default_factory=list)
    confidence: float = 1.0
    is_cached: bool = False
    model: str = "unknown"
    cached_at: Optional[str] = None


# Extraction prompt instructions
SYSTEM_PROMPT = """You are an accurate, strict order intake information extractor.
Given a customer's raw order request text, extract all requested items and quantities.

CRITICAL RULES:
1. Extract exact product names or SKU codes mentioned.
2. Quantities must be positive whole numbers of individual units.
3. NEVER guess or infer how many items a container contains (e.g. "box", "pack", "crate", "bundle", "case", "several", "a couple").
   If any such vague or container term is used, set "extracted_quantity": null, "is_quantity_ambiguous": true, and "ambiguity_reason" describing the ambiguity.
4. If an exact SKU from the catalog (CAB-1, CAB-2, HUB-1) is identified, populate "extracted_sku", otherwise set "extracted_sku": null.
5. Return ONLY a valid JSON object matching the requested schema.
"""


def load_cached_response(request_id: str, cache_dir: str = CACHE_DIR) -> Optional[Dict[str, Any]]:
    """Load cached extraction response for offline replay with Pydantic validation."""
    cache_file = os.path.join(cache_dir, f"{request_id}.json")
    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
            # Label cache explicitly
            raw_data["is_cached"] = True
            if "model" not in raw_data:
                raw_data["model"] = "llama-3.3-70b-versatile"
            # Validate through Pydantic
            payload = ExtractionPayload.model_validate(raw_data)
            return payload.model_dump()
    return None


def save_cached_response(request_id: str, data: Dict[str, Any], cache_dir: str = CACHE_DIR) -> None:
    """Save extraction response to cache for deterministic replay."""
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, f"{request_id}.json")
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def fallback_rule_based_extractor(request_id: str, order_ref: str, text: str) -> Dict[str, Any]:
    """
    Deterministic rule-based extractor used only when offline cache and API keys are missing.
    Validated strictly through Pydantic schema.
    """
    vague_quantities = ["box", "boxes", "pack", "packs", "case", "cases", "several", "crate", "crates"]
    
    is_ambiguous = False
    ambiguity_reason = None
    for vq in vague_quantities:
        if re.search(r"\b" + re.escape(vq) + r"\b", text, re.IGNORECASE):
            is_ambiguous = True
            ambiguity_reason = f"ambiguous quantity: {vq}"
            break

    skus_found = re.findall(r"\b(CAB-1|CAB-2|HUB-1)\b", text, re.IGNORECASE)
    
    numbers = re.findall(r"\b(\d+)\b", text)
    quantity = None
    if not is_ambiguous and numbers:
        quantity = int(numbers[0])
    elif not is_ambiguous:
        word_to_num = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10, "twelve": 12, "fifteen": 15}
        for word, num in word_to_num.items():
            if re.search(r"\b" + word + r"\b", text, re.IGNORECASE):
                quantity = num
                break

    item = ExtractedOrderItem(
        raw_product_text=text,
        raw_quantity_text=str(quantity) if quantity else ("vague" if is_ambiguous else "unspecified"),
        extracted_sku=skus_found[0].upper() if skus_found else None,
        extracted_quantity=quantity if not is_ambiguous else None,
        is_quantity_ambiguous=is_ambiguous,
        ambiguity_reason=ambiguity_reason,
    )

    payload = ExtractionPayload(
        request_id=request_id,
        order_ref=order_ref,
        raw_text=text,
        items=[item],
        confidence=0.85,
        is_cached=False,
        model="rule_based_fallback",
    )
    return payload.model_dump()


def extract_order_information(
    request_id: str,
    order_ref: str,
    text: str,
    force_replay: bool = False,
    cache_dir: str = CACHE_DIR,
) -> Dict[str, Any]:
    """
    Extract order items and quantities from raw text.
    
    1. If force_replay is True, or neither GROQ_API_KEY nor OPENAI_API_KEY is configured,
       loads from pre-saved cached_responses/{request_id}.json.
    2. If API keys are present and force_replay is False, queries the LLM API,
       validates schema strictly with Pydantic, stores to cache, and returns structured data.
    3. If LLM returns an invalid schema or fails, returns an explicit failed status instead of silent guessing.
    """
    groq_key = os.getenv("GROQ_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    # If force_replay or neither API key is available, check cache
    if force_replay or (not groq_key and not openai_key):
        cached = load_cached_response(request_id, cache_dir=cache_dir)
        if cached:
            return cached
        return fallback_rule_based_extractor(request_id, order_ref, text)

    # If cache exists, use cache for fast deterministic execution
    cached = load_cached_response(request_id, cache_dir=cache_dir)
    if cached:
        return cached

    # Attempt live LLM extraction with Groq or OpenAI
    try:
        from openai import OpenAI

        if groq_key:
            client = OpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1")
            model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        else:
            client = OpenAI(api_key=openai_key)
            model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        user_content = f"""Extract order details for request:
Request ID: {request_id}
Order Reference: {order_ref}
Customer text: "{text}"

Return JSON matching schema:
{{
  "request_id": "{request_id}",
  "order_ref": "{order_ref}",
  "raw_text": "{text}",
  "items": [
    {{
      "raw_product_text": "<text>",
      "raw_quantity_text": "<text>",
      "extracted_sku": "<SKU or null>",
      "extracted_quantity": <int or null>,
      "is_quantity_ambiguous": <bool>,
      "ambiguity_reason": "<reason or null>"
    }}
  ],
  "confidence": 0.95
}}
"""
        response = client.chat.completions.create(
            model=model,
            temperature=0.0,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        raw_json = json.loads(content)
        raw_json["is_cached"] = False
        raw_json["model"] = model

        # Strict Pydantic validation
        validated_payload = ExtractionPayload.model_validate(raw_json)
        validated_dict = validated_payload.model_dump()

        save_cached_response(request_id, validated_dict, cache_dir=cache_dir)
        return validated_dict

    except ValidationError as val_err:
        # Schema validation error - do not silently fallback, return explicit failed status
        return {
            "request_id": request_id,
            "order_ref": order_ref,
            "raw_text": text,
            "status": "failed",
            "error_type": "pydantic_validation_error",
            "error_message": str(val_err),
            "is_cached": False,
            "model": model if 'model' in locals() else "unknown",
        }
    except Exception as exc:
        # Model / API call failed
        return {
            "request_id": request_id,
            "order_ref": order_ref,
            "raw_text": text,
            "status": "failed",
            "error_type": "llm_invocation_error",
            "error_message": str(exc),
            "is_cached": False,
            "model": model if 'model' in locals() else "unknown",
        }
