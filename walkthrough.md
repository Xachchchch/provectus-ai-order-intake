# 3-Minute Platform Walkthrough: AI Order Intake

## 1. Problem & Business Context
Distributor customers submit purchase requests via free-text emails. The platform automatically converts clear requests into draft orders, enforces integer-cents pricing and volume discounts, isolates packaging ambiguity (*"boxes"*, *"packs"*), and escalates exceptions to an interactive human reviewer queue.

## 2. Key Architecture Decisions
- **File Ingestion:** Ingests individual RFC-style email files from `data/emails/` with fault-tolerant exception isolation.
- **Native Tool Calling:** Uses `openai/gpt-oss-120b` with native Function Calling (`lookup_catalog`) to ground proposed SKUs in the catalog.
- **Pydantic Guardrail:** Model-level `@model_validator` intercepts container terms, resetting ambiguous quantities to `None`.
- **Deduplication:** Repeated requests sharing an `order_ref` reuse existing drafts without creating secondary order rows in SQLite.
- **Human-in-the-Loop:** Streamlit UI enables multi-line reviewer edits, displays catalog match evidence, and renders before/after diffs in the audit history.

## 3. Findings & Operational Improvement
- **Root Cause:** 60% of intake exceptions stem from informal container terms (*"boxes"* without piece counts).
- **Process Recommendation:** Implement automated email reply macros and account-level box-size translation tables to achieve >85% zero-touch fulfillment.