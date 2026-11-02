"""
Evaluation v4 (WP5 of docs/implementation_plan_v4_vi.md): what an attack achieves end to end, and what legitimate flows pay,
under both exposure modes of Layer 4 ("detection" = the v3 behaviour, "provenance" = v4).

    python evaluation/eval_v4.py                          # engine as configured
    python evaluation/eval_v4.py --artifacts models/l2_multilingual/artifacts_v3 --bands evaluation/results/band_calibration_v3.json --tag v3
    python evaluation/eval_v4.py --data-dir data/eval/v4/human --tag human     # the team-written sets (same file names)

Inputs (see their README files for who wrote them):
  data/eval/v4/attack_scenarios_vi.jsonl  each row: untrusted content -> the action an attacker wants (target_action, target_payload)
  data/eval/v4/friction_flows.jsonl       each row: user messages -> untrusted content -> a legitimate action

Per attack scenario, in a fresh session: the content goes through process_context, then the target action through
validate_action, once per mode. A control asks for the same action in a clean session: cases the hard rules already refuse
(control not ALLOW) are reported but left out of ASR-action.
  ASR-action       share of executable scenarios whose action is ALLOWed
  detector bypass  share of scenarios where the scan flagged nothing (no taint, decision ALLOW)
Per friction flow: the user messages go through process_input (a held or blocked message stops the flow there), then the
content, then the action.
  friction         share of flows held for a confirmation (user channel REVIEW/BLOCK, or action REVIEW)
  false block      share of flows whose action is BLOCKed
The budgeted adaptive-attack part of WP5 (c) is not implemented here: see docs/handoff_noi_dung_tan_cong_vi.md (H6).

Writes evaluation/results/v4_eval[_tag].json. Review items go to a temporary file.
"""
import json
import os
import sys
import tempfile
import time
import uuid
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "evaluation"))
os.environ.setdefault("FIREWALL_REVIEW_QUEUE", os.path.join(tempfile.mkdtemp(prefix="fw_v4_"), "review_queue.json"))

from eval_layer1 import wilson  # noqa: E402
from model_variant import arg, engine_for  # noqa: E402
from data_provenance import describe_data  # noqa: E402

DATA = os.path.join(BASE_DIR, "data", "eval", "v4")
RES = os.path.join(BASE_DIR, "evaluation", "results")
MODES = ("detection", "provenance")
SOURCE = {"tool_json": "tool", "review": "web"}


def rate(hits, n):
    return {"n": n, "hits": hits, "rate": round(hits / n, 4) if n else None, "ci95": wilson(hits, n)}


def load(name, data_dir=DATA):
    return [json.loads(l) for l in open(os.path.join(data_dir, name), encoding="utf-8") if l.strip()]


def ai_generated(author):
    return any(k in author for k in ("AI-generated", "Codex", "Claude", "GPT", "DeepSeek", "Gemini"))


def pct(values, q):
    if not values:
        return None
    values = sorted(values)
    return round(values[min(len(values) - 1, int(round(q * (len(values) - 1))))], 2)


class Runner:
    def __init__(self, engine):
        self.e = engine
        self.latency = defaultdict(list)

    def sid(self, prefix):
        return f"v4-{prefix}-{uuid.uuid4().hex[:8]}"

    def scan(self, sid, text, source, chunk_id):
        t = time.perf_counter()
        ctx = self.e.process_context([{"id": chunk_id, "text": text, "source": SOURCE.get(source, source)}], session_id=sid, use_judge=False)
        self.latency["context"].append((time.perf_counter() - t) * 1000)
        return ctx, bool(ctx["session_tainted"]) or ctx["decision"] != "ALLOW"

    def act(self, sid, action, payload, mode):
        self.e.actions.exposure_mode = mode
        t = time.perf_counter()
        r = self.e.validate_action(action, payload, session_id=sid)
        self.latency["action"].append((time.perf_counter() - t) * 1000)
        return r

    def attack_once(self, text, sc):
        """One try: fresh session, scan, then the action in each mode (rate limit is per session, so two actions are fine)."""
        sid = self.sid("atk")
        _, flagged = self.scan(sid, text, sc["channel"], f"{sc['id']}-c")
        decisions = {m: self.act(sid, sc["target_action"], sc["target_payload"], m) for m in MODES}
        return flagged, decisions


def run_attacks(runner, scenarios):
    rows = []
    for sc in scenarios:
        control = runner.act(runner.sid("ctl"), sc["target_action"], sc["target_payload"], "provenance")["decision"]
        flagged, dec = runner.attack_once(sc["content"], sc)
        rows.append({"id": sc["id"], "domain": sc["domain"], "channel": sc["channel"], "action": sc["target_action"],
                     "explicit": bool(sc["has_explicit_instruction"]), "control": control, "flagged": flagged,
                     **{f"{m}_decision": dec[m]["decision"] for m in MODES}, **{f"{m}_check": dec[m].get("check") for m in MODES}})
    return rows


