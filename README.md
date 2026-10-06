# AI Order Intake & Exception Handling Platform
**Junior AI Engineer Assessment — Alternative A**

A production-grade, deterministic AI Order Intake pipeline that parses unstructured natural language purchase requests from individual email text files, validates items against an official product catalog using an isolated lookup tool with explicit evidence persistence, applies bulk discount pricing with integer cents arithmetic, flags ambiguities/unknowns with automated inquiry email drafts, prevents duplicate orders, and provides an interactive Streamlit operations queue with dynamic multi-line reviewer corrections and structured database analytics.

---

## 🚀 Key Features & Domain Compliance

All domain specifications from [`tasks/orders/domain.md`](tasks/orders/domain.md) and platform requirements are strictly enforced:

1. **Individual Email File Ingestion Pipeline**:
   - Ingests short email-style text files directly from [`data/emails/`](data/emails/) (`R1_O1.txt` through `R10_O10.txt`).
   - Parses RFC-style headers (`Order-Ref`, `Request-ID`, `Subject`) and body text, preserving each original request with a stable identity and metadata.
2. **Local Catalog Lookup Tool with Explicit Evidence Persistence**:
   - The extraction model is strictly coupled with a local catalog lookup tool (`lookup_catalog_tool`).
   - Categorizes matching rules: `exact_sku`, `unambiguous_alias`, `ambiguous_multi_match`, `unknown_product`.
   - Records and persists supporting catalog entries directly in SQLite (`orders.catalog_evidence_json`) and renders evidence badges in the Streamlit UI.
3. **Deterministic Integer Cents Arithmetic**:
   - All monetary amounts are handled strictly as integer cents (no floating-point rounding errors).
   - Line items with quantity $\ge 10$ receive a 10% discount on that line only.
   - Half-cents are rounded to the nearest cent using `decimal.ROUND_HALF_UP`.
4. **No Guessing of Packaging or Units**:
   - Container terms (*"box"*, *"pack"*, *"several"*, *"case"*) are strictly prohibited from being converted or guessed as unit counts. They are immediately flagged as `needs-clarification`.
5. **Automated Clarification Drafts**:
   - Unknown products, ambiguous quantities, or conflicting order revisions automatically generate customer-ready inquiry email drafts explaining the issue and offering catalog options.
6. **Duplicate Prevention & Amendment Detection**:
   - Identical re-submissions (`order_ref` + identical text) are identified immediately as `duplicate`, safely recorded without creating new drafts or inflating order counts.
   - Non-identical submissions with the same `order_ref` are recognized as conflicting amendments and flagged for manual review (`AMENDED_ORDER_REF_CONFLICT`).
7. **Dynamic Multi-Line Reviewer Correction**:
   - In the Streamlit UI, reviewers can adjust, add, or remove multiple line items simultaneously, recalculate deterministic bulk pricing across all lines, and transition status to `reviewed`.
   - Audit trail is immutably preserved in `review_history`.
8. **Structured Exception Codes & Honest Analytics**:
   - Stores standardized enum codes in SQLite (`orders.exception_code`):
     - `CLEAN_DRAFT`, `AMBIGUOUS_CONTAINER_QUANTITY`, `UNKNOWN_CATALOG_PRODUCT`, `AMBIGUOUS_PRODUCT_DESCRIPTION`, `DUPLICATE_ORDER_REF`, `AMENDED_ORDER_REF_CONFLICT`, `EXTRACTION_FAILED`.
   - Analytics metrics and charts are computed directly from the database without fragile free-text regex.
9. **Zero-Key Offline Replay**:
   - Genuine pre-saved responses in `cached_responses/` allow offline evaluation without API keys.

---

## 📁 Repository Structure

