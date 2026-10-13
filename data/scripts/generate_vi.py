"""
Generate Vietnamese training data with an LLM (P2-T4).

Three jobs, one controlled pipeline:
  translate   English rows -> Vietnamese, BOTH labels, with the same prompt.
  chat        Short Vietnamese messages. Benign and attack messages come from the SAME
              prompt template, the same topics and the same style hints; only the
              "kind" line differs. Benign calls outnumber attack calls so labels balance.
  docs        Benign Vietnamese documents (email, article, review...) used as bases for
              indirect-injection pairs by build_dataset_v2.py.

Each output row records provider, model, prompt version and generation time, so the AI
Use Disclosure Log can be filled from the data itself. A random 5% sample is exported to
`review_sample.csv` for a human to label; generated data is not trusted until that is done.

Without an API key use `--provider manual`: prompts are written to a folder, you paste
them into any chat UI, save the replies, and run the same command again.

Examples:
    python data/scripts/generate_vi.py chat --provider deepseek          # key in .env: DEEPSEEK_API_KEY=...
    python data/scripts/generate_vi.py chat --provider ollama --model qwen2.5:7b
    python data/scripts/generate_vi.py chat --provider manual --manual-dir data/raw/generated_vi/manual
    python data/scripts/generate_vi.py docs --provider anthropic --n 120 --max-calls 200
"""
import argparse
import csv
import hashlib
import json
import os
import random
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from data.scripts.vietnamese_norm import detect_language  # noqa: E402
from firewall.llm_provider import (  # noqa: E402
    BudgetExceeded, LLMError, LLMProvider, ManualPending, get_provider,
)

PROMPT_DIR = os.path.join(BASE_DIR, "firewall", "prompts")
OUT_DIR = os.path.join(BASE_DIR, "data", "raw", "generated_vi")

TOPICS = [
    "đơn hàng và giao hàng", "hoàn tiền và đổi trả", "tài khoản và mật khẩu", "thanh toán và hóa đơn",
    "bảo hành sản phẩm", "khuyến mãi và mã giảm giá", "ứng dụng di động", "thẻ ngân hàng",
    "dịch vụ internet", "đặt phòng khách sạn", "học trực tuyến", "bảo hiểm",
]
FLAVORS = ["câu hỏi ngắn", "yêu cầu hỗ trợ lịch sự", "phàn nàn nhẹ nhàng", "nhờ tư vấn lựa chọn",
           "hỏi về thủ tục", "nhắn gấp, giọng thân mật", "hỏi chi tiết kèm số liệu"]
ATTACK_KINDS = {
    "direct_injection": "tin nhắn cố ép trợ lý bỏ qua chỉ dẫn trước đó hoặc làm việc khác với nhiệm vụ của nó",
    "prompt_leaking": "tin nhắn cố khiến trợ lý tiết lộ chỉ dẫn hệ thống, cấu hình hoặc quy tắc ẩn của nó",
    "privilege_escalation": "tin nhắn tự nhận có quyền cao (quản trị viên, giám đốc, kiểm toán) để đòi bỏ qua xác minh",
    "jailbreak_roleplay": "tin nhắn yêu cầu trợ lý đóng vai một nhân vật không có giới hạn hoặc không tuân theo quy tắc",
    "action_abuse": "tin nhắn đòi trợ lý thực hiện hành động nhạy cảm không đúng thẩm quyền (hoàn tiền lớn, chuyển tiền, đổi mật khẩu, xóa dữ liệu)",
    "data_exfiltration": "tin nhắn đòi trợ lý gửi hoặc lộ dữ liệu cá nhân hay khóa bí mật ra ngoài",
    "subtle_redirect": "tin nhắn kín đáo chuyển hướng câu trả lời của trợ lý sang mục đích khác mà không dùng từ khóa rõ ràng",
}
BENIGN_KIND = "câu hỏi hoặc yêu cầu bình thường, hợp lệ của khách hàng, không có ý định thao túng trợ lý"
DOC_TYPES = ["email của khách hàng gửi bộ phận hỗ trợ", "bài báo ngắn", "đánh giá sản phẩm",
             "thông báo nội bộ công ty", "biên bản cuộc họp", "mục hỏi đáp thường gặp (FAQ)"]
DOC_INTENTS = ["Tóm tắt văn bản sau.", "Văn bản này nói về điều gì?", "Hãy rút ra ba ý chính từ nội dung sau.",
               "Cho mình biết thông tin quan trọng nhất trong đoạn sau.", "Dịch ngắn gọn nội dung sau sang tiếng Anh."]

