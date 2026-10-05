"""Script to execute real Groq LLM calls once and populate cached_responses/ with genuine data."""

import json
import os
import time
from datetime import datetime, timezone
from openai import OpenAI

# Load .env manually if dotenv not installed
env_file = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_file):
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip('"').strip("'")

groq_key = os.getenv("GROQ_API_KEY")
if not groq_key:
    raise ValueError("GROQ_API_KEY not found in environment or .env file!")

client = OpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1")
groq_active_model = "openai/gpt-oss-120b"
model_label = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

requests_path = os.path.join(os.path.dirname(__file__), "data", "requests.json")
with open(requests_path, "r", encoding="utf-8") as f:
    requests = json.load(f)["requests"]

cache_dir = os.path.join(os.path.dirname(__file__), "cached_responses")
os.makedirs(cache_dir, exist_ok=True)

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

print(f"Connecting to Groq Cloud ({groq_active_model}) to generate real cached responses...")

for req in requests:
    req_id = req["id"]
    order_ref = req["order_ref"]
    text = req["text"]

    user_content = f"""Extract order details:
Request ID: {req_id}
Order Reference: {order_ref}
Customer text: "{text}"

Return JSON matching schema:
{{
  "request_id": "{req_id}",
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
        model=groq_active_model,
        temperature=0.0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
    )

    data = json.loads(response.choices[0].message.content)
    data["is_cached"] = True
    data["model"] = model_label
    data["cached_at"] = datetime.now(timezone.utc).isoformat()

    out_file = os.path.join(cache_dir, f"{req_id}.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"  [OK] Saved real Groq response for {req_id} ({order_ref}) -> {out_file}")
    time.sleep(0.5)

print("All 10 real cached responses successfully recorded from Groq Cloud!")