```text
client-ai-starter-pack/
├── app.py                         # Streamlit operations queue, multi-line correction & analytics
├── cached_responses/              # Real Groq LLM extraction responses with cache labeling (R1 - R10)
├── data/
│   ├── emails/                    # Individual email request files (R1_O1.txt - R10_O10.txt)
│   ├── requests.json              # Structured test order requests
│   └── expected_results.json      # Ground truth expected outputs
├── src/
│   ├── __init__.py                # Package declaration & tool exports
│   ├── catalog.py                 # Official catalog, deterministic matcher & lookup_catalog_tool
│   ├── engine.py                  # Core processing engine, exception codes & email draft generator
│   ├── extractor.py               # LLM extractor with Pydantic validation & cache labeling
│   ├── ingestion.py               # Email file ingestion pipeline (load_email_requests_from_dir)
│   ├── pricing.py                 # Integer cents arithmetic & ROUND_HALF_UP discount calculation
│   └── storage.py                 # SQLite database layer, audit history & manual corrections
├── tasks/orders/
│   ├── domain.md                  # Exercise rules & worked example
│   ├── seed.json                  # Seed data
│   └── expected-seed-results.json # Initial seed expectations
├── tests/
│   └── test_reference_cases.py    # Pytest suite verifying all checks (21/21 passing)
├── ai-workflow/
│   ├── manifest.json              # AI workflow configuration manifest
│   ├── README.md                  # Workflow, prompt engineering & failure correction case
│   └── .env.example               # Environment variables template (Groq / OpenAI)
├── pyproject.toml                 # Pytest configuration
├── requirements.txt               # Python dependencies (pytest, streamlit, openai, pydantic)
└── README.md                      # Platform documentation
```

---

## 🏗️ Architecture: Native LLM Function Calling

### Agentic Tool-Use Loop (`src/extractor.py`)

The extractor implements true **native function calling** per the OpenAI/Groq tool-use API — not a post-hoc Python dispatch after JSON extraction:

```
User Request Text
       │
       ▼
┌─────────────────────────────┐
│  LLM (llama-3.3-70b /       │ ← tools=[CATALOG_LOOKUP_TOOL]
│   gpt-4o-mini)              │
└──────────┬──────────────────┘
           │ finish_reason="tool_calls"
           ▼
  lookup_catalog(query="USB hub")   ← local Python function
           │
           ▼  tool role message
┌─────────────────────────────┐
│  LLM (final answer turn)    │ ← finish_reason="stop"
└──────────┬──────────────────┘
           │
           ▼
  Pydantic ExtractionPayload  ← strict schema validation
  + tool_calls_log persisted in SQLite
```

### Pydantic Container-Term Guardrail

A `@model_validator(mode="after")` on `ExtractedOrderItem` deterministically intercepts any hallucinated integer for container-term quantities:

```python
CONTAINER_TERMS = {"box", "boxes", "pack", "packs", "crate", ...}
# If the model outputs extracted_quantity=12 for "a box of cables",
# the validator resets it to None and sets is_quantity_ambiguous=True.
```

### Strict Error Policy (No Silent Regex Fallback)

| Condition | Behaviour |
|---|---|
| Cache hit | Serve cached payload (always preferred) |
| API key present, no cache | Live LLM call with tool-use → cache result |
| No cache + no API key | Raise `ExtractionError` → order saved as `failed / EXTRACTION_FAILED` |

The `fallback_rule_based_extractor` has been **permanently removed**. Failures are explicit and visible in the UI analytics.

---

## 🛠️ Quickstart & Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run Test Suite (Zero-Key Offline Mode)
```bash
pytest tests/test_reference_cases.py -v
```

### 3. Launch the Interactive Operations Queue
```bash
streamlit run app.py
```
Open your browser to `http://localhost:8501`. You can:
- Ingest all email requests from `data/emails/` with a single click.
- Filter orders by status (`draft`, `reviewed`, `needs-clarification`, `duplicate`, `failed`).
- View line items, bulk discounts, and calculated totals in integer cents.
- Inspect auto-generated inquiry email drafts and supporting **Catalog Match Evidence**.
- Use the **Multi-Line Reviewer Correction Form** to resolve exceptions, add/remove lines, trigger deterministic re-pricing, and view the audit trail.
- View the **Analytics & Insights** tab to inspect dynamic exception breakdowns powered by structured SQLite `exception_code` values.

---

## 🧪 Verification Results

The pytest suite in [`tests/test_reference_cases.py`](tests/test_reference_cases.py) directly implements all checks specified in the brief:

