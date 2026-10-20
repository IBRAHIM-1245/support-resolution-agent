# Refund Review Assistant - the FastAPI part.
# n8n sends a big refund request here and gets back a recommendation.
# Run:  uvicorn refund_agent.main:app --port 8000
from fastapi import FastAPI
from pydantic import BaseModel

from refund_agent.graph import refund_review

app = FastAPI(title="ShaikMart Refund Review Assistant")


# What n8n must send (FastAPI checks this automatically and rejects bad input)
class RefundRequest(BaseModel):
    ticket_id: str
    ticket_date: str
    customer_email: str
    order_id: str
    product: str
    amount_rs: float
    payment_method: str
    delivered_date: str
    refund_status: str = "none"
    message: str = ""


@app.get("/health")
def health():
    """Quick check that the service is running."""
    return {"status": "ok"}


@app.post("/review-refund")
def review_refund(request: RefundRequest):
    """Run the LangGraph review and return the recommendation."""
    result = refund_review.invoke(request.model_dump())

    # One ready-to-read text block for the Telegram message
    lines = [f"Recommendation: {result['recommendation'].upper()} (risk: {result['risk_level']})"]
    for reason in result["reasons"]:
        lines.append("- " + reason)
    for flag in result["risk_flags"]:
        lines.append("! " + flag)
    if result.get("policy_quote"):
        lines.append('Policy: "' + result["policy_quote"] + '"')

    return {
        "ticket_id": request.ticket_id,
        "recommendation": result["recommendation"],
        "risk_level": result["risk_level"],
        "risk_flags": result["risk_flags"],
        "reasons": result["reasons"],
        "policy_quote": result.get("policy_quote", ""),
        "past_orders": result["past_orders"],
        "past_refunds": result["past_refunds"],
        "days_since_delivery": result["days_since_delivery"],
        "summary": "\n".join(lines),
    }
