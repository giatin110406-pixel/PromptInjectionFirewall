"""Run H1 through real FastAPI routes + local models, with isolated stores.

No mock decisions, skipped layers, paid judge or running-server writes.
Each scenario gets a new session, as when resetting the demo before each case.
"""
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    with tempfile.TemporaryDirectory(prefix="handoff_demo_") as temp:
        os.environ["FIREWALL_REVIEW_QUEUE"] = str(Path(temp) / "review.json")
        os.environ["FIREWALL_FEEDBACK_FILE"] = str(Path(temp) / "feedback.jsonl")
        os.environ["FIREWALL_JUDGE_PROVIDER"] = "none"
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        # The current IncidentStore has no environment override. Redirect its
        # module constant before importing the application singleton.
        import api.incident_store as store_module
        store_module.INCIDENTS_FILE = str(Path(temp) / "incidents.json")
        store_module.incident_store.incidents.clear()
        from fastapi.testclient import TestClient
        from api.main import app

        scenarios = json.loads((ROOT / "frontend/security-console/lib/demo_scenarios.json").read_text(encoding="utf-8"))
        base = {"shop": {"user_id": "cus_may_01"},
                "bank": {"user_id": "demo_customer", "from_account": "0071000555666", "otp_verified": True},
                "work": {"user_id": "emp_001"}}
        rows = []
        with TestClient(app) as client:
            health = client.get("/health").json()
            for domain, config in scenarios["domains"].items():
                login = client.post("/auth/login", json={"username": config["login"], "password": config["login"] + "_123"})
                login.raise_for_status()
                headers = {"Authorization": "Bearer " + login.json()["access_token"]}
                for case in config["cases"]:
                    sid = "handoff-" + uuid.uuid4().hex
                    def post(path, body):
                        response = client.post(path, json=dict(body, session_id=sid), headers=headers)
                        response.raise_for_status()
                        return response.json()
                    message = post("/chat/message", {"text": case["user"]})
                    context = None
                    action = None
                    if message["decision"] == "ALLOW":
                        if case.get("doc"):
                            context = post("/chat/context", {"chunks": [case["doc"]]})
                        action = post("/chat/action", {"action_type": case["action"]["type"], "payload": dict(base[domain], **case["action"]["payload"])})
                    expected = {"attack": ["BLOCK", "REVIEW"], "value": ["REVIEW"], "legit": ["ALLOW"]}[case["kind"]]
                    passed = (message["decision"] == "ALLOW" and action is not None and action["decision"] in expected)
                    # The pitch's value-only case must pass detection and be
                    # held by provenance rather than taint, limits or hard rules.
                    if case["kind"] == "value":
                        passed = passed and context is not None and not context["session_tainted"] and context["decision"] == "ALLOW" and action["check"] == "exposure"
                    row = dict(id=case["id"], kind=case["kind"], expected=expected, passed=passed,
                               message=message, context=context, action=action)
                    rows.append(row)
                    print(f"{case['id']}: user={message['decision']} context={context and context['decision']} action={action and action['decision']} passed={passed}", flush=True)
            # The existing UI keeps taint until the viewer resets the session.
        report = dict(method="FastAPI TestClient, real local L1/L2/L4, no skipped layers, isolated disk stores; not a browser test",
                      health=health, passed=sum(r["passed"] for r in rows), total=len(rows), cases=rows)
        target = ROOT / "evaluation/results/handoff/demo_api_check.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 0 if report["passed"] == report["total"] and health["status"] == "healthy" else 1


if __name__ == "__main__":
    raise SystemExit(main())
