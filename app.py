"""Streamlit-based interactive operations queue with status filtering, reviewer corrections, and analytics."""

from collections import Counter
import html
import json
import os
import streamlit as st

from src.catalog import CATALOG
from src.engine import apply_reviewer_correction, batch_process, process_request
from src.ingestion import load_email_requests_from_dir
from src.storage import (
    DEFAULT_DB_PATH,
    get_clarification_draft,
    get_order,
    get_order_by_request_id,
    get_orders_metrics,
    get_review_history,
    init_db,
    list_orders,
)

# Page configuration
st.set_page_config(
    page_title="AI Order Intake & Operations Queue",
    page_icon="📦",
    layout="wide",
)

# Initialize database
init_db()

# Custom CSS styling for polished UI
st.markdown(
    """
    <style>
    .main-title {
        font-size: 2.2rem;
        font-weight: 700;
        color: #1e293b;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        font-size: 1.05rem;
        color: #64748b;
        margin-bottom: 1.5rem;
    }
    .status-badge {
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.82rem;
        display: inline-block;
    }
    .badge-draft { background-color: #dcfce7; color: #15803d; border: 1px solid #bbf7d0; }
    .badge-reviewed { background-color: #e0e7ff; color: #4338ca; border: 1px solid #c7d2fe; }
    .badge-needs-clarification { background-color: #fef3c7; color: #b45309; border: 1px solid #fde68a; }
    .badge-duplicate { background-color: #f1f5f9; color: #475569; border: 1px solid #cbd5e1; }
    .badge-failed { background-color: #fee2e2; color: #b91c1c; border: 1px solid #fca5a5; }
    .cache-tag {
        font-size: 0.75rem;
        padding: 2px 8px;
        border-radius: 4px;
        background-color: #f8fafc;
        color: #64748b;
        border: 1px solid #e2e8f0;
        display: inline-block;
    }
    .evidence-badge {
        font-size: 0.78rem;
        padding: 3px 8px;
        border-radius: 4px;
        background-color: #f0fdf4;
        color: #166534;
        border: 1px solid #bbf7d0;
        margin-right: 6px;
        display: inline-block;
    }
    .order-card {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 1.2rem;
        margin-bottom: 1.2rem;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div class="main-title">📦 AI Order Intake & Exception Handling Queue</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-title">Automated natural language ingestion, strict unit parsing, deterministic pricing, human-in-the-loop exception handling, and operational analytics.</div>',
    unsafe_allow_html=True,
)

# Sidebar
st.sidebar.header("⚙️ Controls & Ingestion")

replay_mode = st.sidebar.toggle("Replay Mode (Offline Cache)", value=True, help="Replay pre-saved extractions without requiring API keys.")

if st.sidebar.button("🚀 Ingest / Process All Email Requests (data/emails/)", type="primary"):
    email_requests = load_email_requests_from_dir("data/emails")
    if not email_requests:
        # Fallback to requests.json if directory is empty
        legacy_path = os.path.join(os.path.dirname(__file__), "data", "requests.json")
        if os.path.exists(legacy_path):
            with open(legacy_path, "r", encoding="utf-8") as f:
                email_requests = json.load(f).get("requests", [])
    
    results = batch_process(email_requests, force_replay=replay_mode)
    st.sidebar.success(f"Successfully processed {len(results)} email requests from data/emails/!")
    st.rerun()

if st.sidebar.button("🧹 Reset Database"):
    if os.path.exists(DEFAULT_DB_PATH):
        os.remove(DEFAULT_DB_PATH)
    init_db()
    st.sidebar.info("Database reset.")
    st.rerun()

# ── Optional Enhancement: Export Finalized Orders ─────────────────────────────
st.sidebar.markdown("---")
st.sidebar.header("📥 Data Export")
reviewed_orders = [o for o in all_orders if o["status"] in ("draft", "reviewed")]
if reviewed_orders:
    export_payload = json.dumps(
        [
            {
                "order_ref": o["order_ref"],
                "request_id": o["request_id"],
                "status": o["status"],
                "line_items": o.get("line_items", []),
                "total_cents": o.get("total_cents", 0),
                "total_usd": f"${o.get('total_cents', 0) / 100:.2f}",
                "updated_at": o.get("updated_at"),
            }
            for o in reviewed_orders
        ],
        indent=2,
    )
    st.sidebar.download_button(
        label="📥 Export Finalized Orders (JSON)",
        data=export_payload,
        file_name="finalized_orders.json",
        mime="application/json",
        help="Export all verified draft and reviewed orders in structured JSON format.",
    )

# Retrieve orders and metrics from DB
all_orders = list_orders()
metrics = get_orders_metrics()

# Top Navigation Tabs
tab_queue, tab_analytics = st.tabs(["📦 Operations Queue", "📊 Analytics & Insights"])

with tab_queue:
    # Metrics summary bar distinguishing valid orders from blocked duplicates
    total_valid = metrics["net_valid"]
    draft_count = metrics["drafts"]
    reviewed_count = metrics["reviewed"]
    clarification_count = metrics["clarifications"]
    duplicate_count = metrics["duplicates"]
    failed_count = metrics["failed"]

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Net Valid Orders", total_valid, help="Active ingested orders excluding blocked duplicates")
    col2.metric("Valid Drafts", draft_count, help="Orders converted to draft without manual review")
    col3.metric("Human Reviewed", reviewed_count, help="Orders confirmed and corrected by operations lead")
    col4.metric("Needs Clarification", clarification_count, help="Orders flagged for customer clarification")
    col5.metric("Duplicates Blocked", duplicate_count, help="Duplicate submissions safely blocked without inflating drafts")

    st.markdown("---")

    # Filter
    filter_status = st.selectbox(
        "Filter by Status:",
        options=["All", "needs-clarification", "draft", "reviewed", "duplicate", "failed"],
        index=0,
    )

    if filter_status == "All":
        filtered_orders = all_orders
    else:
        filtered_orders = [o for o in all_orders if o["status"] == filter_status]

    if not filtered_orders:
        st.info("No orders found for selected filter. Click **'Ingest / Process All Email Requests'** in the sidebar to populate the queue.")

    # Display Orders
    for order in filtered_orders:
        order_ref = order["order_ref"]
        req_id = order["request_id"]
        status = order["status"]
        created_at = order["created_at"]
        raw_text = order["raw_text"]
        notes = order.get("notes", "")
        model_name = order.get("model", "openai/gpt-oss-120b")
        is_cached = order.get("is_cached", True)
        catalog_evidence = order.get("catalog_evidence", [])
        exception_code = order.get("exception_code", "")

        badge_class = f"badge-{status}"
        badge_label = status.upper().replace("-", " ")
        if status == "draft":
            badge_label = "DRAFT (AUTO)"
        elif status == "reviewed":
            badge_label = "REVIEWED (BY HUMAN)"

        cache_label = f"Cached ({model_name})" if is_cached else f"Live API ({model_name})"

        with st.container():
            st.markdown(
                f"""
                <div class="order-card">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                        <div>
                            <span style="font-size: 1.15rem; font-weight: 700;">Order #{html.escape(order_ref)}</span>
                            <span style="font-size: 0.85rem; color: #64748b; margin-left: 8px;">(Request ID: {html.escape(req_id)})</span>
                            <span class="cache-tag" style="margin-left: 6px;">{html.escape(cache_label)}</span>
                        </div>
                        <span class="status-badge {badge_class}">{badge_label}</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # ── TRUE SIDE-BY-SIDE REVIEW INSPECTOR ────────────────────────────
            col_left, col_right = st.columns([1, 1])

            # LEFT COLUMN: Original Request & Catalog Grounding Evidence
            with col_left:
                st.markdown("##### 📄 Original Customer Email")
                st.info(f"\"{raw_text}\"")

                if catalog_evidence:
                    st.markdown("##### 🔍 Supporting Catalog Match Evidence")
                    for ev in catalog_evidence:
                        rule = ev.get("match_rule", "catalog_lookup")
                        ev_text = ev.get("evidence", "")
                        st.caption(f"- `{rule}`: **{ev_text}**")

                if status == "needs-clarification":
                    draft = get_clarification_draft(order_ref)
                    if draft:
                        with st.expander("✉️ Customer Clarification Email Draft", expanded=False):
                            st.text_input("Subject", value=draft["subject"], disabled=True, key=f"s_{order_ref}_{req_id}")
                            st.text_area("Body", value=draft["draft_email"], height=140, disabled=True, key=f"b_{order_ref}_{req_id}")

                elif status == "duplicate":
                    st.warning(f"ℹ️ {notes}")

            # RIGHT COLUMN: Proposed Order, Pricing, & Reviewer Action
            with col_right:
                st.markdown("##### 📦 Proposed Order & Verification")

                if status in ("draft", "reviewed"):
                    line_items = order.get("line_items", [])
                    if line_items:
                        st.table(
                            [
                                {
                                    "SKU": i["sku"],
                                    "Product": i["name"],
                                    "Qty": i["quantity"],
                                    "Unit Price": f"${i['unit_cents']/100:.2f}",
                                    "10% Disc": f"-${i['discount_cents']/100:.2f}",
                                    "Total": f"${i['total_cents']/100:.2f}",
                                }
                                for i in line_items
                            ]
                        )
                    tot1, tot2 = st.columns(2)
                    tot1.metric("Bulk Discount", f"${order.get('discount_cents', 0)/100:.2f}")
                    tot2.metric("Total Payable", f"${order.get('total_cents', 0)/100:.2f} ({order.get('total_cents', 0)}¢)")

                elif status == "needs-clarification":
                    st.error(f"❌ Exception: {notes} (`{exception_code}`)")
                    st.caption("Reviewer must confirm line items to establish payable total.")
                elif status == "failed":
                    st.error(f"⚠️ Processing failed (`{exception_code}`): {notes}")
                    st.caption("No order was proposed. Fix the input file or model access and re-ingest to retry.")

                # Reviewer Form (Works for both Draft and Clarification)
                if status in ("draft", "reviewed", "needs-clarification"):
                    exp_label = "✏️ Confirm & Approve Order" if status == "draft" else "✏️ Resolve Exception & Edit Lines"
                    with st.expander(exp_label, expanded=(status == "needs-clarification")):
                        existing_lines = order.get("line_items", [])
                        state_key = f"lines_{order_ref}_{req_id}"
                        if state_key not in st.session_state:
                            st.session_state[state_key] = [
                                {"sku": item.get("sku", "CAB-1"), "quantity": item.get("quantity", 1)}
                                for item in existing_lines
                            ] or [{"sku": "CAB-1", "quantity": 1}]

                        btn_c1, btn_c2, _ = st.columns([1, 1, 2])
                        if btn_c1.button("➕ Add Line", key=f"add_{state_key}"):
                            st.session_state[state_key].append({"sku": "CAB-1", "quantity": 1})
                            st.rerun()
                        if btn_c2.button("➖ Remove", key=f"rem_{state_key}") and len(st.session_state[state_key]) > 1:
                            st.session_state[state_key].pop()
                            st.rerun()

                        with st.form(key=f"form_{order_ref}_{req_id}"):
                            sku_opts = list(CATALOG.keys())
                            updated_lines = []
                            for idx, it in enumerate(st.session_state[state_key]):
                                c_sku, c_qty = st.columns([2, 1])
                                def_idx = sku_opts.index(it["sku"]) if it["sku"] in sku_opts else 0
                                sel_s = c_sku.selectbox(f"Line {idx+1} SKU", sku_opts, index=def_idx, key=f"s_{state_key}_{idx}")
                                sel_q = c_qty.number_input(f"Qty", min_value=1, value=int(it.get("quantity", 1)), key=f"q_{state_key}_{idx}")
                                updated_lines.append({"sku": sel_s, "quantity": sel_q})

                            r_user = st.text_input("Reviewer Name", value="ops_reviewer", key=f"u_{state_key}")
                            r_comm = st.text_input("Comment", value="Confirmed and approved by operator", key=f"c_{state_key}")

                            if st.form_submit_button("✅ Save & Mark as 'reviewed'", type="primary"):
                                apply_reviewer_correction(order_ref, updated_lines, reviewer=r_user, comment=r_comm)
                                st.session_state.pop(state_key, None)
                                st.success(f"Order #{order_ref} marked as 'reviewed'!")
                                st.rerun()

            # Audit Trail with Diff View
            history = get_review_history(order_ref)
            if history:
                with st.expander(f"📜 Audit History ({len(history)} events)"):
                    for entry in history:
                        st.markdown(f"**{entry['created_at']}** — *{entry['reviewer']}* performed `{entry['action']}`: {entry['comment']}")
                        try:
                            pst = json.loads(entry.get("previous_state") or "{}")
                            nst = json.loads(entry.get("new_state") or "{}")
                            if pst or nst:
                                d1, d2 = st.columns(2)
                                d1.caption("Previous State:")
                                d1.json(pst)
                                d2.caption("New State:")
                                d2.json(nst)
                        except Exception:
                            pass

            st.markdown("<hr style='margin: 1rem 0;'>", unsafe_allow_html=True)


with tab_analytics:
    st.header("📊 Intake Analytics & Operational Insights")
    st.caption("All metrics below are computed dynamically using structured exception_code records in SQLite.")

    total_valid_orders = metrics["net_valid"]
    duplicates_count = metrics["duplicates"]
    total_records = metrics["total_raw"]

    if total_records == 0:
        st.info("The database is currently empty. Ingest requests from the sidebar to view analytics.")
    else:
        auto_drafts = metrics["drafts"]
        reviewed = metrics["reviewed"]
        clarifications = metrics["clarifications"]
        failed = metrics["failed"]

        kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
        kpi1.metric("Zero-Touch Drafts", f"{auto_drafts} ({auto_drafts/total_valid_orders*100:.0f}%)" if total_valid_orders else "0")
        kpi2.metric("Human Reviewed", f"{reviewed} ({reviewed/total_valid_orders*100:.0f}%)" if total_valid_orders else "0")
        kpi3.metric("Clarifications", f"{clarifications} ({clarifications/total_valid_orders*100:.0f}%)" if total_valid_orders else "0")
        kpi4.metric("Duplicates / Amendments", f"{duplicates_count} dup / {metrics['amendments']} amended")
        kpi5.metric("Failures", f"{failed}")

        st.markdown("---")

        col_chart, col_recommendation = st.columns([1, 1])

        with col_chart:
            st.subheader("🔍 Structured Exception Code Breakdown")

            # Count directly by structured exception_code from database
            code_counts = Counter(o.get("exception_code", "") for o in all_orders if o.get("exception_code"))

            box_pack = code_counts.get("AMBIGUOUS_CONTAINER_QUANTITY", 0)
            unknown_prod = code_counts.get("UNKNOWN_CATALOG_PRODUCT", 0)
            ambiguous_prod = code_counts.get("AMBIGUOUS_PRODUCT_DESCRIPTION", 0)
            amended_conflict = code_counts.get("AMENDED_ORDER_REF_CONFLICT", 0)
            dup_code = code_counts.get("DUPLICATE_ORDER_REF", 0)

            categorized_breakdown = {
                "Container Ambiguity ('box'/'pack') [AMBIGUOUS_CONTAINER_QUANTITY]": box_pack,
                "Unknown Catalog Product [UNKNOWN_CATALOG_PRODUCT]": unknown_prod,
                "Ambiguous Description (multiple SKUs) [AMBIGUOUS_PRODUCT_DESCRIPTION]": ambiguous_prod,
                "Conflicting Amendment [AMENDED_ORDER_REF_CONFLICT]": amended_conflict,
                "Duplicate Order Reference [DUPLICATE_ORDER_REF]": dup_code,
            }

            for cause, count in categorized_breakdown.items():
                if count > 0:
                    pct = (count / total_records) * 100
                    st.write(f"**{cause}**: {count} requests ({pct:.0f}%)")
                    st.progress(pct / 100)

        with col_recommendation:
            st.subheader("💡 Actionable Business Process Improvement")
            st.info(
                f"""
                **Evidence from Live Email Intake Data:**
                - **{box_pack} exceptions ({box_pack/total_records*100:.0f}% of volume)** stem from customer container jargon (*"boxes"*, *"packs"*).
                - **{unknown_prod} exceptions** stem from unlisted items or vague descriptions.

                **Practical Process Improvement (Email Workflow):**
                1. **Automated Unit Clarification Macro:** For container exceptions (R3, R7, R9), instantly auto-respond asking for the exact count of single items (e.g., *"How many individual CAB-1 cables do you need?"*).
                2. **Customer Packaging Translation Tables:** Establish account-level pack mappings only where a customer has confirmed packaging unit counts in writing (proposal for operational review).
                """
            )
