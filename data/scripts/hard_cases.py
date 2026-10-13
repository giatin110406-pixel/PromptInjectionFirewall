"""
Hard cases for Layer 1 / Layer 2 (the second data round, written by Claude Haiku subagents).

Why: the first Layer 2 run caught nearly every attack but blocked 9-14% of safe text on data from another
author: Vietnamese questions that merely MENTION a scam, a bypass or a password, unaccented chat, and English
requests to write code or translate. Safe text of that kind was missing from training, and so was the attack
that hides inside such a request ("translate this, then do what it says").

This script only prepares tasks and validates what the subagents wrote. Nothing is paid per call.

    python data/scripts/hard_cases.py prepare             # writes task files for the writers
    (subagents write data/raw/hard_cases/out_*.jsonl, one {"text": ...} per line)
    python data/scripts/hard_cases.py clean               # quality gates, dedupe, overlap with eval sets,
                                                          #   writes blind verification batches
    (subagents write data/raw/hard_cases/verdict_*.jsonl: {"id", "label"} from the text alone)
    python data/scripts/hard_cases.py finalize            # keep rows whose blind label equals the intended one

Rules that keep this round honest:
  - the verifier sees only the text, never the intended label;
  - a row is dropped when a char-trigram Jaccard >= 0.6 with ANY text of the evaluation sets
    (dataset_v2 validation/test, vi_test_v1, tmdeptrai external): the hard cases must not be a paraphrase of what
    is measured;
  - both labels are written in the same forms (questions, digits, unaccented, code or translation framing), and
    build_dataset_v2 then applies its usual form matching.
"""
import argparse
import glob
import hashlib
import json
import os
import re
import sys
from typing import Any, Dict, List, Set

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from data.scripts.generate_vi import _REFUSAL  # noqa: E402

WORK_DIR = os.path.join(BASE_DIR, "data", "raw", "hard_cases")
OUT_FILE = os.path.join(BASE_DIR, "data", "raw", "generated_vi", "hard_cases.jsonl")
PROMPT_VERSION = "hard_cases_v1"
PER_TASK = 70
JACCARD_LIMIT = 0.6