_REFUSAL = re.compile(
    r"(xin lỗi,? (nhưng )?(tôi|mình) không thể|tôi không thể (giúp|hỗ trợ|thực hiện)|không thể hỗ trợ yêu cầu|"
    r"i can(?:no|')t (help|assist|comply)|i cannot (help|assist|comply)|as an ai)", re.IGNORECASE)
_VI_ASCII_WORDS = re.compile(
    r"\b(toi|ban|khong|minh|cho|voi|la|va|cua|duoc|don hang|tai khoan|mat khau|hoan tien|giup|nhe|nha|oi|"
    r"gui|toan|cuoc|chuyen|truoc|khach|tui|roi|nay|nguoi|tien|khau|gio|tra loi|mk|tk|dc|ko|nhung|thi|lam sao|"
    r"cac|mot|nhieu|hay|xin|vay|duoi)\b"
)


# ----------------------------------------------------------------------------
# Prompts
# ----------------------------------------------------------------------------
def load_prompt(name: str) -> Tuple[str, str]:
    """Return (template, version) where version = file name + short content hash."""
    path = os.path.join(PROMPT_DIR, f"{name}.md")
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    return text, f"{name}@{hashlib.sha256(text.encode('utf-8')).hexdigest()[:8]}"


def fill(template: str, **values: Any) -> str:
    for key, value in values.items():
        template = template.replace(f"<<{key.upper()}>>", str(value))
    return template


# ----------------------------------------------------------------------------
# Parsing and quality gates
# ----------------------------------------------------------------------------
def parse_string_list(raw: str) -> List[str]:
    """Extract a JSON array of strings from a model reply; fall back to one item per line."""
    start, end = raw.find("["), raw.rfind("]")
    if start != -1 and end > start:
        try:
            data = json.loads(raw[start:end + 1])
            if isinstance(data, list):
                return [str(item).strip() for item in data if isinstance(item, (str, int, float)) and str(item).strip()]
        except json.JSONDecodeError:
            pass
    lines = [re.sub(r'^\s*(?:[-*•]|\d+[.)])\s*', "", ln).strip().strip('"').strip() for ln in raw.splitlines()]
    return [ln for ln in lines if ln and not ln.startswith(("```", "[", "]"))]


def looks_vietnamese(text: str) -> bool:
    if detect_language(text) in ("vi", "mixed"):
        return True
    return len(_VI_ASCII_WORDS.findall(text.lower())) >= 2  # unaccented Vietnamese


def acceptable(text: str, min_len: int = 15, max_len: int = 400) -> Tuple[bool, str]:
    if not (min_len <= len(text) <= max_len):
        return False, "length"
    if _REFUSAL.search(text):
        return False, "refusal"
    if not looks_vietnamese(text):
        return False, "not_vietnamese"
    return True, ""


