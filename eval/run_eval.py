# Sends test tickets to the Support Agent and checks the answers.
# Usage:
#   python eval/run_eval.py                 -> runs all tickets
#   python eval/run_eval.py T02 T16 T21     -> runs only these tickets
import csv
import sys
import requests

URL = "http://localhost:5678/webhook/ticket"   # production webhook (workflow must be published)

results = []
action_pass = 0
mention_pass = 0
mention_total = 0

with open("eval/test_tickets.csv") as f:
    tickets = list(csv.DictReader(f))

# Optional: run only the ticket IDs given on the command line
if len(sys.argv) > 1:
    tickets = [t for t in tickets if t["ticket_id"] in sys.argv[1:]]

for t in tickets:
    body = {
        "ticket_id": t["ticket_id"],
        "created_at": t["created_at"],
        "customer_email": t["customer_email"],
        "order_id": t["order_id"],
        "message": t["message"],
    }
    try:
        answer = requests.post(URL, json=body, timeout=120).json()
    except Exception as error:
        answer = {"status": "error", "reply": str(error)}

    # What did the agent decide?
    if answer.get("status") == "blocked":
        got_action = "block"
    else:
        got_action = answer.get("action", "error")
    reply = answer.get("reply") or answer.get("message") or ""

    # Check 1: correct decision
    action_ok = got_action == t["expected_action"]
    if action_ok:
        action_pass += 1

    # Check 2: the reply mentions the key fact (skipped for blocked tickets)
    mention = t["must_mention"].strip()
    if mention:
        mention_total += 1
        mention_ok = mention.lower() in reply.lower()
        if mention_ok:
            mention_pass += 1
    else:
        mention_ok = True

    status = "PASS" if action_ok and mention_ok else "FAIL"
    print(f"{t['ticket_id']}  {status}  expected={t['expected_action']:<16} got={got_action:<16} mention '{mention}': {mention_ok}")

    results.append({
        "ticket_id": t["ticket_id"],
        "expected_action": t["expected_action"],
        "got_action": got_action,
        "action_ok": action_ok,
        "must_mention": mention,
        "mention_ok": mention_ok,
        "reply": reply,
    })

# Save details for review
with open("eval/results.csv", "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=results[0].keys())
    writer.writeheader()
    writer.writerows(results)

print()
print(f"Correct decisions: {action_pass}/{len(tickets)}")
print(f"Key fact mentioned: {mention_pass}/{mention_total}")
print("Details saved to eval/results.csv")
