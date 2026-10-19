# ShaikMart Support Agent - Streamlit UI
# Page 1: customer sends a ticket and sees the agent's reply.
# Page 2: support dashboard built from the Postgres audit log.
# Run: streamlit run ui/streamlit_app.py
import os
import requests
import pandas as pd
import psycopg2
import streamlit as st
from dotenv import load_dotenv

load_dotenv()  # reads DASHBOARD_DB_URL from .env (never committed)

TICKET_URL = "http://localhost:5678/webhook/ticket"   # published n8n workflow
DB_URL = os.getenv("DASHBOARD_DB_URL")

st.set_page_config(page_title="ShaikMart Support", page_icon="🛒", layout="wide")

# Friendly labels for each decision the agent can make
ACTION_LABELS = {
    "refund_auto": "✅ Refund approved",
    "refund_approval": "⏳ Refund under review (human approval)",
    "cancel": "✅ Order cancelled",
    "deny": "❌ Request not possible",
    "escalate": "🧑‍💼 Escalated to a human",
    "verify_identity": "🔒 Identity check needed",
    "ask_info": "❓ More information needed",
    "answer": "💬 Answered",
}


def send_ticket(email, order_id, message, ticket_date):
    """Send one ticket to the n8n agent and return its JSON answer."""
    body = {
        "customer_email": email,
        "order_id": order_id,
        "message": message,
        "created_at": ticket_date,
    }
    response = requests.post(TICKET_URL, json=body, timeout=120)
    return response.json()


def load_audit_log():
    """Read the latest tickets from the audit table."""
    connection = psycopg2.connect(DB_URL)
    query = """
        SELECT ticket_id, ticket_date, customer_email, order_id, category, action,
               reason, refund_amount, verifier_ok, human_decision, reply, logged_at
        FROM support_audit
        ORDER BY id DESC
        LIMIT 200;
    """
    data = pd.read_sql(query, connection)
    connection.close()
    return data


# ---------------- Sidebar ----------------
st.sidebar.title("🛒 ShaikMart")
st.sidebar.caption("Fictional store, created for a portfolio project.")
page = st.sidebar.radio("Go to", ["Customer support", "Support dashboard"])