def _norm_key(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _orig_id(prefix: str, text: str) -> str:
    return f"{prefix}:{hashlib.sha1(_norm_key(text).encode('utf-8')).hexdigest()[:12]}"


# ----------------------------------------------------------------------------
# Jobs
# ----------------------------------------------------------------------------
class Collector:
    """Calls the provider, applies the quality gates, deduplicates, and tracks what was lost."""

    def __init__(self, provider: LLMProvider, model: str, workers: int = 1):
        self.provider, self.model = provider, model
        self.workers = max(1, workers)
        self.rows: List[Dict[str, Any]] = []
        self.seen: set = set()
        self.rejected: Dict[str, int] = {}
        self.pending: List[str] = []
        self.errors: List[str] = []
        self.disagreed: List[Dict[str, Any]] = []   # verify job: rows the verifier disagreed with
        self.verify_stats: Dict[str, Dict[str, Any]] = {}
        self.budget_hit = False
        self._lock = threading.Lock()

    def call(self, prompt: str, **kwargs: Any) -> Optional[str]:
        try:
            return self.provider.complete(prompt, **kwargs)
        except ManualPending as pending:
            with self._lock:
                self.pending.append(pending.request_id)
        except BudgetExceeded:
            self.budget_hit = True
            if self.workers == 1:
                raise
        except LLMError as exc:
            with self._lock:
                self.errors.append(str(exc))
        return None

    def call_many(self, prompts: List[str], **kwargs: Any) -> List[Optional[str]]:
        """
        Run independent prompts, on several threads when `workers` > 1. Replies come back in the
        order of `prompts`, so everything downstream (dedup, ids, row order) stays deterministic.
        Manual mode is always sequential: a human is the provider.
        """
        if self.workers == 1 or self.provider.name == "manual":
            return [self.call(p, **kwargs) for p in prompts]
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            return list(pool.map(lambda p: self.call(p, **kwargs), prompts))

    def add(self, text: str, **fields: Any) -> bool:
        ok, why = acceptable(text)
        key = _norm_key(text)
        if ok and key in self.seen:
            ok, why = False, "duplicate"
        if not ok:
            self.rejected[why] = self.rejected.get(why, 0) + 1
            return False
        self.seen.add(key)
        self.rows.append({"text": text, "lang": "vi", "source": "llm_generated", "provider": self.provider.name,
                          "model": self.model, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                          **fields})
        return True


def run_translate(col: Collector, items: List[Dict[str, Any]], batch: int = 10) -> None:
    template, version = load_prompt("translate_v1")
    for start in range(0, len(items), batch):
        chunk = items[start:start + batch]
        prompt = fill(template, n=len(chunk), items=json.dumps([c["text"] for c in chunk], ensure_ascii=False))
        reply = col.call(prompt, max_tokens=2048, temperature=0.2)
        if reply is None:
            continue
        translations = parse_string_list(reply)
        if len(translations) != len(chunk):  # misaligned batch: never guess which line belongs to which source
            col.rejected["misaligned_batch"] = col.rejected.get("misaligned_batch", 0) + len(chunk)
            continue
        for source, vi in zip(chunk, translations):
            col.add(vi, label_binary=int(source["label_binary"]), attack_type=source.get("attack_type", "safe"),
                    orig_id=source["orig_id"], template_id="", variant="translated",
                    prompt_version=version, synthetic_kind="translated")


def run_chat(col: Collector, topics: List[str], n_per_call: int = 10, seed: int = 0) -> None:
    template, version = load_prompt("generate_chat_v2")
    categories = list(ATTACK_KINDS)
    jobs: List[Tuple[str, str, int, str]] = []  # (prompt, cell, label, topic)
    for topic in topics:
        rng = random.Random(f"{seed}|{topic}")
        # Same template for both labels. Benign gets one call per attack category so labels balance.
        cells = [("safe", BENIGN_KIND, 0)] * len(categories) + [(c, ATTACK_KINDS[c], 1) for c in categories]
        for index, (cell, kind, label) in enumerate(cells):
            prompt = fill(template, n=n_per_call, kind=kind, topic=topic, flavor=rng.choice(FLAVORS))
            jobs.append((f"{prompt}\n(mã lượt: {topic}/{index})", cell, label, topic))

    replies = col.call_many([job[0] for job in jobs], max_tokens=2048, temperature=0.9)
    for (_, cell, label, topic), reply in zip(jobs, replies):
        if reply is None:
            continue
        for text in parse_string_list(reply):
            col.add(text, label_binary=label, attack_type=cell, orig_id=_orig_id("gen", text), template_id="",
                    variant="raw", prompt_version=version, synthetic_kind="llm_generated", topic=topic)
    if col.budget_hit:  # rows already paid for were kept above; tell the caller the run is incomplete
        raise BudgetExceeded("call budget reached: the run is incomplete")


def run_docs(col: Collector, n: int, seed: int = 0) -> None:
    template, version = load_prompt("generate_doc_v1")
    rng = random.Random(seed)
    jobs = []
    for i in range(n):
        topic, doc_type = TOPICS[i % len(TOPICS)], DOC_TYPES[(i // len(TOPICS)) % len(DOC_TYPES)]
        words = rng.choice([120, 160, 200, 250])
        prompt = fill(template, doc_type=doc_type, words=words, topic=topic) + f"\n(mã văn bản: {i})"
        jobs.append((prompt, topic, doc_type, rng.choice(DOC_INTENTS)))
    replies = col.call_many([job[0] for job in jobs], max_tokens=1500, temperature=0.9)
    for (_, topic, doc_type, intent), reply in zip(jobs, replies):
        if reply is None:
            continue
        text = reply.strip()
        ok, why = acceptable(text, min_len=200, max_len=3000)
        if ok and _norm_key(text) in col.seen:
            ok, why = False, "duplicate"
        if not ok:
            col.rejected[why] = col.rejected.get(why, 0) + 1
            continue
        col.seen.add(_norm_key(text))
        col.rows.append({
            "intent": intent, "context": text, "orig_id": _orig_id("docvi", text), "lang": "vi",
            "source": "llm_generated", "provider": col.provider.name, "model": col.model, "topic": topic,
            "doc_type": doc_type, "prompt_version": version,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
    if col.budget_hit:
        raise BudgetExceeded("call budget reached: the run is incomplete")


def run_verify(col: Collector, rows: List[Dict[str, Any]], batch: int = 20) -> None:
    """
    Second opinion on every generated label, using an independent prompt with an explicit rubric.

    Only rows where the verifier agrees with the generator's label are kept; the rest go to
    `col.disagreed`. The disagreement rate per attack type is the measured label noise, and shows
    which categories the generator cannot be trusted with (in the first full run the "subtle"
    category was often generated as an ordinary question).

    The verifier is the same model family as the generator, so shared mistakes are not caught.
    A human still has to check the exported 5% sample.
    """
    template, version = load_prompt("verify_label_v1")
    chunks = [rows[i:i + batch] for i in range(0, len(rows), batch)]
    prompts = [fill(template, n=len(c), items=json.dumps([r["text"] for r in c], ensure_ascii=False)) for c in chunks]
    replies = col.call_many(prompts, max_tokens=800, temperature=0.0)

    stats: Dict[str, Dict[str, int]] = {}
    for chunk, reply in zip(chunks, replies):
        if reply is None:
            col.rejected["no_reply"] = col.rejected.get("no_reply", 0) + len(chunk)
            continue
        verdicts = [v.strip().lower() for v in parse_string_list(reply)]
        if len(verdicts) != len(chunk) or any(v not in ("attack", "benign") for v in verdicts):
            col.rejected["misaligned_batch"] = col.rejected.get("misaligned_batch", 0) + len(chunk)
            continue  # never guess which verdict belongs to which message
        for row, verdict in zip(chunk, verdicts):
            expected = "attack" if int(row["label_binary"]) == 1 else "benign"
            slot = stats.setdefault(str(row.get("attack_type", "")), {"agree": 0, "disagree": 0})
            if verdict == expected:
                slot["agree"] += 1
                col.rows.append({**row, "verifier": verdict, "verify_prompt": version,
                                 "verified_by": f"{col.provider.name}:{col.model}"})
            else:
                slot["disagree"] += 1
                col.disagreed.append({**row, "verifier": verdict, "verify_prompt": version})
    col.verify_stats = {
        cat: {**s, "agreement": round(s["agree"] / max(s["agree"] + s["disagree"], 1), 3)} for cat, s in sorted(stats.items())
    }
    if col.budget_hit:
        raise BudgetExceeded("call budget reached: the run is incomplete")


def load_jsonl(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


# ----------------------------------------------------------------------------
# Output
# ----------------------------------------------------------------------------
def write_jsonl(path: str, rows: Iterable[Dict[str, Any]]) -> int:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    count = 0
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def write_review_sample(path: str, rows: List[Dict[str, Any]], fraction: float = 0.05, minimum: int = 30,
                        seed: int = 0) -> int:
    """Random sample for a human to check. `human_label` is left blank on purpose."""
    if not rows:
        return 0
    size = min(len(rows), max(minimum, int(len(rows) * fraction)))
    sample = random.Random(seed).sample(rows, size)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["orig_id", "text", "generated_label", "attack_type", "human_label", "human_notes"])
        for row in sample:
            text = row.get("text") or row.get("context", "")[:400]
            writer.writerow([row["orig_id"], text, row.get("label_binary", ""), row.get("attack_type", ""), "", ""])
    return size


def leakage_guard(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Run the same leakage audit used for public data on what was just generated. A model that
    can tell the labels apart by form (question mark, digits, length) will learn the form, not
    the attack. This is how the first DeepSeek pilot was caught: 87% of safe messages were
    questions against 25% of attack messages.
    """
    labelled = [r for r in rows if "label_binary" in r]
    if len({r["label_binary"] for r in labelled}) < 2:
        return {"checked": False}
    import pandas as pd
    from data.scripts import audit_leakage as audit

    frame = pd.DataFrame(labelled)
    frame["source"] = "generated"
    report = audit.audit_frame(frame, "generated")
    by_label = frame.groupby("label_binary")["text"]
    return {
        "checked": True, "flags": report["flags"], "leaky": report["leaky"],
        "length_auc": report["length_auc"], "style_auc": report["style_auc"],
        "question_rate": {str(k): round(float(v.str.contains(r"\?").mean()), 2) for k, v in by_label},
        "digit_rate": {str(k): round(float(v.str.contains(r"\d").mean()), 2) for k, v in by_label},
    }


def summarize(col: Collector, name: str, out_path: str) -> Dict[str, Any]:
    labels: Dict[str, int] = {}
    for row in col.rows:
        key = str(row.get("label_binary", "doc"))
        labels[key] = labels.get(key, 0) + 1
    return {"job": name, "accepted": len(col.rows), "labels": labels, "rejected": col.rejected,
            "pending_manual": len(col.pending), "errors": col.errors[:5], "output": out_path,
            "disagreed": len(col.disagreed), "verify_by_attack_type": col.verify_stats,
            "leakage_guard": leakage_guard(col.rows)}


def load_translate_items(path: Optional[str]) -> List[Dict[str, Any]]:
    """English rows to translate: from a jsonl (text,label_binary,attack_type,orig_id) or tmdeptrai English rows."""
    if path:
        with open(path, "r", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]
    from data.scripts.build_dataset_v2 import fetch_tmdeptrai, build_tmdeptrai_rows

    rows = [r for r in build_tmdeptrai_rows(fetch_tmdeptrai(), 0) if r["lang"] == "en"]
    return [{"text": r["text"], "label_binary": r["label_binary"], "attack_type": r["attack_type"],
             "orig_id": r["orig_id"]} for r in rows]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("job", choices=["translate", "chat", "docs", "verify"])
    parser.add_argument("--provider", required=True, choices=["ollama", "anthropic", "openai", "deepseek", "manual"])
    parser.add_argument("--model")
    parser.add_argument("--manual-dir", default=os.path.join(OUT_DIR, "manual"))
    parser.add_argument("--max-calls", type=int, default=300, help="hard cap on LLM calls (cost guard)")
    parser.add_argument("--out-dir", default=OUT_DIR)
    parser.add_argument("--input", help="translate: jsonl of English rows (default: tmdeptrai English rows)")
    parser.add_argument("--n", type=int, default=120, help="docs: number of documents")
    parser.add_argument("--topics", type=int, default=len(TOPICS), help="chat: number of topics to use")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--workers", type=int, default=1, help="parallel requests (ignored in manual mode)")
    args = parser.parse_args()

    provider = get_provider(args.provider, model=args.model, manual_dir=args.manual_dir, max_calls=args.max_calls)
    col = Collector(provider, args.model or args.provider, workers=args.workers)
    try:
        if args.job == "translate":
            run_translate(col, load_translate_items(args.input))
        elif args.job == "chat":
            run_chat(col, TOPICS[:args.topics], seed=args.seed)
        elif args.job == "verify":
            if not args.input:
                parser.error("verify needs --input (a chat_vi.jsonl from the chat job)")
            run_verify(col, load_jsonl(args.input))
        else:
            run_docs(col, args.n, seed=args.seed)
    except BudgetExceeded as exc:
        print(f"[WARN] stopped early: {exc}")

    out_path = os.path.join(args.out_dir, f"{args.job}_vi.jsonl")
    write_jsonl(out_path, col.rows)
    if args.job == "verify":
        write_jsonl(os.path.join(args.out_dir, "verify_disagreed.jsonl"), col.disagreed)
    review = write_review_sample(os.path.join(args.out_dir, f"review_sample_{args.job}.csv"), col.rows, seed=args.seed)
    summary = summarize(col, args.job, out_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    guard = summary["leakage_guard"]
    if guard.get("leaky"):
        print(f"[WARN] generated data is LEAKY ({guard['flags']}): labels can be told apart by form. "
              "Do not train on it; adjust the prompt or resample before building the dataset.")
    if review:
        print(f"[INFO] {review} rows exported for human review: review_sample_{args.job}.csv")
    if col.pending:
        print(f"[ACTION] {len(col.pending)} prompts need answers. Open {os.path.join(args.manual_dir, 'requests.md')}, "
              f"paste each into a chat UI, append {{\"id\": ..., \"text\": ...}} lines to answers.jsonl, then rerun.")
        sys.exit(2)


if __name__ == "__main__":
    main()