| Check | Description | Test Method | Status |
| :--- | :--- | :--- | :---: |
| **Check 1** | Normal request & bulk discount calculation | `test_normal_order_r1`, `test_bulk_discount_r5`, `test_bulk_discount_multi_line_r6`, `test_round_half_up_rule` | **PASSED** |
| **Check 2** | Unknown product flagged with clarification draft | `test_unknown_product_r2` | **PASSED** |
| **Check 3** | Ambiguous quantity ('box'/'pack') flagged, not guessed | `test_box_quantity_r3`, `test_pack_quantity_r7`, `test_box_quantity_known_sku_r9` | **PASSED** |
| **Check 4** | Duplicate request blocked without new draft creation | `test_duplicate_order_ref_blocked` | **PASSED** |
| **Check 5** | Reviewer correction sets status to 'reviewed', reruns pricing & persists | `test_reviewer_correction_and_persistence` | **PASSED** |
| **Schema** | Pydantic model validation on extraction schemas | `test_pydantic_schema_validation` | **PASSED** |
| **Full Suite** | All 10 requests match `expected_results.json` end-to-end | `test_all_10_requests_end_to_end` | **PASSED** |
| **Idempotency** | Re-ingesting requests preserves reviewer work without overwrite | `test_reprocessing_idempotency_does_not_overwrite_reviewed` | **PASSED** |
| **Error Handling** | Unhandled LLM failure creates explicit 'failed' status | `test_failed_extraction_path_emits_failed_status` | **PASSED** |
| **Email Files** | Ingestion from individual .txt email files with headers and body | `test_load_email_requests_from_dir` | **PASSED** |
| **Catalog Evidence** | Dedicated local catalog tool & explicit evidence persistence | `test_catalog_evidence_persisted` | **PASSED** |
| **Multi-Line Review** | Reviewer corrections update multiple lines without dropping items | `test_multi_line_reviewer_correction_preserves_all_lines` | **PASSED** |
| **Exception Codes** | Structured SQLite exception_code values assigned for all conditions | `test_structured_exception_codes_assigned` | **PASSED** |
| **Amendment Rule** | Identical re-send -> duplicate; conflicting amendment -> clarification | `test_identical_vs_conflicting_amendment` | **PASSED** |
| **Immutability** | Database updates strictly preserve original created_at timestamp | `test_created_at_immutability_on_update` | **PASSED** |
| **Tool Loop** | Native multi-turn LLM function-calling execution with mocked client | `test_native_tool_calling_execution_loop` | **PASSED** |

**Summary: 21 passed in ~1.4s (100% pass rate).**

---

## ⏱️ Time Spent & Assumptions

### Time Investment (~7 hours total):
- **Data Preparation & Validation (1h):** Analyzing domain rules, extending seed to 10 comprehensive cases, creating individual email text files with headers.
- **Core Processing Engine (2.5h):** Pydantic schema validation, local catalog lookup tool with evidence tracking, integer cents arithmetic with `ROUND_HALF_UP`, and SQLite storage.
- **LLM Integration & Real Replay (1.5h):** Live Groq API calls (`llama-3.3-70b-versatile`), caching provenance, idempotency guard, and explicit error handling.
- **UI & Analytics Dashboard (1.25h):** Streamlit review queue, multi-line reviewer correction forms, supporting catalog evidence display, and structured database-backed analytics.
- **Testing & Documentation (45m):** 20 comprehensive pytest cases, AI workflow manifest, and failure incident documentation.

### Data Assumptions & Rule Ambiguities Recorded:
1. **Container Rule (Rule 1):** In accordance with `domain.md`, container terms (*"box"*, *"pack"*, *"crate"*) have no stated unit counts and are strictly never guessed.
2. **"Usual Cable" Ambiguity (Rule 3):** Handled as ambiguous between `CAB-1` (1 m) and `CAB-2` (2 m) because the catalog provides no prior customer purchase history.
3. **Reprocessing Duplicate Rule (Rule 4):** Identical `order_ref` values are recorded as `duplicate` for operations queue visibility, but do not create new drafts or inflate totals. Conflicting submissions with the same `order_ref` are flagged as `AMENDED_ORDER_REF_CONFLICT`.

### Known Limitations:
- **Single Currency:** Operates exclusively in USD integer cents; multi-currency exchange rates are out of current scope.
- **Input Modality:** Processes plain text and email files; image and PDF attachments require an external OCR/multimodal module.
