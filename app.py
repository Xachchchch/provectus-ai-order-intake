"""Streamlit-based interactive operations queue with status filtering, reviewer corrections, and analytics."""

from collections import Counter
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

st.sidebar.markdown("---")
st.sidebar.header("📚 Official Product Catalog")
for sku, item in CATALOG.items():
    st.sidebar.markdown(f"**{sku}**: {item.name} — `${item.unit_cents / 100:.2f}` ({item.unit_cents}¢)")
st.sidebar.caption("Bulk Rule: >=10 units per line receives 10% discount (rounded HALF_UP).")

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

        cache_label = f"Cached Replay ({model_name})" if is_cached else f"Live API ({model_name})"

        with st.container():
            st.markdown(
                f"""
                <div class="order-card">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <div>
                            <span style="font-size: 1.2rem; font-weight: 700; color: #0f172a;">Order {order_ref}</span>
                            <span style="font-size: 0.9rem; color: #64748b; margin-left: 10px;">(Request ID: {req_id})</span>
                            <span class="cache-tag" style="margin-left: 8px;">{cache_label}</span>
                        </div>
                        <span class="status-badge {badge_class}">{badge_label}</span>
                    </div>
                    <div style="color: #334155; font-size: 0.95rem; margin-bottom: 10px;">
                        <strong>Customer Request:</strong> <em>"{raw_text}"</em>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # Details per status
            if status in ("draft", "reviewed"):
                line_items = order.get("line_items", [])
                if line_items:
                    table_data = []
                    for item in line_items:
                        table_data.append(
                            {
                                "SKU": item["sku"],
                                "Product Name": item["name"],
                                "Quantity": item["quantity"],
                                "Unit Price": f"${item['unit_cents'] / 100:.2f}",
                                "Gross": f"${item['gross_cents'] / 100:.2f}",
                                "10% Bulk Discount": f"-${item['discount_cents'] / 100:.2f}" if item['discount_cents'] > 0 else "$0.00",
                                "Net Total": f"${item['total_cents'] / 100:.2f}",
                            }
                        )
                    st.table(table_data)

                # Dedicated Catalog Evidence View
                if catalog_evidence:
                    with st.expander("🔍 Supporting Catalog Match Evidence", expanded=False):
                        for ev in catalog_evidence:
                            ev_text = ev.get("evidence", "")
                            rule = ev.get("match_rule", "catalog_lookup")
                            st.markdown(f"- `<{rule}>` **{ev_text}**")

                tot_col1, tot_col2, tot_col3 = st.columns([2, 1, 1])
                tot_col1.caption(f"Created: {created_at} | Exception Code: {exception_code or 'CLEAN_DRAFT'} | {notes}")
                tot_col2.metric("Total Discount", f"${order.get('discount_cents', 0) / 100:.2f}")
                tot_col3.metric("Final Total", f"${order.get('total_cents', 0) / 100:.2f} ({order.get('total_cents', 0)}¢)")

                # ── Staff Review, Correction & Approval Form ──────────────────
                expander_label = (
                    f"✏️ Staff Review, Correction & Approval Form (Transition to 'reviewed')"
                    if status == "draft"
                    else f"✏️ Re-Review / Edit Approved Order {order_ref}"
                )
                with st.expander(expander_label, expanded=False):
                    st.write(
                        "Confirm or adjust line items below, then click **Confirm Review & Approve** "
                        "to mark this order as `reviewed` by a human operator:"
                    )

                    existing_lines = order.get("line_items", [])
                    default_lines_count = max(1, len(existing_lines))

                    # Initialize session state for draft line items if not present
                    state_key = f"lines_{order_ref}_{req_id}"
                    if state_key not in st.session_state:
                        st.session_state[state_key] = [
                            {"sku": item.get("sku", "CAB-1"), "quantity": item.get("quantity", 1)}
                            for item in existing_lines
                        ] or [{"sku": "CAB-1", "quantity": 1}]

                    current_item_count = len(st.session_state[state_key])

                    # Controls to Add / Remove lines without losing entered values
                    col_b1, col_b2, col_info = st.columns([1, 1, 3])
                    if col_b1.button("➕ Add Item Line", key=f"add_{state_key}"):
                        st.session_state[state_key].append({"sku": "CAB-1", "quantity": 1})
                        st.rerun()
                    if col_b2.button("➖ Remove Line", key=f"rem_{state_key}") and current_item_count > 1:
                        st.session_state[state_key].pop()
                        st.rerun()
                    col_info.caption(f"Managing **{current_item_count}** line item(s).")

                    with st.form(key=f"draft_approval_form_{order_ref}_{req_id}"):
                        corrected_items_draft = []
                        sku_options = list(CATALOG.keys())

                        for i, item_data in enumerate(st.session_state[state_key]):
                            st.markdown(f"**Item Line {i + 1}**")
                            c1, c2 = st.columns([2, 1])

                            curr_sku = item_data.get("sku", "CAB-1")
                            default_sku_idx = sku_options.index(curr_sku) if curr_sku in sku_options else 0
                            default_qty = int(item_data.get("quantity", 1))

                            line_sku = c1.selectbox(
                                f"Catalog Item (Line {i + 1})",
                                options=sku_options,
                                index=default_sku_idx,
                                format_func=lambda s: f"{s} - {CATALOG[s].name} (${CATALOG[s].unit_cents/100:.2f})",
                                key=f"dsku_{order_ref}_{req_id}_{i}",
                            )
                            line_qty = c2.number_input(
                                f"Quantity (Line {i + 1})",
                                min_value=1,
                                max_value=1000,
                                value=default_qty,
                                step=1,
                                key=f"dqty_{order_ref}_{req_id}_{i}",
                            )
                            corrected_items_draft.append({"sku": line_sku, "quantity": line_qty})

                        d3, d4 = st.columns([1, 2])
                        reviewer_name_draft = d3.text_input(
                            "Reviewer Username",
                            value="reviewer_ops",
                            key=f"drev_{order_ref}_{req_id}",
                        )
                        reviewer_note_draft = d4.text_input(
                            "Approval Comment",
                            value="Operator reviewed and confirmed draft order",
                            key=f"dcom_{order_ref}_{req_id}",
                        )

                        approve_btn = st.form_submit_button(
                            "✅ Confirm Review & Approve Order (Mark as 'reviewed')",
                            type="primary",
                        )

                        if approve_btn:
                            apply_reviewer_correction(
                                order_ref=order_ref,
                                corrected_items=corrected_items_draft,
                                reviewer=reviewer_name_draft,
                                comment=reviewer_note_draft,
                            )
                            st.session_state.pop(state_key, None)
                            st.success(f"✅ Order {order_ref} approved and marked as 'reviewed'!")
                            st.rerun()

            elif status == "duplicate":
                st.info(f"ℹ️ **Duplicate Handled**: {notes} (Exception Code: `{exception_code}`)")

            elif status == "needs-clarification":
                st.warning(f"⚠️ **Exception Flagged**: {notes} (Exception Code: `{exception_code}`)")

                # Show draft inquiry email
                draft = get_clarification_draft(order_ref)
                if draft:
                    with st.expander("✉️ View Customer Clarification Email Draft", expanded=False):
                        st.text_input("Subject", value=draft["subject"], disabled=True, key=f"subj_{order_ref}_{req_id}")
                        st.text_area("Email Body", value=draft["draft_email"], height=200, disabled=True, key=f"body_{order_ref}_{req_id}")

                # Catalog Lookup Evidence for Exception
                if catalog_evidence:
                    with st.expander("🔍 Catalog Lookup Findings", expanded=False):
                        for ev in catalog_evidence:
                            st.markdown(f"- **Query**: *{ev.get('query')}* — Result: `{ev.get('match_rule')}`: {ev.get('evidence')}")

                # Multi-Line Human Reviewer Correction Form
                with st.expander(f"✏️ Manual Multi-Line Reviewer Correction for {order_ref}", expanded=True):
                    st.write("Resolve this exception by specifying confirmed catalog items and quantities across all order lines (updates status to **'reviewed'**):")

                    existing_lines = order.get("line_items", [])

                    # Initialize session state for clarification line items
                    corr_state_key = f"corr_lines_{order_ref}_{req_id}"
                    if corr_state_key not in st.session_state:
                        st.session_state[corr_state_key] = [
                            {"sku": item.get("sku", "CAB-1"), "quantity": item.get("quantity", 1)}
                            for item in existing_lines
                        ] or [{"sku": "CAB-1", "quantity": 1}]

                    current_corr_count = len(st.session_state[corr_state_key])

                    # Controls to Add / Remove lines without losing entered values
                    col_c1, col_c2, col_cinfo = st.columns([1, 1, 3])
                    if col_c1.button("➕ Add Item Line", key=f"add_{corr_state_key}"):
                        st.session_state[corr_state_key].append({"sku": "CAB-1", "quantity": 1})
                        st.rerun()
                    if col_c2.button("➖ Remove Line", key=f"rem_{corr_state_key}") and current_corr_count > 1:
                        st.session_state[corr_state_key].pop()
                        st.rerun()
                    col_cinfo.caption(f"Managing **{current_corr_count}** line item(s).")

                    with st.form(key=f"correction_form_{order_ref}_{req_id}"):
                        corrected_items_input = []
                        sku_options = list(CATALOG.keys())

                        for i, item_data in enumerate(st.session_state[corr_state_key]):
                            st.markdown(f"**Item Line {i+1}**")
                            c1, c2 = st.columns([2, 1])

                            curr_sku = item_data.get("sku", "CAB-1")
                            default_sku_idx = sku_options.index(curr_sku) if curr_sku in sku_options else 0
                            default_qty = int(item_data.get("quantity", 1))

                            line_sku = c1.selectbox(
                                f"Catalog Item (Line {i+1})",
                                options=sku_options,
                                index=default_sku_idx,
                                format_func=lambda s: f"{s} - {CATALOG[s].name} (${CATALOG[s].unit_cents/100:.2f})",
                                key=f"sku_{order_ref}_{req_id}_{i}",
                            )
                            line_qty = c2.number_input(
                                f"Quantity (Line {i+1})",
                                min_value=1,
                                max_value=1000,
                                value=default_qty,
                                step=1,
                                key=f"qty_{order_ref}_{req_id}_{i}",
                            )
                            corrected_items_input.append({"sku": line_sku, "quantity": line_qty})

                        c3, c4 = st.columns([1, 2])
                        reviewer_name = c3.text_input("Reviewer Username", value="reviewer_ops", key=f"rev_{order_ref}_{req_id}")
                        reviewer_note = c4.text_input("Correction Comment", value="Customer confirmed SKU and unit count via support", key=f"com_{order_ref}_{req_id}")

                        submit_btn = st.form_submit_button("✅ Apply Multi-Line Correction & Recalculate Pricing", type="primary")

                        if submit_btn:
                            apply_reviewer_correction(
                                order_ref=order_ref,
                                corrected_items=corrected_items_input,
                                reviewer=reviewer_name,
                                comment=reviewer_note,
                            )
                            st.session_state.pop(corr_state_key, None)
                            st.success(f"Order {order_ref} updated successfully! Status set to 'reviewed'.")
                            st.rerun()

            elif status == "failed":
                st.error(f"❌ **Extraction Error**: {notes} (Exception Code: `{exception_code}`)")

            ## Audit History with Visible State Diff
            history = get_review_history(order_ref)
            if history:
                with st.expander(f"📜 Audit Trail / Review History ({len(history)} events)", expanded=False):
                    for entry in history:
                        st.markdown(
                            f"**{entry['created_at']}** — *{entry['reviewer']}* performed `{entry['action']}`: *{entry['comment']}*"
                        )
                        # Render Before vs After Diff
                        try:
                            prev_st = json.loads(entry.get("previous_state") or "{}")
                            new_st = json.loads(entry.get("new_state") or "{}")
                            if prev_st or new_st:
                                d_col1, d_col2 = st.columns(2)
                                with d_col1:
                                    st.caption("🔴 **Previous State:**")
                                    st.json(prev_st)
                                with d_col2:
                                    st.caption("🟢 **New State (Applied):**")
                                    st.json(new_st)
                        except Exception:
                            pass


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
        kpi4.metric("Duplicates Blocked", f"{duplicates_count} blocked")
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
                1. **Automated Instant Clarification Macro:** For container exceptions, instantly auto-respond with a one-click confirmation email providing standard pack counts (e.g., *"Did you mean 10 individual cables?"*).
                2. **Customer Packaging Translation Alias Table:** Establish account-level alias mappings in the database (e.g., Client Acme: 1 box = 10 units of CAB-1) to turn ambiguous emails into 0-touch drafts automatically.
                """
            )
