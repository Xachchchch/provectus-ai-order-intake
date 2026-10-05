# AI Order Intake & Exception Handling Platform
**Junior AI Engineer Assessment — Alternative A**

A production-grade, deterministic AI Order Intake pipeline that parses unstructured natural language purchase requests, validates items against an official product catalog, applies bulk discount pricing with integer cents arithmetic, flags ambiguities/unknowns with automated inquiry email drafts, prevents duplicate orders, and provides an interactive Streamlit operations queue with human reviewer corrections and analytics.

---

## 🚀 Key Features & Domain Compliance

All domain specifications from [`tasks/orders/domain.md`](tasks/orders/domain.md) are strictly enforced:

1. **Deterministic Integer Cents Arithmetic**:
   - All monetary amounts are handled strictly as integer cents (no floating-point rounding errors).
   - Line items with quantity $\ge 10$ receive a 10% discount on that line only.
   - Half-cents are rounded to the nearest cent using `decimal.ROUND_HALF_UP`.
2. **Catalog Matching**:
   - Matches products against official catalog items (`CAB-1` @ 2000¢, `CAB-2` @ 3000¢, `HUB-1` @ 5000¢) via exact SKU or unambiguous description.
   - Ambiguous mentions (e.g. *"USB-C cables"* without length) are flagged as `needs-clarification`.
3. **No Guessing of Packaging or Units**:
   - Container terms (*"box"*, *"pack"*, *"several"*, *"case"*) are strictly prohibited from being converted or guessed as unit counts. They are immediately flagged as `needs-clarification`.
4. **Automated Clarification Drafts**:
   - Unknown products or ambiguous quantities automatically generate customer-ready inquiry email drafts explaining the issue and offering catalog options.
5. **Duplicate Order Prevention**:
   - Identical `order_ref` values are detected immediately and marked as `duplicate`. No secondary draft is created and order counts remain uninflated.
6. **Distinction Between Valid Drafts & Human-Reviewed Orders**:
   - Automated structurally valid orders receive `draft` status.
   - Once a human reviewer manually corrects and approves an order, its status is updated to `reviewed`, strictly distinguishing it from automated unreviewed drafts.
7. **Pydantic Validation & Explicit Error Handling**:
   - Strict Pydantic models validate LLM extractions. Model errors or unparseable schemas result in an explicit `failed` status rather than silent fallbacks.
8. **Explicit Cache Labeling & Zero-Key Offline Replay**:
   - Cached responses are explicitly labeled (`"is_cached": true`, `"model": "llama-3.3-70b-versatile"`). The entire suite runs with zero API keys required.
9. **Analytics & Process Improvement**:
   - Dedicated dashboard view visualizing exception root causes and providing actionable operational recommendations.

---

## 📁 Repository Structure

```text
client-ai-starter-pack/
├── app.py                         # Streamlit operations queue, reviewer correction & analytics
├── cached_responses/              # Pre-saved JSON extraction responses with cache labeling (R1.json - R10.json)
├── data/
│   ├── requests.json              # 10 comprehensive test order requests (R1 to R10)
│   └── expected_results.json      # Ground truth expected outputs
├── src/
│   ├── __init__.py                # Package declaration
│   ├── catalog.py                 # Official catalog and deterministic product matcher
│   ├── engine.py                  # Core processing engine & email draft generator
│   ├── extractor.py               # LLM extractor with Pydantic validation & cache labeling
│   ├── pricing.py                 # Integer cents arithmetic & ROUND_HALF_UP discount calculation
│   └── storage.py                 # SQLite database layer, audit history & manual corrections
├── tasks/orders/
│   ├── domain.md                  # Exercise rules & worked example
│   ├── seed.json                  # Seed data
│   └── expected-seed-results.json # Initial seed expectations
├── tests/
│   └── test_reference_cases.py    # Pytest suite verifying all 5 required checks (12/12 passing)
├── ai-workflow/
│   ├── manifest.json              # AI workflow configuration manifest
│   ├── README.md                  # Workflow, prompt engineering & failure correction case
│   └── .env.example               # Environment variables template (Groq / OpenAI)
├── flatten_codebase.py            # Codebase flattener utility
├── pyproject.toml                 # Pytest configuration
├── requirements.txt               # Python dependencies (pytest, streamlit, openai, pydantic)
└── README.md                      # Platform documentation
```

---

## 🛠️ Quickstart & Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the Verification Tests
To run the full suite verifying all 5 checks across all reference cases:
```bash
pytest tests/test_reference_cases.py -v
```

### 3. Launch the Interactive Operations Queue
```bash
streamlit run app.py
```
Open your browser to `http://localhost:8501`. You can:
- Ingest all 10 seed requests with a single click.
- Filter orders by status (`draft`, `reviewed`, `needs-clarification`, `duplicate`, `failed`).
- View line items, bulk discounts, and calculated totals in integer cents.
- Inspect auto-generated inquiry email drafts for flagged orders.
- Use the **Inline Reviewer Correction Form** to correct an exception (e.g. resolve `O10` from `Solar connectors` to `HUB-1`), trigger deterministic re-pricing, transition status to `reviewed`, and view the audit trail.
- View the **Analytics & Insights** tab to inspect exception rates, root causes, and operational recommendations.

---

## 🧪 Verification Results

The pytest suite in [`tests/test_reference_cases.py`](tests/test_reference_cases.py) directly implements all 5 checks specified in the brief:

| Check | Description | Test Method | Status |
| :--- | :--- | :--- | :---: |
| **Check 1** | Normal request & bulk discount calculation | `test_normal_order_r1`, `test_bulk_discount_r5`, `test_bulk_discount_multi_line_r6`, `test_round_half_up_rule` | **PASSED** |
| **Check 2** | Unknown product flagged with clarification draft | `test_unknown_product_r2` | **PASSED** |
| **Check 3** | Ambiguous quantity ('box'/'pack') flagged, not guessed | `test_box_quantity_r3`, `test_pack_quantity_r7`, `test_box_quantity_known_sku_r9` | **PASSED** |
| **Check 4** | Duplicate request blocked without new draft creation | `test_duplicate_order_ref_blocked` | **PASSED** |
| **Check 5** | Reviewer correction sets status to 'reviewed', reruns pricing & persists | `test_reviewer_correction_and_persistence` | **PASSED** |
| **Schema** | Pydantic model validation on extraction schemas | `test_pydantic_schema_validation` | **PASSED** |
| **Full Suite** | All 10 requests match `expected_results.json` end-to-end | `test_all_10_requests_end_to_end` | **PASSED** |

**Summary: 12 passed in ~1.6s (100% pass rate).**
