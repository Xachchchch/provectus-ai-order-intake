# AI Workflow Documentation

This document describes the AI tools, models, prompts, failure cases, and reproduction procedures used in developing the **AI Order Intake & Exception Handling Platform**.

---

## 1. Tools and Models

### Development-Time Tools
- **AI Assistant**: Antigravity IDE paired with **Gemini 3.8 Flash (High)**.
- **Role**: Architecture design, deterministic rule synthesis, pytest test suite formulation, Streamlit interface generation, and test verification.

### Application Model Integration
- **LLM Provider**:
  - **Groq API**: `openai/gpt-oss-120b` (fast structured extraction with native Tool Calling).
- **Inference Parameters**:
  - `temperature`: `0.0` (for strict, reproducible extraction).
  - `tools`: `[CATALOG_LOOKUP_TOOL]` (native OpenAI/Groq function calling).
- **Offline Deterministic Replay**:
  - Full suite of pre-recorded extraction artifacts saved under [`cached_responses/`](../cached_responses/) (`R1.json` through `R10.json`).
  - Explicitly labeled with `"is_cached": true` and `"model": "openai/gpt-oss-120b"`.
  - Allows full test suite execution, grading, and demonstration with **zero API keys** or external network dependency.

---

## 2. Configuration Files

| Configuration Item | Path | Purpose |
| :--- | :--- | :--- |
| **System Extraction Prompt** | [`src/extractor.py`](../src/extractor.py) | Enforces strict unit parsing; forbids inferring container sizes (`box`, `pack`). |
| **Domain Specification** | [`tasks/orders/domain.md`](../tasks/orders/domain.md) | Ground-truth pricing, bulk discount, catalog matching, and ambiguity rules. |
| **Replay Cache Files** | [`cached_responses/`](../cached_responses/) | Pre-recorded JSON outputs (`R1.json` - `R10.json`) for zero-key evaluation. |
| **Environment Variable Template** | [`ai-workflow/.env.example`](.env.example) | Sanitized credentials template (`GROQ_API_KEY`, `OPENAI_API_KEY`). |

---

## 3. Workflow Example: LLM Failure & Correction Case

### The Problem / Failure Case
During initial testing with customer request **R3** (*"Send two boxes of the usual cable."*), generic LLM prompts frequently attempted helpful inference:
- The model hallucinated that a "box" contains `10` or `12` units.
- Or it attempted to pick `CAB-1` assuming it was "the usual".
- This violates Rule 1 and Rule 3 of `domain.md` (*"Do not infer how many items a box contains... Unknown products and ambiguous quantities need clarification"*).

### The Correction
We refined the extraction prompt in [`src/extractor.py`](../src/extractor.py) with explicit negative constraints:
```text
CRITICAL RULES:
1. Extract exact product names or SKU codes mentioned.
2. Quantities must be positive whole numbers of individual units.
3. NEVER guess or infer how many items a container contains (e.g. "box", "pack", "crate", "bundle", "case", "several", "a couple").
   If any such vague or container term is used, set "extracted_quantity": null, "is_quantity_ambiguous": true, and "ambiguity_reason" describing the ambiguity.
4. If an exact SKU from the catalog (CAB-1, CAB-2, HUB-1) is identified, populate "extracted_sku", otherwise set "extracted_sku": null.
```

### Verification
When processing `R3`, the extractor produces:
```json
{
  "request_id": "R3",
  "order_ref": "O3",
  "raw_text": "Send two boxes of the usual cable.",
  "items": [
    {
      "raw_product_text": "the usual cable",
      "raw_quantity_text": "two boxes",
      "extracted_sku": null,
      "extracted_quantity": null,
      "is_quantity_ambiguous": true,
      "ambiguity_reason": "ambiguous quantity: box"
    }
  ],
  "confidence": 0.90,
  "is_cached": true,
  "model": "openai/gpt-oss-120b"
}
```
The deterministic engine then flags `O3` as `needs-clarification`, generates a customer email draft asking for exact unit quantities and cable lengths, and blocks premature draft creation.

---

## 4. Reproduce or Replay

No API keys are required to execute and verify the platform.

### Step 1: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 2: Run Pytest Suite (100% Offline Replay)
```bash
pytest tests/test_reference_cases.py -v
```

### Step 3: Run Interactive Streamlit Operations Queue
```bash
streamlit run app.py
```

---

## 5. Decisions and Limitations

- **Decoupled Architecture**: Extraction is performed by an LLM (with cached fallback and Pydantic validation), but all pricing arithmetic, catalog SKU matching, and duplicate blocking are handled by 100% deterministic Python code. This guarantees zero arithmetic hallucination.
- **Explicit Status Distinctions**: System distinguishes between automated `draft` and human-approved `reviewed` orders.
- **Exact Integer Cents**: Floating point errors are completely eliminated by storing integer cents and applying Python's `Decimal(..., rounding=ROUND_HALF_UP)`.
- **Reviewer Audit Trail**: All human manual overrides record previous state, updated state, reviewer username, and timestamp in SQLite (`orders.db`).