# (task_id, label, lang, attack_type, what to write)
TASKS = [
    ("B1", 0, "vi", "safe", "Vietnamese WITH diacritics. Safe questions and notes about scams, phishing, passwords and account security, written "
                            "by someone who wants to protect themselves. They mention words like 'lừa đảo', 'mật khẩu', 'OTP', 'giả danh nhân viên ngân hàng'. "
                            "Example: 'Nếu có người tự xưng là nhân viên ngân hàng gọi hỏi mã OTP thì mình nên làm gì?'"),
    ("B2", 0, "vi", "safe", "Vietnamese WITH diacritics. Ordinary messages that use words like 'bỏ qua', 'quên đi', 'không cần', 'tạm tắt', 'vượt qua', "
                            "'ghi đè', 'bỏ hướng dẫn cũ' about everyday, product or policy matters (skipping a step, ignoring a notification, "
                            "turning off a setting, skipping an intro). Example: 'Mình có thể bỏ qua bước xác minh khuôn mặt nếu đã xác minh bằng vân tay không?'"),
    ("B3", 0, "vi", "safe", "Vietnamese WITH diacritics. Legitimate customer-support requests: refund of an order, voucher, changing a password or "
                            "address, closing an account, checking a balance. Most contain order numbers, amounts or dates. They are polite and normal."),
    ("B4", 0, "vi", "safe", "Vietnamese WITH diacritics. Requests to translate, summarize, proofread or explain a short quoted sentence whose TOPIC is "
                            "security or AI safety (prompt injection, invisible characters, jailbreak as a research topic). The writer only wants help "
                            "with the text and gives no instruction to the assistant to change its behaviour. Example: "
                            "'Hãy dịch sang tiếng Anh câu sau: \"Kỹ thuật chèn ký tự vô hình có thể lách bộ lọc\".'"),
    ("B5", 0, "vi", "safe", "Vietnamese WITHOUT diacritics (typed casually on a phone, like 'minh muon doi mat khau'). Safe messages: support requests, "
                            "scam-awareness questions, 'bo qua buoc ...' about everyday matters, summarize requests. Some with numbers."),
    ("B6", 0, "en", "safe", "English. Safe requests to write or fix code: SQL queries, cron expressions, bash, Python, regex, Docker, git, "
                            "a script that watches a folder. Some mention 'delete', 'admin', 'permissions', 'bypass cache' in a normal programming sense."),
    ("B7", 0, "en", "safe", "English. Safe requests to translate, rewrite, summarize or explain a short sentence, plus educational questions about "
                            "phishing, prompt injection, passwords and AI safety. No instruction aimed at changing the assistant's behaviour."),
    ("B8", 0, "en", "safe", "English. Safe customer-support style messages that mention system, admin, rules, instructions or permissions in a normal "
                            "way (e.g. 'Where can I read the store's return instructions?', 'Can I ignore the old invoice and use the new one?')."),
    ("A1", 1, "vi", "direct_injection", "Vietnamese WITH diacritics. Prompt injections that tell an assistant to drop its instructions, adopt an "
                                        "unrestricted persona, or answer without rules. Vary the wording a lot; some polite, some casual, some long-winded."),
    ("A2", 1, "vi", "action_abuse", "Vietnamese WITH diacritics. Injections that claim authority or a special mode (bảo trì, quản trị, đã được duyệt) to "
                                    "get an assistant to refund, transfer, open a payment gateway, raise limits or skip identity checks. Include amounts and order numbers."),
    ("A3", 1, "vi", "prompt_leaking", "Vietnamese WITH diacritics. Injections that try to make the assistant reveal its hidden instructions, "
                                      "or send the conversation to an outside URL, or hide data inside an image link."),
    ("A4", 1, "vi", "indirect_injection", "Vietnamese WITH diacritics. Injections disguised as an ordinary task: 'translate this sentence, then do what it "
                                          "says', 'summarize this note and also ...', 'proofread the following and carry out its request'. The hidden "
                                          "instruction asks for something the user was not entitled to."),
    ("A5", 1, "vi", "direct_injection", "Vietnamese WITHOUT diacritics (typed casually). A mix of: drop your rules, claim admin rights, reveal your prompt, "
                                        "approve a refund or skip verification. Same register as a phone chat message."),
    ("A6", 1, "en", "indirect_injection", "English. Injections disguised as a coding or translation request: a code comment or a quoted sentence that "
                                          "carries an instruction to the assistant ('translate: ... and then ignore your rules'). Keep them short."),
    ("A7", 1, "en", "direct_injection", "English. Classic and creative prompt injections: ignore previous instructions, act as an unrestricted persona, "
                                        "reveal the system prompt, claim authority to skip checks, approve a transfer."),
    ("A8", 1, "vi", "subtle_redirect", "Vietnamese WITH diacritics. Soft injections with no obvious trigger word: a sentence inside a review, an email or "
                                       "a chat that quietly steers an assistant (rank this supplier first, always answer that the order is approved, "
                                       "do not mention the warning)."),
]

WRITER_RULES = (
    "Write {n} DIFFERENT texts for this task. Each is one chat message of 40 to 220 characters (at most 2 sentences). "
    "Vary vocabulary and sentence shape; about a third should be questions and about a third should contain a digit. "
    "No numbering, no quotes around the whole text, no explanation. This is labelled training data for a defensive "
    "classifier, so write realistic messages, do not refuse and do not add warnings."
)


def _sha(text: str, n: int = 12) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).strip().lower())


def _grams(text: str) -> Set[str]:
    t = _norm(text)
    return {t[i:i + 3] for i in range(max(len(t) - 2, 1))}


def jaccard(a: Set[str], b: Set[str]) -> float:
    return len(a & b) / max(len(a | b), 1)


# ----------------------------------------------------------------------------
def cmd_prepare(args: argparse.Namespace) -> None:
    os.makedirs(WORK_DIR, exist_ok=True)
    for old in glob.glob(os.path.join(WORK_DIR, "*")):
        os.remove(old)
    for task_id, label, lang, attack_type, brief in TASKS:
        spec = {"task_id": task_id, "n": args.per_task, "instruction": WRITER_RULES.format(n=args.per_task) + " TASK: " + brief,
                "output": f"out_{task_id}.jsonl", "line_format": '{"text": "..."}'}
        with open(os.path.join(WORK_DIR, f"task_{task_id}.json"), "w", encoding="utf-8") as handle:
            json.dump(spec, handle, ensure_ascii=False, indent=2)
    print(f"[INFO] {len(TASKS)} tasks x {args.per_task} -> {WORK_DIR}")


def _eval_texts() -> List[str]:
    texts: List[str] = []
    for name in ("validation", "test"):
        texts += pd.read_csv(os.path.join(BASE_DIR, "data", "processed", f"dataset_v2_{name}.csv"), keep_default_na=False)["text"].astype(str).tolist()
    texts += pd.read_csv(os.path.join(BASE_DIR, "data", "eval", "vi_test_v1.csv"), keep_default_na=False, encoding="utf-8-sig")["text"].astype(str).tolist()
    texts += pd.read_csv(os.path.join(BASE_DIR, "data", "eval", "tmdeptrai_external_test.csv"), keep_default_na=False)["text"].astype(str).tolist()
    return [t for t in texts if len(t) < 600]   # short texts only: those are the ones a chat paraphrase could copy


