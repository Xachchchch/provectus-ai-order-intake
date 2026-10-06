# Minimum Demonstration Check Results & Verification Report

**Evaluator Note:** All checks executed deterministically under offline replay mode (`cached_responses/`).

| Check # | Scenario / Requirement | Input Request ID | Expected Outcome | Observed Outcome | Status |
| :---: | :--- | :---: | :--- | :--- | :---: |
| **Check 1** | Normal Draft & Volume Discount | R1, R5, R6 | R1: 2x CAB-1 = 4000¢<br>R5: 10x CAB-1 (10% bulk) = 18000¢<br>R6: 12x CAB-2 + 1x HUB-1 = 37400¢ | R1: 4000¢ (draft)<br>R5: 18000¢ (draft)<br>R6: 37400¢ (draft) | **PASSED** |
| **Check 2** | Unknown Product Isolation | R2 | "Moon adapter" unresolved; automated email inquiry drafted | Flagged `UNKNOWN_CATALOG_PRODUCT`; draft saved | **PASSED** |
| **Check 3** | Container Ambiguity Guard | R3, R7, R9 | "two boxes", "a pack", "3 boxes" un-inferred; quantity set to null | Flagged `AMBIGUOUS_CONTAINER_QUANTITY`; Pydantic guard triggered | **PASSED** |
| **Check 4** | Deduplication & Order Isolation | R4 | Same `order_ref: O1` as R1; reuses draft without inflating draft count | Flagged `DUPLICATE_ORDER_REF`; draft count stays 1 | **PASSED** |
| **Check 5** | Human Review & State Persistence | R10 | Reviewer resolves "Solar connectors" to 15x HUB-1; price recalculates to 67500¢; status becomes `reviewed` | Status `reviewed`; total 67500¢; persisted across SQLite restarts | **PASSED** |

---

## Unresolved Failures & Documented Trade-offs
- **Unresolved Product Descriptions (R8):** "USB-C cables" without length variant cannot be resolved without customer clarification and remains unresolved by design.
- **Single Currency Constraint:** All calculations are strictly bound to USD integer cents per `tasks/orders/domain.md`.