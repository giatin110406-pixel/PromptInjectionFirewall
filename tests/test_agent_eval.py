"""evaluation/eval_agent.py in dry-run mode (scripted LLM, no network): runs end to end and writes the documented JSON."""
import json
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "evaluation"))

import eval_agent  # noqa: E402


@pytest.fixture
def run_eval(tmp_path, monkeypatch):
    monkeypatch.setattr(eval_agent, "RES", str(tmp_path))

    def run(*extra):
        monkeypatch.setattr(sys, "argv", ["eval_agent.py", "--provider", "scripted", "--limit", "5", "--tag", "t", *extra])
        eval_agent.main()
        return json.load(open(tmp_path / "agent_eval_t.json", encoding="utf-8"))

    return run


def test_dry_run_writes_the_report(run_eval):
    report = run_eval()
    assert report["provider"] == "scripted" and report["prompt_version"] and report["partial"] is False
    assert {"data_provenance", "note", "latency_ms", "attacks", "flows", "attack_rows", "flow_rows"} <= set(report)
    off = report["attacks"]["by_mode"]["off"]
    assert off["n"] == 5 and off["agent_attempt_rate"]["rate"] == 1.0 and off["asr_action"]["rate"] == 1.0   # the scripted agent always follows
    assert set(off["asr_action"]) == {"n", "hits", "rate", "ci95"}
    prov = report["attacks"]["by_mode"]["provenance"]
    assert prov["asr_action"]["rate"] == 0.0 and report["attacks"]["excluded"] == {"role_escalation": 4}
    flows = report["flows"]
    assert flows["n"] == 5 and {"task_success", "human_approval_rate", "false_block", "stopped_on_user_channel", "agent_error"} <= set(flows)
    assert report["data_provenance"]["declared_provenance"]["ai_generated"] > 0


def test_resume_reuses_the_checkpoint(run_eval, tmp_path):
    first = run_eval("--only", "h3")
    second = run_eval("--only", "h3", "--resume")
    assert [r["id"] for r in second["flow_rows"]] == [r["id"] for r in first["flow_rows"]]
    assert second["llm_calls_this_invocation"] == 0
    assert os.path.getsize(tmp_path / "agent_eval_t.checkpoint.jsonl") > 0


def test_resume_refuses_changed_prompt(run_eval, monkeypatch):
    run_eval("--only", "h3")
    monkeypatch.setattr(eval_agent, "PROMPT_VERSION", "changed")
    with pytest.raises(SystemExit, match="2"):
        run_eval("--only", "h3", "--resume")


def test_success_requires_right_amount_and_scope():
    assert not eval_agent.same_key("transfer_money", {"to_account": "123456", "amount": 1},
                                  {"to_account": "123456", "amount": 2_000_000})
    assert not eval_agent.same_key("data_access", {"resource": "leave_balance", "query_scope": "all"},
                                  {"resource": "leave_balance", "query_scope": "own_account"})
    assert eval_agent.same_key("transfer_money", {"to_account": "123456", "amount": 2_000_000.0},
                              {"to_account": "123456", "amount": 2_000_000})
