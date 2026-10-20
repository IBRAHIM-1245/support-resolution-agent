# Refund Review Assistant - the LangGraph part.
# It prepares a recommendation for the human who approves big refunds.
# The human still makes the final decision on Telegram.
#
# Steps (nodes):
#   load_history -> check_risk -> (not eligible?) -> decline_without_ai -> END
#                               -> (eligible)     -> find_policy -> recommend -> END
import os
from datetime import date
from typing import Literal, TypedDict

import psycopg2
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langgraph.graph import END, START, StateGraph
from pinecone import Pinecone
from pydantic import BaseModel, Field

load_dotenv()  # reads the keys from .env (never written in code)

RETURN_WINDOW_DAYS = 7          # refund policy: returns within 7 days of delivery
HIGH_VALUE_RS = 5000            # our own extra check for very expensive items
PINECONE_INDEX = "shaikmart-policies"
PINECONE_NAMESPACE = "policies"


# ---------- The shared "state": every node reads it and adds to it ----------
class ReviewState(TypedDict, total=False):
    # input from n8n
    ticket_id: str
    ticket_date: str          # the ticket date counts as "today"
    customer_email: str
    order_id: str
    product: str
    amount_rs: float
    payment_method: str
    delivered_date: str
    refund_status: str
    message: str
    # added by the nodes
    past_orders: int
    past_refunds: int
    days_since_delivery: int
    eligible: bool
    risk_flags: list
    risk_level: str
    policy_text: str
    recommendation: str
    reasons: list
    policy_quote: str


# ---------- Node 1: customer history from the database (read-only user) ----------
def load_history(state: ReviewState) -> dict:
    connection = psycopg2.connect(os.getenv("DASHBOARD_DB_URL"))
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT COUNT(*),
               COUNT(*) FILTER (WHERE refund_status = 'refunded')
        FROM order_lookup
        WHERE lower(customer_email) = lower(%s)
          AND order_id <> %s
        """,
        (state["customer_email"], state["order_id"]),
    )
    past_orders, past_refunds = cursor.fetchone()
    connection.close()
    return {"past_orders": past_orders, "past_refunds": past_refunds}


# ---------- Node 2: simple, fixed rules (no AI) ----------
def check_risk(state: ReviewState) -> dict:
    today = date.fromisoformat(state["ticket_date"][:10])
    delivered = date.fromisoformat(state["delivered_date"][:10])
    days = (today - delivered).days

    # Hard rules from the refund policy
    eligible = days <= RETURN_WINDOW_DAYS and state["refund_status"] != "refunded"

    # Extra warning signs for the human
    flags = []
    if state["amount_rs"] > HIGH_VALUE_RS:
        flags.append("High value item (above Rs 5,000)")
    if state["past_refunds"] >= 2:
        flags.append(f"Customer already had {state['past_refunds']} refunds")
    if state["payment_method"] == "COD":
        flags.append("Cash on delivery: refund goes as store credit or to a UPI ID")

    if not eligible or state["past_refunds"] >= 2:
        risk = "high"
    elif flags:
        risk = "medium"
    else:
        risk = "low"

    return {"days_since_delivery": days, "eligible": eligible,
            "risk_flags": flags, "risk_level": risk}


# ---------- Branch: skip the AI when the policy already says no ----------
def route_after_risk(state: ReviewState) -> str:
    if state["eligible"]:
        return "find_policy"
    return "decline_without_ai"


def decline_without_ai(state: ReviewState) -> dict:
    if state["refund_status"] == "refunded":
        reason = "This order was already refunded."
    else:
        reason = (f"Delivered {state['days_since_delivery']} days ago, "
                  f"outside the {RETURN_WINDOW_DAYS}-day return window.")
    return {"recommendation": "decline", "reasons": [reason],
            "policy_quote": "", "policy_text": ""}


# ---------- Node 3: read the refund policy from Pinecone ----------
def find_policy(state: ReviewState) -> dict:
    question = f"refund approval rules for a {state['product']} worth Rs {state['amount_rs']}"
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")   # LangChain
    vector = embeddings.embed_query(question)

    index = Pinecone(api_key=os.getenv("PINECONE_API_KEY")).Index(PINECONE_INDEX)
    result = index.query(
        vector=vector,
        top_k=3,
        namespace=PINECONE_NAMESPACE,
        include_metadata=True,
        filter={"policy": {"$eq": "refund_return_policy"}},   # only the refund policy
    )
    texts = [match.metadata.get("text", "") for match in result.matches]
    return {"policy_text": "\n---\n".join(texts)}


# ---------- Node 4: the AI writes a recommendation (fixed output fields) ----------
class Recommendation(BaseModel):
    recommendation: Literal["approve", "decline", "needs_more_info"]
    reasons: list[str] = Field(description="2 or 3 short reasons, each under 20 words")
    policy_quote: str = Field(description="One short sentence copied from the policy text")


def recommend(state: ReviewState) -> dict:
    model = ChatOpenAI(model="gpt-4o-mini", temperature=0)          # LangChain
    reviewer = model.with_structured_output(Recommendation)

    prompt = f"""You help a ShaikMart support lead decide a refund request above Rs 2,000.
Use ONLY the facts and the policy text below. Do not invent rules.

FACTS:
- Product: {state['product']}, amount Rs {state['amount_rs']}, paid by {state['payment_method']}
- Delivered {state['days_since_delivery']} days before the ticket (return window: {RETURN_WINDOW_DAYS} days)
- Customer's other orders: {state['past_orders']}, past refunds: {state['past_refunds']}
- Risk level from company rules: {state['risk_level']}
- Warning signs: {state['risk_flags'] or 'none'}
- Customer message: {state['message']}

POLICY TEXT:
{state['policy_text']}

Recommend approve, decline, or needs_more_info (for example if the message does not explain the problem)."""

    answer = reviewer.invoke(prompt)
    return {"recommendation": answer.recommendation,
            "reasons": answer.reasons,
            "policy_quote": answer.policy_quote}


# ---------- Build the graph ----------
def build_graph():
    graph = StateGraph(ReviewState)
    graph.add_node("load_history", load_history)
    graph.add_node("check_risk", check_risk)
    graph.add_node("decline_without_ai", decline_without_ai)
    graph.add_node("find_policy", find_policy)
    graph.add_node("recommend", recommend)

    graph.add_edge(START, "load_history")
    graph.add_edge("load_history", "check_risk")
    graph.add_conditional_edges("check_risk", route_after_risk,
                                ["find_policy", "decline_without_ai"])
    graph.add_edge("find_policy", "recommend")
    graph.add_edge("recommend", END)
    graph.add_edge("decline_without_ai", END)
    return graph.compile()


refund_review = build_graph()