# ---------------- Page 1: Customer support ----------------
if page == "Customer support":
    st.title("💬 Customer Support")
    st.write("Describe your issue. Our AI agent checks your order and store policy, "
             "and a human approves anything risky.")

    with st.form("ticket_form"):
        email = st.text_input("Your email", value="riya.sharma@example.com")
        order_id = st.text_input("Order ID (optional)", value="ORD-1001")
        message = st.text_area("Your message",
                               value="The left earbud is not working at all. I want a refund please.")
        # Demo data is dated around 16 Oct 2026, so the ticket date is adjustable
        ticket_date = st.text_input("Ticket date (YYYY-MM-DD)", value="2026-10-16")
        submitted = st.form_submit_button("Send ticket")

    if submitted:
        if not message.strip():
            st.warning("Please write a message.")
        else:
            with st.spinner("The agent is checking your order and our policies..."):
                try:
                    answer = send_ticket(email, order_id, message, ticket_date)
                except Exception as error:
                    answer = {"status": "error", "message": str(error)}

            status = answer.get("status")
            if status == "blocked":
                st.error(answer.get("message", "This request was blocked."))
            elif status in ("invalid", "error"):
                st.warning(answer.get("message", "Something went wrong. Please try again."))
            else:
                action = answer.get("action", "")
                st.subheader(ACTION_LABELS.get(action, action))
                st.info(answer.get("reply", ""))
                # Top numbers
                confidence = answer.get("verifier_confidence")
                col1, col2, col3 = st.columns(3)
                col1.metric("Category", answer.get("category", "-"))
                col2.metric("Sent to a human?", "Yes" if answer.get("needs_human") else "No")
                col3.metric("Reply check confidence",
                            f"{confidence * 100:.0f}%" if isinstance(confidence, (int, float)) else "-")

                # Evidence: why the agent decided this
                st.markdown("#### 🔍 How this decision was made")

                st.markdown("**1. Company rule applied**")
                st.write(answer.get("reason", "-"))

                st.markdown("**2. Order record checked** (read-only database)")
                order = answer.get("order")
                if isinstance(order, dict):
                    st.dataframe(pd.DataFrame([order]), hide_index=True, width="stretch")
                elif order == "not shared":
                    st.write("Not shown: order details are hidden until identity is verified.")
                else:
                    st.write("No order needed for this question.")

                st.markdown("**3. Store policies the agent read** (Pinecone search)")
                searches = answer.get("policy_searches") or []
                sources = answer.get("policy_sources") or []
                policies = answer.get("policies_used") or []
                for query in searches:
                    st.write("🔎 The agent searched for: *" + query + "*")
                if sources:
                    # Show the exact policy text the agent was given
                    for number, source in enumerate(sources, start=1):
                        with st.expander(f"📄 Source {number}: {source['policy']}"):
                            st.write(source["text"])
                elif policies:
                    for name in policies:
                        st.write("📄 " + name)
                else:
                    st.write("No policy lookup was needed for this reply.")

                st.markdown("**4. Reply check** (a second AI verifies the reply before it is sent)")
                if answer.get("verifier_ok"):
                    st.success("Passed: the reply matches the decision and the order facts.")
                else:
                    st.warning("The AI reply did not pass the check, so a safe template reply was sent instead.")

    with st.expander("Try these demo tickets"):
        st.markdown(
            "- **Auto refund:** riya.sharma@example.com · ORD-1001 · earbud not working\n"
            "- **Needs approval:** ibrahim@example.com · ORD-1016 · smartwatch stopped charging, refund\n"
            "- **Wrong person:** rahul.verma@example.com · ORD-1002 · status of my order\n"
            "- **Late delivery (Hinglish):** pooja.reddy@example.com · ORD-1009 · Mera order abhi tak nahi aaya\n"
            "- **Blocked:** any email · What is the capital of France?"
        )


# ---------------- Page 2: Support dashboard ----------------
else:
    st.title("📊 Support Dashboard")

    if not DB_URL:
        st.error("DASHBOARD_DB_URL is missing in .env")
        st.stop()

    data = load_audit_log()
    if data.empty:
        st.info("No tickets yet. Send one from the Customer support page.")
        st.stop()

    # Top numbers
    total = len(data)
    automatic = data["action"].isin(["refund_auto", "cancel", "answer", "deny"]).sum()
    to_human = data["human_decision"].isin(["approved", "rejected"]).sum()
    verifier_pass = data["verifier_ok"].mean() * 100

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Tickets", total)
    col2.metric("Resolved automatically", f"{automatic / total * 100:.0f}%")
    col3.metric("Decided by a human", int(to_human))
    col4.metric("Verifier pass rate", f"{verifier_pass:.0f}%")

    # Decisions by type
    st.subheader("Decisions by type")
    counts = data["action"].map(lambda a: ACTION_LABELS.get(a, a)).value_counts()
    st.bar_chart(counts)

    # Human approvals
    st.subheader("Human approvals (Telegram)")
    approvals = data[data["human_decision"] != "not_needed"]
    if approvals.empty:
        st.write("No approvals yet.")
    else:
        st.dataframe(approvals[["ticket_id", "order_id", "action", "refund_amount",
                                "human_decision", "logged_at"]],
                     width="stretch", hide_index=True)

    # All tickets
    st.subheader("Recent tickets")
    st.dataframe(data[["ticket_id", "customer_email", "order_id", "category", "action",
                       "reason", "verifier_ok", "human_decision", "logged_at"]],
                 width="stretch", hide_index=True)

    # Read one reply in full
    chosen = st.selectbox("Read the reply for ticket", data["ticket_id"])
    st.info(data[data["ticket_id"] == chosen]["reply"].iloc[0])