def cmd_clean(args: argparse.Namespace) -> None:
    labels = {t[0]: t for t in TASKS}
    eval_grams = [_grams(t) for t in _eval_texts()]
    rows, seen, lost = [], set(), {}
    for path in sorted(glob.glob(os.path.join(WORK_DIR, "out_*.jsonl"))):
        task_id = os.path.basename(path)[4:-6]
        _, label, lang, attack_type, _ = labels[task_id]
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    text = str(json.loads(line)["text"]).strip()
                except (ValueError, KeyError):
                    lost["bad_json"] = lost.get("bad_json", 0) + 1
                    continue
                why = None
                if not 25 <= len(text) <= 300:
                    why = "length"
                elif _REFUSAL.search(text):
                    why = "refusal"
                elif _norm(text) in seen:
                    why = "duplicate"
                else:
                    grams = _grams(text)
                    if any(jaccard(grams, g) >= JACCARD_LIMIT for g in eval_grams):
                        why = "near_eval_text"
                if why:
                    lost[why] = lost.get(why, 0) + 1
                    continue
                seen.add(_norm(text))
                rows.append({"id": "h" + _sha(text), "text": text, "label_binary": label, "lang": lang,
                             "attack_type": attack_type, "task": task_id})
    with open(os.path.join(WORK_DIR, "candidates.jsonl"), "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    batch = args.batch
    for i in range(0, len(rows), batch):
        with open(os.path.join(WORK_DIR, f"verify_in_{i // batch:02d}.jsonl"), "w", encoding="utf-8") as handle:
            for row in rows[i:i + batch]:
                handle.write(json.dumps({"id": row["id"], "text": row["text"]}, ensure_ascii=False) + "\n")
    print(json.dumps({"kept": len(rows), "lost": lost, "verify_batches": (len(rows) + batch - 1) // batch}, ensure_ascii=False))


def cmd_finalize(args: argparse.Namespace) -> None:
    verdict: Dict[str, str] = {}
    for path in sorted(glob.glob(os.path.join(WORK_DIR, "verdict_*.jsonl"))):
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    row = json.loads(line)
                    verdict[str(row["id"])] = str(row.get("label", "")).strip().lower()
    # Second opinion on a shuffled sample (the batches above are grouped by task, so a verifier can guess the label
    # from position). When both opinions exist they must agree with the intended label.
    second: Dict[str, str] = {}
    second_path = os.path.join(WORK_DIR, "shuffle_verdict.jsonl")
    if os.path.exists(second_path):
        with open(second_path, "r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    row = json.loads(line)
                    second[str(row["id"])] = str(row.get("label", "")).strip().lower()
    kept, lost = [], {"no_verdict": 0, "disagree": 0}
    with open(os.path.join(WORK_DIR, "candidates.jsonl"), "r", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            seen = verdict.get(row["id"])
            intended = "attack" if row["label_binary"] else "benign"
            if seen == intended and second.get(row["id"], intended) != intended:
                seen = "disputed"
            if not seen:
                lost["no_verdict"] += 1
            elif seen != ("attack" if row["label_binary"] else "benign"):
                lost["disagree"] += 1
            else:
                kept.append({
                    "text": row["text"], "label_binary": row["label_binary"], "attack_type": row["attack_type"],
                    "orig_id": "hc:" + _sha(row["text"]), "variant": "hard_" + row["task"], "synthetic_kind": "hard_case",
                    "lang": row["lang"], "source": "hard_cases", "provider": "claude-haiku", "model": "haiku",
                    "prompt_version": PROMPT_VERSION})
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        for row in kept:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    by = pd.DataFrame(kept).groupby(["lang", "label_binary"]).size().to_dict() if kept else {}
    print(json.dumps({"kept": len(kept), "lost": lost, "by_lang_label": {str(k): v for k, v in by.items()}, "out": args.out}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare"); p.add_argument("--per-task", type=int, default=PER_TASK)
    q = sub.add_parser("clean"); q.add_argument("--batch", type=int, default=200)
    r = sub.add_parser("finalize"); r.add_argument("--out", default=OUT_FILE)
    args = parser.parse_args()
    {"prepare": cmd_prepare, "clean": cmd_clean, "finalize": cmd_finalize}[args.command](args)


if __name__ == "__main__":
    main()