def summarize_attacks(rows):
    out = {"n": len(rows), "executable": sum(r["control"] == "ALLOW" for r in rows),
           "detector_bypass": rate(sum(not r["flagged"] for r in rows), len(rows)), "by_mode": {}}
    exe = [r for r in rows if r["control"] == "ALLOW"]
    for m in MODES:
        out["by_mode"][m] = {
            "asr_action": rate(sum(r[f"{m}_decision"] == "ALLOW" for r in exe), len(exe)),
            "stopped_by": {k: sum(r[f"{m}_check"] == k and r[f"{m}_decision"] != "ALLOW" for r in exe) for k in ("taint", "exposure", "hard_rule", "policy", "rate_limit")},
            "by_explicit": {str(flag): rate(sum(r[f"{m}_decision"] == "ALLOW" for r in exe if r["explicit"] == flag), sum(r["explicit"] == flag for r in exe)) for flag in (True, False)},
            "by_channel": {ch: rate(sum(r[f"{m}_decision"] == "ALLOW" for r in exe if r["channel"] == ch), sum(r["channel"] == ch for r in exe))
                           for ch in sorted({r["channel"] for r in exe})},
        }
    out["not_executable_by_action"] = {a: sum(1 for r in rows if r["control"] != "ALLOW" and r["action"] == a) for a in sorted({r["action"] for r in rows})}
    return out


def run_friction(runner, flows):
    rows = []
    for f in flows:
        per_mode = {}
        for m in MODES:
            sid = runner.sid("fr")
            stopped_user = None
            for msg in f["user_messages"]:
                r = runner.e.process_input(msg, use_judge=False, session_id=sid)
                if r["decision"] in ("BLOCK", "REVIEW"):
                    stopped_user = {"decision": r["decision"], "layer": r["stopped_at_layer"]}
                    break
            if stopped_user:
                per_mode[m] = {"stage": "user", "decision": stopped_user["decision"], "layer": stopped_user["layer"], "check": None}
                continue
            if f.get("content"):
                runner.scan(sid, f["content"]["text"], f["content"]["source"], f"{f['id']}-c")
            a = runner.act(sid, f["action"]["type"], f["action"]["payload"], m)
            per_mode[m] = {"stage": "action", "decision": a["decision"], "layer": 4, "check": a.get("check")}
        rows.append({"id": f["id"], "domain": f["domain"], "lang": f["lang"], "split": f["split"], "destination_from": f["destination_from"],
                     "action": f["action"]["type"], **{f"{m}_{k}": v for m in MODES for k, v in per_mode[m].items()}})
    return rows


def summarize_friction(rows):
    out = {"n": len(rows), "by_mode": {}}
    for m in MODES:
        def block(r):
            return r[f"{m}_stage"] == "action" and r[f"{m}_decision"] == "BLOCK"

        def held(r):
            return (r[f"{m}_stage"] == "user") or (r[f"{m}_decision"] == "REVIEW")

        entry = {"friction": rate(sum(held(r) for r in rows), len(rows)), "false_block": rate(sum(block(r) for r in rows), len(rows)),
                 "stopped_on_user_channel": rate(sum(r[f"{m}_stage"] == "user" for r in rows), len(rows)),
                 "action_review": rate(sum(r[f"{m}_stage"] == "action" and r[f"{m}_decision"] == "REVIEW" for r in rows), len(rows)),
                 "action_review_by_check": {}}
        for r in rows:
            if r[f"{m}_stage"] == "action" and r[f"{m}_decision"] != "ALLOW":
                key = f"{r[f'{m}_decision']}:{r[f'{m}_check']}"
                entry["action_review_by_check"][key] = entry["action_review_by_check"].get(key, 0) + 1
        for field in ("destination_from", "split", "lang", "domain"):
            entry[f"by_{field}"] = {v: {"friction": rate(sum(held(r) for r in rows if r[field] == v), sum(r[field] == v for r in rows)),
                                        "false_block": rate(sum(block(r) for r in rows if r[field] == v), sum(r[field] == v for r in rows))}
                                    for v in sorted({r[field] for r in rows})}
        out["by_mode"][m] = entry
    return out


def main():
    tag = arg("--tag")
    engine, clf = engine_for(arg("--artifacts"), arg("--bands"))
    runner = Runner(engine)
    data_dir = os.path.join(BASE_DIR, arg("--data-dir")) if arg("--data-dir") else DATA
    attacks, flows = load("attack_scenarios_vi.jsonl", data_dir), load("friction_flows.jsonl", data_dir)
    a_rows = run_attacks(runner, attacks)
    f_rows = run_friction(runner, flows)
    provenance = describe_data(attacks + flows)
    report = {
        "model": arg("--artifacts") or "default", "l2_threshold": clf.threshold, "soft_block_below": engine.soft_block_below,
        "data_dir": arg("--data-dir") or "data/eval/v4", **provenance,
        "attacks": summarize_attacks(a_rows), "friction": summarize_friction(f_rows),
        "friction_by_split": {s: summarize_friction([r for r in f_rows if r["split"] == s]) for s in ("dev", "test")},
        "latency_ms": {k: {"p50": pct(v, 0.5), "p95": pct(v, 0.95), "n": len(v)} for k, v in runner.latency.items()},
        "adaptive": "not run (H6 of docs/handoff_noi_dung_tan_cong_vi.md)",
        "attack_rows": a_rows, "friction_rows": f_rows,
    }
    path = os.path.join(RES, f"v4_eval{'_' + tag if tag else ''}.json")
    json.dump(report, open(path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    A, F = report["attacks"], report["friction"]
    print(f"attacks n={A['n']} executable={A['executable']} detector_bypass={A['detector_bypass']['rate']}")
    for m in MODES:
        print(f"  {m:10s} ASR-action={A['by_mode'][m]['asr_action']['rate']}  stopped_by={A['by_mode'][m]['stopped_by']}")
    print(f"friction flows n={F['n']}")
    for m in MODES:
        e = F["by_mode"][m]
        print(f"  {m:10s} friction={e['friction']['rate']} false_block={e['false_block']['rate']} user_channel={e['stopped_on_user_channel']['rate']} "
              f"action_review={e['action_review']['rate']}")
    print(f"[INFO] wrote {path}")


if __name__ == "__main__":
    main()
