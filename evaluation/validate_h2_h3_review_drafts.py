"""Static checks only: no engine, detector, scores or decision-based filtering."""
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DATA = ROOT / "data/eval/v4/ai_draft_for_review"


def read(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]


def normalized(text):
    return re.sub(r"\s+", " ", text.strip()).casefold()


BASE_ACTIONS = {"refund", "transfer_money", "data_access", "role_escalation", "password_reset", "account_recovery", "voucher_apply"}
EGRESS = {"send_email", "share_file", "http_request", "post_message"}
TARGET_FIELDS = {"refund": ("order_id",), "transfer_money": ("to_account",), "data_access": ("resource",),
                 "password_reset": ("target_account",), "account_recovery": ("target_account",),
                 "voucher_apply": ("voucher_code",), "send_email": ("to", "cc"),
                 "share_file": ("share_with",), "http_request": ("url",), "post_message": ("target",)}


def leaves(value):
    if isinstance(value, dict):
        return [leaf for v in value.values() for leaf in leaves(v)]
    if isinstance(value, list):
        return [leaf for v in value for leaf in leaves(v)]
    return [value]


def mentions(value, text):
    return bool(re.search(r"(?<![\w@])" + re.escape(str(value)) + r"(?![\w@])", text, re.IGNORECASE))


def diversity(rows):
    turns = [m for row in rows for m in row["user_messages"]]
    digit_masked = Counter(re.sub(r"\d+", "#", normalized(t)) for t in turns)
    def mask_slots(text):
        text = re.sub(r"https?://[^\s<>]+", "<url>", normalized(text))
        text = re.sub(r"[\w.%+-]+@[\w.-]+\.[a-z]{2,}", "<email>", text)
        text = re.sub(r"\b[a-z]{1,12}[-_]?\d[\w-]*\b", "<id>", text)
        return re.sub(r"\d+", "#", text)
    slot_masked = Counter(mask_slots(t) for t in turns)
    return dict(user_messages=len(turns), unique_after_digit_mask=len(digit_masked), max_digit_masked_repeat=max(digit_masked.values()),
                unique_after_slot_mask=len(slot_masked), max_slot_masked_repeat=max(slot_masked.values()),
                repeated_digit_masked=[dict(text=t, count=n) for t,n in digit_masked.items() if n > 1],
                repeated_slot_masked=[dict(text=t, count=n) for t,n in slot_masked.items() if n > 1])


