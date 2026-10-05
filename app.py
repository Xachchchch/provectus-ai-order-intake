"""Streamlit-based interactive operations queue with status filtering, reviewer corrections, and analytics."""

import json
import os
import streamlit as st

from src.catalog import CATALOG
from src.engine import apply_reviewer_correction, batch_process, process_request
from src.storage import (
    DEFAULT_DB_PATH,
    get_clarification_draft,
    get_order,
    get_order_by_request_id,
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

# Load seed requests from data/requests.json
DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "requests.json")


def load_seed_requests():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("requests", [])
    return []


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

if st.sidebar.button("🚀 Ingest / Run All Seed Requests (R1-R10)", type="primary"):
    seed_requests = load_seed_requests()
    results = batch_process(seed_requests, force_replay=replay_mode)
    st.sidebar.success(f"Processed {len(results)} incoming requests!")
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

# Retrieve orders from DB
all_orders = list_orders()

# Top Navigation Tabs
tab_queue, tab_analytics = st.tabs(["📦 Operations Queue", "📊 Analytics & Insights"])

with tab_queue:
    # Metrics summary bar
    total_count = len(all_orders)
    draft_count = sum(1 for o in all_orders if o["status"] == "draft")
    reviewed_count = sum(1 for o in all_orders if o["status"] == "reviewed")
    clarification_count = sum(1 for o in all_orders if o["status"] == "needs-clarification")
    duplicate_count = sum(1 for o in all_orders if o["status"] == "duplicate")
    failed_count = sum(1 for o in all_orders if o["status"] == "failed")

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total Ingested", total_count)
    col2.metric("Valid Drafts", draft_count)
    col3.metric("Human Reviewed", reviewed_count)
    col4.metric("Needs Clarification", clarification_count)
    col5.metric("Duplicates Handled", duplicate_count)

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
        st.info("No orders found for selected filter. Click **'Ingest / Run All Seed Requests (R1-R10)'** in the sidebar to populate the queue.")

    # Display Orders
    for order in filtered_orders:
        order_ref = order["order_ref"]
        req_id = order["request_id"]
        status = order["status"]
        created_at = order["created_at"]
        raw_text = order["raw_text"]
        notes = order.get("notes", "")
        model_name = order.get("model", "llama-3.3-70b-versatile")
        is_cached = order.get("is_cached", True)

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

                tot_col1, tot_col2, tot_col3 = st.columns([2, 1, 1])
                tot_col1.caption(f"Created: {created_at} | {notes}")
                tot_col2.metric("Total Discount", f"${order.get('discount_cents', 0) / 100:.2f}")
                tot_col3.metric("Final Total", f"${order.get('total_cents', 0) / 100:.2f} ({order.get('total_cents', 0)}¢)")

            elif status == "duplicate":
                st.info(f"ℹ️ **Duplicate Handled**: {notes}")

            elif status == "needs-clarification":
                st.warning(f"⚠️ **Exception Flagged**: {notes}")

                # Show draft inquiry email
                draft = get_clarification_draft(order_ref)
                if draft:
                    with st.expander("✉️ View Customer Clarification Email Draft", expanded=False):
                        st.text_input("Subject", value=draft["subject"], disabled=True, key=f"subj_{order_ref}_{req_id}")
                        st.text_area("Email Body", value=draft["draft_email"], height=200, disabled=True, key=f"body_{order_ref}_{req_id}")

                # Inline Human Reviewer Correction Form
                with st.expander(f"✏️ Manual Reviewer Correction for {order_ref}", expanded=True):
                    st.write("Resolve this exception by selecting confirmed catalog items and unit quantities (updates status to **'reviewed'**):")
                    with st.form(key=f"correction_form_{order_ref}_{req_id}"):
                        c1, c2 = st.columns([2, 1])
                        selected_sku = c1.selectbox(
                            "Confirmed Catalog SKU",
                            options=list(CATALOG.keys()),
                            format_func=lambda s: f"{s} - {CATALOG[s].name} (${CATALOG[s].unit_cents/100:.2f})",
                            key=f"sku_{order_ref}_{req_id}",
                        )
                        qty_input = c2.number_input(
                            "Confirmed Individual Units",
                            min_value=1,
                            max_value=1000,
                            value=1,
                            step=1,
                            key=f"qty_{order_ref}_{req_id}",
                        )

                        c3, c4 = st.columns([1, 2])
                        reviewer_name = c3.text_input("Reviewer Username", value="reviewer_ops", key=f"rev_{order_ref}_{req_id}")
                        reviewer_note = c4.text_input("Correction Comment", value="Customer confirmed SKU and unit count via support", key=f"com_{order_ref}_{req_id}")

                        submit_btn = st.form_submit_button("✅ Apply Correction & Recalculate Pricing", type="primary")

                        if submit_btn:
                            apply_reviewer_correction(
                                order_ref=order_ref,
                                corrected_items=[{"sku": selected_sku, "quantity": qty_input}],
                                reviewer=reviewer_name,
                                comment=reviewer_note,
                            )
                            st.success(f"Order {order_ref} updated successfully! Status set to 'reviewed'.")
                            st.rerun()

            elif status == "failed":
                st.error(f"❌ **Extraction Error**: {notes}")

            # Audit History
            history = get_review_history(order_ref)
            if history:
                with st.expander(f"📜 Audit Trail / Review History ({len(history)} events)"):
                    for entry in history:
                        st.markdown(
                            f"**{entry['created_at']}** — *{entry['reviewer']}* performed `{entry['action']}`: {entry['comment']}"
                        )

            st.markdown("<hr style='margin: 1.5rem 0;'>", unsafe_allow_html=True)


