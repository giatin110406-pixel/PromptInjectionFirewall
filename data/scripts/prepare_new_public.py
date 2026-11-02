"""
Build evaluation sets from two public benchmarks published after the firewall's training data (2026-10-24).

    python data/scripts/prepare_new_public.py

Inputs (downloaded by hand into data/raw/public/, see SOURCES.md):
  msb/          MCP Security Bench (DongsenZhang/MSB on Hugging Face, MIT, arXiv 2510.15994). MSB is an executable benchmark:
                its attacks are its own templates (prompt_template.py) filled with its own goals (attack_task.jsonl) and
                placed in a tool description or a tool response. This script rebuilds those texts the same way.
  promptshield/ PromptShield test split (hendzh/PromptShield, Apache-2.0, arXiv 2501.15145).

Outputs in data/eval/public/ (same columns as the other public sets: text, label_binary, lang, attack_type):
  msb_tool_desc     benign MCP tool descriptions (label 0) and the same descriptions with MSB's injection appended (label 1)
  msb_tool_resp     tool responses built from MSB's false-error, simulated-user and tool-transfer attacks (label 1)
  promptshield      PromptShield test, minus texts that are also in the L2 training data (exact match after normalising),
                    then a random sample of SAMPLE_PER_LABEL texts per label (seed 0) so a run takes minutes, not hours

Not rebuilt: MSB attacks that are not text (name collision, out-of-scope parameters); a text filter cannot see them.
"""
import ast
import glob
import json
import os
import re
import sys

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW = os.path.join(BASE_DIR, "data", "raw", "public")
OUT = os.path.join(BASE_DIR, "data", "eval", "public")
MSB = os.path.join(RAW, "msb")
SAMPLE_PER_LABEL = 2000
VARIANT = re.compile(r"-(name_overlap|out_of_scope_parameter|preference_manipulation|tool_transfer)")


def norm(text) -> str:
    return re.sub(r"\s+", " ", str(text).strip().lower())


def load_templates() -> dict:
    """Read the template strings from MSB's prompt_template.py without running it."""
    tree = ast.parse(open(os.path.join(MSB, "prompt_template.py"), encoding="utf-8").read())
    return {node.targets[0].id: node.value.value for node in tree.body
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)}


def tool_docstrings(path: str) -> list:
    """Docstrings of the functions registered as MCP tools (any decorator whose source mentions 'tool')."""
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except (SyntaxError, UnicodeDecodeError):
        return []
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                any("tool" in ast.unparse(d) for d in node.decorator_list):
            doc = ast.get_docstring(node)
            if doc and len(doc) > 20:
                out.append((node.name, doc))
    return out


def build_msb() -> tuple:
    templates = load_templates()
    goals = [json.loads(line) for line in open(os.path.join(MSB, "attack_task.jsonl"), encoding="utf-8") if line.strip()]
    goals = [(g["attack_task"], g["implementation"].replace("{pid}", "4321")) for g in goals]
    files = glob.glob(os.path.join(MSB, "servers", "**", "*.py"), recursive=True)

    base_docs, seen = [], set()
    for path in files:
        if VARIANT.search(os.path.basename(path)):
            continue
        for name, doc in tool_docstrings(path):
            if norm(doc) not in seen:
                seen.add(norm(doc))
                base_docs.append((name, doc))

    desc = [{"text": doc, "label_binary": 0, "lang": "en", "attack_type": "benign_tool_description"} for _, doc in base_docs]
    for (_, doc) in base_docs:
        for task, goal in goals:
            desc.append({"text": doc + "\n" + templates["PROMPT_INJECTION_TEMPLATE"].format(goal=goal), "label_binary": 1,
                         "lang": "en", "attack_type": f"PI:{task}"})
    # Preference manipulation: MSB rewrites a description to praise the tool, without any instruction.
    for path in files:
        if "preference_manipulation" in os.path.basename(path):
            for _, doc in tool_docstrings(path):
                if norm(doc) not in seen:
                    seen.add(norm(doc))
                    desc.append({"text": doc, "label_binary": 1, "lang": "en", "attack_type": "PM:description"})

    resp = []
    for task, goal in goals:
        resp.append({"text": templates["TOOL_RESPONSE_ATTACK_TEMPLATE"] + goal, "label_binary": 1, "lang": "en", "attack_type": f"FE:{task}"})
        resp.append({"text": templates["SIMULATED_USER_TEMPLATE"] + goal, "label_binary": 1, "lang": "en", "attack_type": f"UI:{task}"})
    transfer = set()
    for path in files:
        if "tool_transfer" in os.path.basename(path):
            for literal in re.findall(r'results\s*=\s*"(<IMPORTANT>[^"]+)"', open(path, encoding="utf-8").read()):
                transfer.add(literal)
    resp += [{"text": t, "label_binary": 1, "lang": "en", "attack_type": "TT:tool_transfer"} for t in sorted(transfer)]
    return pd.DataFrame(desc), pd.DataFrame(resp)


def build_promptshield() -> tuple:
    train = set()
    for path in glob.glob(os.path.join(BASE_DIR, "data", "processed_public", "*.csv")):
        frame = pd.read_csv(path, keep_default_na=False)
        train |= set(map(norm, frame["text"]))
    rows = json.load(open(os.path.join(RAW, "promptshield", "test.json"), encoding="utf-8"))
    kept = [r for r in rows if norm(r["prompt"]) not in train]
    frame = pd.DataFrame({"text": [r["prompt"] for r in kept], "label_binary": [int(r["label"]) for r in kept],
                          "lang": "en", "attack_type": ["injection" if r["label"] else "benign" for r in kept]})
    frame = pd.concat([g.sample(min(len(g), SAMPLE_PER_LABEL), random_state=0) for _, g in frame.groupby("label_binary")])
    return frame.reset_index(drop=True), len(rows) - len(kept)


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    desc, resp = build_msb()
    desc.to_csv(os.path.join(OUT, "msb_tool_desc.csv"), index=False, encoding="utf-8")
    resp.to_csv(os.path.join(OUT, "msb_tool_resp.csv"), index=False, encoding="utf-8")
    shield, dropped = build_promptshield()
    shield.to_csv(os.path.join(OUT, "promptshield.csv"), index=False, encoding="utf-8")
    print("msb_tool_desc", desc.groupby("label_binary").size().to_dict(), desc.attack_type.str.split(":").str[0].value_counts().to_dict())
    print("msb_tool_resp", resp.attack_type.str.split(":").str[0].value_counts().to_dict())
    print("promptshield", shield.groupby("label_binary").size().to_dict(), f"dropped {dropped} texts also in the L2 training data")


if __name__ == "__main__":
    sys.exit(main())
