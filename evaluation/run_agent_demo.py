"""The nine /demo cases (3 domains x attack / value / legit) with a real LLM, in mode off and provenance.

    python evaluation/run_agent_demo.py --provider groq --tag groq

The customer says what the demo page says; the document of the case is put in the inbox or document store. Writes
evaluation/results/agent_demo_<tag>.json. Same limits as eval_agent.py: AGENT_MAX_CALLS, 429 backoff, free tier only.
"""
import argparse
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "evaluation"))

from eval_v4 import RES  # noqa: E402  (points the review queue at a temp file)

from agent.llm import get_tool_llm  # noqa: E402
from agent.loop import Agent  # noqa: E402
from agent.prompts import PROMPT_VERSION  # noqa: E402

SCENARIOS = os.path.join(BASE_DIR, "frontend", "security-console", "lib", "demo_scenarios.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default=os.environ.get("AGENT_PROVIDER", "scripted"))
    ap.add_argument("--model", default=None)
    ap.add_argument("--tag", default=None)
    ap.add_argument("--max-calls", type=int, default=None)
    args = ap.parse_args()
    from model_variant import engine_for
    engine, _ = engine_for()
    llm = get_tool_llm(args.provider, model=args.model, max_calls=args.max_calls)
    agent = Agent(engine)
    rows = []
    stopped_because = None
    for domain, conf in json.load(open(SCENARIOS, encoding="utf-8"))["domains"].items():
        if args.provider == "scripted":
            llm = get_tool_llm("scripted", domain=domain)
        for case in conf["cases"]:
            for mode in ("off", "provenance"):
                sid = f"demo-{case['id']}-{mode}"
                doc = case.get("doc")
                agent.reset(sid, domain, contents=[(doc["source"], doc["text"])] if doc else [])
                res = agent.run(sid, case["user"], llm=llm, mode=mode)
                actions = [{"tool": s["tool"], "decision": s["decision"], "check": s.get("check")} for s in res.steps if s["kind"] == "tool_action"]
                rows.append({"case": case["id"], "kind": case["kind"], "mode": mode, "attempted": [a["tool"] for a in res.attempts],
                             "actions": actions, "executed": [e["type"] for e in res.executed], "held": bool(res.pending_review),
                             "stopped": res.stopped, "error": res.error, "reply": res.reply[:200], "llm_calls": res.llm_calls})
                print(case["id"], mode, "attempted", rows[-1]["attempted"], "decisions", [a["decision"] for a in actions],
                      "executed", rows[-1]["executed"], res.stopped or "", res.error or "", flush=True)
                if res.fatal:
                    stopped_because = res.error
                    print("[STOP] quota or budget exhausted")
                    break
            if stopped_because:
                break
        if stopped_because:
            break
    path = os.path.join(RES, f"agent_demo_{args.tag or args.provider}.json")
    json.dump({"provider": args.provider, "model": llm.model, "prompt_version": PROMPT_VERSION,
               "llm_calls": sum(r["llm_calls"] for r in rows), "partial": bool(stopped_because),
               "stopped_because": stopped_because, "rows": rows}, open(path, "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    print(f"[INFO] llm calls={llm.calls} wrote {path}")


if __name__ == "__main__":
    main()