def main():
    # Pydantic payload models only. Do not instantiate a firewall/Runner or
    # request a classification. No text is selected based on model outcomes.
    from firewall.layer4 import Layer4Validator
    from firewall.values import normalize_value, load_trusted_book
    attacks = read(DATA / "attack_scenarios_vi.jsonl")
    flows = read(DATA / "friction_flows.jsonl")
    book = load_trusted_book()
    errors = []
    def check(condition, message):
        if not condition:
            errors.append(message)
    check(40 <= len(attacks) <= 60 and len(flows) == 96, "dataset size")
    check(sum(not r["has_explicit_instruction"] for r in attacks) >= len(attacks) / 4, "value-only coverage")
    check(sum(r["channel"] == "tool_json" for r in attacks) >= 10, "tool JSON coverage")
    check(BASE_ACTIONS <= {r["target_action"] for r in attacks}, "retain all seven original target actions")
    check(EGRESS <= {r["target_action"] for r in attacks}, "H2 egress coverage")
    check(EGRESS <= {r["action"]["type"] for r in flows}, "H3 egress coverage")
    core_path = DATA / "compatibility/core7/attack_scenarios_vi.jsonl"
    core = read(core_path)
    check(core == [r for r in attacks if r["target_action"] in BASE_ACTIONS], "core cohort differs from full H2")
    check(40 <= len(core) <= 60 and {r["target_action"] for r in core} == BASE_ACTIONS, "legacy core count/action enum")
    check(sum(not r["has_explicit_instruction"] for r in core) >= len(core) / 4, "legacy core value-only coverage")
    check(sum(r["channel"] == "tool_json" for r in core) >= 10, "legacy core tool coverage")
    owners = ["Tín", "Thịnh", "Khang", "Thắng"]
    check(Counter(r["assigned_to"] for r in attacks) == {p: len(attacks) // 4 for p in owners}, "H2 assignment")
    check(Counter(r["assigned_to"] for r in flows) == {p: 24 for p in owners}, "H3 assignment")
    for name, rows in (("H2", attacks), ("H3", flows)):
        check(len({r["id"] for r in rows}) == len(rows), name + " duplicate IDs")
        check(all("author" not in r and r["authorship"] == "ai_generated" for r in rows), name + " source metadata")
        check(all(isinstance(r["id"],str) and r["id"] and r["domain"] in {"shop","bank","work","other"} for r in rows), name + " ID/domain types")
    for row in attacks:
        check(all(k in row for k in ("id", "domain", "channel", "content", "has_explicit_instruction", "target_action", "target_payload", "attacker_value", "notes")), row["id"] + " H2 fields")
        check(isinstance(row["content"], str) and isinstance(row["target_payload"], dict), row["id"] + " H2 field types")
        check(all(isinstance(row[k],str) and row[k] for k in ("channel","target_action","attacker_value","notes")), row["id"] + " string types")
        check(row["channel"] in {"email", "web", "tool_json", "document", "review"}, row["id"] + " channel")
        check(type(row["has_explicit_instruction"]) is bool, row["id"] + " boolean")
        check(bool(row["attacker_value"]) and row["attacker_value"] in row["content"], row["id"] + " attacker_value")
        check(row["attacker_value"] in leaves(row["target_payload"]), row["id"] + " target payload value")
        if row["channel"] == "tool_json":
            json.loads(row["content"])
        try:
            Layer4Validator.ACTION_MODELS[row["target_action"]].model_validate(row["target_payload"])
        except Exception as exc:
            errors.append(row["id"] + " payload schema: " + str(exc))
    families = defaultdict(set)
    for row in flows:
        check(all(k in row for k in ("id", "domain", "lang", "user_messages", "content", "action", "destination_from", "split")), row["id"] + " H3 fields")
        check(isinstance(row["user_messages"], list) and bool(row["user_messages"]) and all(isinstance(m,str) and m.strip() for m in row["user_messages"]), row["id"] + " message types")
        check(isinstance(row["content"], dict) and isinstance(row["content"]["text"], str), row["id"] + " content types")
        check(isinstance(row["action"], dict) and isinstance(row["action"]["payload"], dict), row["id"] + " action types")
        families[row["family"]].add(row["split"])
        a = row["action"]
        payload = a["payload"]
        values = [v for k in TARGET_FIELDS[a["type"]] for v in leaves(payload.get(k, []))]
        user_text = " ".join(row["user_messages"])
        typed = all(mentions(v, user_text) for v in values)
        saved = all(book.contains(payload["user_id"], normalize_value(v)) for v in values)
        check(row["content"]["source"] in {"email", "web", "tool_json", "document"}, row["id"] + " source")
        if row["destination_from"] == "user":
            check(typed, row["id"] + " user target absent")
        elif row["destination_from"] == "saved":
            check(values == ["0451000123456"] and saved and not typed, row["id"] + " saved fixture")
        elif row["destination_from"] == "content":
            check(all(not mentions(v,user_text) and mentions(v,row["content"]["text"]) for v in values) and not saved, row["id"] + " content-only target")
        else:
            errors.append(row["id"] + " invalid destination_from")
        if row["content"]["source"] == "tool_json":
            json.loads(row["content"]["text"])
        try:
            Layer4Validator.ACTION_MODELS[a["type"]].model_validate(payload)
        except Exception as exc:
            errors.append(row["id"] + " payload schema: " + str(exc))
    check(all(len(splits) == 1 for splits in families.values()), "topic crosses split")
    check(Counter(r["split"] for r in flows) == {"dev": 48, "test": 48}, "split balance")
    check(Counter(r["lang"] for r in flows) == {"vi": 48, "en": 48}, "language balance")
    check(Counter(r["destination_from"] for r in flows) == {"user": 48, "saved": 16, "content": 32}, "destination balance")
    check(all(Counter(r["lang"] for r in flows if r["family"] == family) == {"vi": 2, "en": 2} for family in families), "topic bilingual coverage")
    text_diversity = diversity(flows)
    check(text_diversity["max_digit_masked_repeat"] == 1 and text_diversity["max_slot_masked_repeat"] == 1, "repeated user-message skeleton")
    check(all("Chứng từ nghiệp vụ giả lập" not in r["content"]["text"] for r in flows), "generic document stub")
    sources = json.loads((DATA / "SOURCES.json").read_text(encoding="utf-8"))["sources"]
    check(all(r.get("source_refs") and set(r["source_refs"]) <= set(sources) for r in attacks + flows), "source reference IDs")
    assigned = {}
    for person in owners:
        aa = [r for r in attacks if r["assigned_to"] == person]
        ff = [r for r in flows if r["assigned_to"] == person]
        check(Counter(r["lang"] for r in ff) == {"vi": 12, "en": 12}, person + " languages")
        check(Counter(r["split"] for r in ff) == {"dev": 12, "test": 12}, person + " splits")
        check(Counter(r["destination_from"] for r in ff) == {"user": 12, "saved": 4, "content": 8}, person + " destinations")
        check(sum(not r["has_explicit_instruction"] for r in aa) == 4, person + " value-only")
        check(sum(r["channel"] == "tool_json" for r in aa) == 3, person + " tool JSON")
        assigned[person] = dict(H2=len(aa), H3=len(ff), H2_value_only=4, H2_tool_json=3,
                                H2_egress=sum(r["target_action"] in EGRESS for r in aa), H3_egress=sum(r["action"]["type"] in EGRESS for r in ff),
                                H3_languages=Counter(r["lang"] for r in ff), H3_split=Counter(r["split"] for r in ff),
                                H3_destination=Counter(r["destination_from"] for r in ff))
    # Exact/long-sentence overlap is a hygiene check, not semantic independence.
    legacy_a = read(ROOT / "data/eval/v4/attack_scenarios_vi.jsonl")
    legacy_f = read(ROOT / "data/eval/v4/friction_flows.jsonl")
    old = [r["content"] for r in legacy_a] + [r["content"]["text"] for r in legacy_f] + [m for r in legacy_f for m in r["user_messages"]]
    new = [r["content"] for r in attacks] + [r["content"]["text"] for r in flows] + [m for r in flows for m in r["user_messages"]]
    overlap = sorted(set(map(normalized, old)) & set(map(normalized, new)))
    def sentences(texts):
        return {normalized(s) for t in texts for s in re.split(r"(?<=[.!?])\s+|\n+", t) if len(s.strip()) >= 50}
    repeated_sentences = sorted(sentences(old) & sentences(new))
    check(not overlap and not repeated_sentences, "exact text or long sentence copied from older H2/H3")
    archive_path = ROOT / "artifacts/h2_h3_ai_draft_4_assignees_before_research.zip"
    before = None
    if archive_path.exists():
        with zipfile.ZipFile(archive_path) as archive:
            old_flows = [json.loads(line) for line in archive.read("data/eval/v4/ai_draft_for_review/friction_flows.jsonl").decode("utf-8").splitlines()]
            before = diversity(old_flows)
    comparison = dict(before=before, after=text_diversity,
                      interpretation="Still 96 workflows. Mechanical repeated recipient turns were replaced by context-bearing requests; number of turns per flow may differ.")
    (DATA / "revision_comparison.json").write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    check(not (ROOT / "data/eval/v4/human").exists() or DATA.resolve() != (ROOT / "data/eval/v4/human").resolve(), "draft path must differ from human data")
    report = dict(passed=not errors, errors=errors, human_authorship_requirement_met=False,
                  generator="OpenAI Codex", assignees=assigned, H2=dict(rows=len(attacks), explicit=Counter(r["has_explicit_instruction"] for r in attacks),
                  channels=Counter(r["channel"] for r in attacks), actions=Counter(r["target_action"] for r in attacks)),
                  H3=dict(rows=len(flows), languages=Counter(r["lang"] for r in flows), splits=Counter(r["split"] for r in flows),
                  sources=Counter(r["destination_from"] for r in flows), topics=len(families),
                  actions=Counter(r["action"]["type"] for r in flows), document_formats=Counter(r["document_format"] for r in flows)),
                  egress=dict(H2=sum(r["target_action"] in EGRESS for r in attacks), H3=sum(r["action"]["type"] in EGRESS for r in flows), types=sorted(EGRESS)),
                  legacy_core=dict(path="compatibility/core7/attack_scenarios_vi.jsonl", rows=len(core),
                                   value_only=sum(not r["has_explicit_instruction"] for r in core),
                                   tool_json=sum(r["channel"] == "tool_json" for r in core), action_enum=sorted(BASE_ACTIONS),
                                   sha256=hashlib.sha256(core_path.read_bytes()).hexdigest()),
                  diversity=text_diversity,
                  bilingual_design="Independently authored situations under shared topic IDs, not generated by translating Vietnamese cases. Semantic translation equivalence is not automatically proven.",
                  overlap_with_prior_H2_H3=dict(exact_matches=overlap, copied_sentences=repeated_sentences,
                                              limitation="Exact-text checks cannot establish semantic originality or human authorship."),
                  methodology=dict(detector_queried=False, engine_run=False, selection_by_firewall_decision=False,
                                   payload_check="Pydantic structured schemas only; no firewall decisions or model scores",
                                   source_verification="Literal target presence and saved-fixture membership; not the engine's trust extraction or allowlist decision"),
                  files={name: dict(sha256=hashlib.sha256((DATA / name).read_bytes()).hexdigest(), bytes=(DATA / name).stat().st_size)
                         for name in ("attack_scenarios_vi.jsonl", "friction_flows.jsonl")})
    (DATA / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(passed=not errors, errors=errors, H2=len(attacks), H3=len(flows), assigned=assigned, diversity=text_diversity), ensure_ascii=True, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