with tab_analytics:
    st.header("📊 Intake Analytics & Operational Insights")
    st.caption("All metrics below are computed dynamically from the live database records.")

    total_reqs = len(all_orders)

    if total_reqs == 0:
        st.info("The database is currently empty. Ingest requests from the sidebar to view analytics.")
    else:
        auto_drafts = sum(1 for o in all_orders if o["status"] == "draft")
        reviewed = sum(1 for o in all_orders if o["status"] == "reviewed")
        clarifications = sum(1 for o in all_orders if o["status"] == "needs-clarification")
        duplicates = sum(1 for o in all_orders if o["status"] == "duplicate")
        failed = sum(1 for o in all_orders if o["status"] == "failed")

        kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
        kpi1.metric("Zero-Touch Drafts", f"{auto_drafts} ({auto_drafts/total_reqs*100:.0f}%)")
        kpi2.metric("Human Reviewed", f"{reviewed} ({reviewed/total_reqs*100:.0f}%)")
        kpi3.metric("Clarifications", f"{clarifications} ({clarifications/total_reqs*100:.0f}%)")
        kpi4.metric("Duplicates Blocked", f"{duplicates} ({duplicates/total_reqs*100:.0f}%)")
        kpi5.metric("Processing Failures", f"{failed}")

        st.markdown("---")

        col_chart, col_recommendation = st.columns([1, 1])

        with col_chart:
            st.subheader("🔍 Dynamic Exception Breakdown")
            
            # Dynamically categorize exceptions based on notes in database
            box_pack = sum(1 for o in all_orders if any(w in o.get("notes", "").lower() for w in ["box", "pack", "crate", "ambiguous quantity"]))
            unknown_prod = sum(1 for o in all_orders if "unknown product" in o.get("notes", "").lower())
            ambiguous_prod = sum(1 for o in all_orders if "ambiguous product" in o.get("notes", "").lower())
            
            cause_counts = {
                "Container Ambiguity ('box'/'pack')": box_pack,
                "Unknown Catalog Product": unknown_prod,
                "Ambiguous Description (multiple SKUs)": ambiguous_prod,
                "Duplicate Submission": duplicates,
            }

            for cause, count in cause_counts.items():
                if count > 0:
                    pct = (count / total_reqs) * 100
                    st.write(f"**{cause}**: {count} orders ({pct:.0f}%)")
                    st.progress(pct / 100)

        with col_recommendation:
            st.subheader("💡 Actionable Business Process Improvement")
            st.info(
                f"""
                **Evidence from Current Ingestion Data:**
                - Out of **{clarifications} clarification exceptions**, **{box_pack} are caused by container terminology** 
                  (*"boxes"*, *"packs"*, *"crates"*) where unit counts were omitted (e.g., R3, R7, R9).
                - **{unknown_prod} exceptions** are caused by unlisted products (R2, R10), and **{ambiguous_prod}** by missing length specifications (R8).

                **Supported Operational Improvement:**
                1. **Mandatory Piece-Count Field:** By replacing open-ended text with a numeric *'Piece count'* field on incoming portals, all **{box_pack} packaging exceptions ({box_pack/total_reqs*100:.0f}% of total volume)** would be resolved before hitting the operations queue.
                2. **Catalog Dropdown at Intake:** Restricting product entry to catalog SKUs or forcing length selection for cables would convert the remaining exceptions directly into automated drafts.
                """
            )
