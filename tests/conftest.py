"""Keep test runs from writing into the project's data/ folder."""
import os
import tempfile

os.environ.setdefault("FIREWALL_REVIEW_QUEUE", os.path.join(tempfile.mkdtemp(prefix="fw_review_"), "review_queue.json"))

os.environ.setdefault("FIREWALL_FEEDBACK_FILE", os.path.join(tempfile.mkdtemp(prefix="fw_feedback_"), "feedback.jsonl"))

# Tests never call an external judge (it would spend quota and make runs depend on the network).
os.environ["FIREWALL_JUDGE_PROVIDER"] = "none"
