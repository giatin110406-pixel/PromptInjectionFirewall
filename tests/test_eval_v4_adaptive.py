from types import SimpleNamespace

import pytest

from evaluation.eval_v4_adaptive import search_scenario, summarize, plot_result


class FakeRunner:
    def __init__(self, scores, bypass=(), allowed=None, control="ALLOW"):
        self.scores, self.queries, self.attempts = scores, [], []
        self.bypass, self.allowed, self.control = set(bypass), allowed or {}, control
        self.e = SimpleNamespace(actions=SimpleNamespace(exposure_mode="detection"),
                                 layer2=SimpleNamespace(window_scores=self.score))

    def score(self, text):
        self.queries.append(text)
        return [self.scores[text] / 2, self.scores[text]]

    def sid(self, prefix):
        return prefix

    def act(self, sid, action, payload, mode):
        self.e.actions.exposure_mode = mode
        return {"decision": self.control}

    def attack_once(self, text, scenario):
        self.attempts.append(text)
        return text not in self.bypass, {m: {"decision": "ALLOW" if text in self.allowed.get(m, ()) else "BLOCK"} for m in ("detection", "provenance")}


SCENARIO = dict(id="A-test", content="seed", channel="email", target_action="transfer_money", target_payload={})


def test_score_guided_expansion_charges_every_candidate_and_uses_fresh_runner_attempt():
    graph = {"seed": ["seed", "a", "b"], "a": ["expensive"], "b": ["c"], "c": []}
    runner = FakeRunner(dict(seed=.9, a=.95, b=.1, c=.2, expensive=.99), bypass=["b"], allowed={"detection": ["c"]})
    row = search_scenario(runner, SCENARIO, (1, 3, 4), transform=lambda t, lang: graph[t])
    assert runner.queries == runner.attempts == ["seed", "a", "b", "c"]
    assert row["checkpoints"]["1"]["detector_bypass"] is False
    assert row["checkpoints"]["3"]["detector_bypass"] is True
    assert row["checkpoints"]["3"]["asr_action"]["detection"] is False
    assert row["checkpoints"]["4"]["asr_action"]["detection"] is True
    assert row["checkpoints"]["4"]["asr_action"]["provenance"] is False
    assert row["best_text"] == "b"
    assert runner.e.actions.exposure_mode == "detection"


def test_deduplication_bounds_and_exhaustion_do_not_inflate_query_budget():
    runner = FakeRunner(dict(seed=.5, ok=.4), bypass=["ok"])
    row = search_scenario(runner, SCENARIO, (1, 10, 50), max_chars=5, max_depth=1,
                          transform=lambda t, lang: ["seed", "seed", "", "much too long", "ok", "ok"])
    assert runner.queries == ["seed", "ok"]
    assert row["trials"] == 2 and row["exhausted"]
    assert row["checkpoints"]["50"]["queries"] == 2
    assert row["checkpoints"]["1"]["detector_bypass"] is False
    assert row["checkpoints"]["10"]["detector_bypass"] is True
    assert max(e["depth"] for e in row["history"]) == 1


def test_controls_exclude_intrinsically_held_actions_from_asr_only():
    good = search_scenario(FakeRunner(dict(seed=.1), bypass=["seed"], allowed={"detection": ["seed"]}), SCENARIO, (1,), transform=lambda t, lang: [])
    held = search_scenario(FakeRunner(dict(seed=.1), bypass=["seed"], control="REVIEW"), dict(SCENARIO, id="held"), (1,), transform=lambda t, lang: [])
    result = summarize([good, held], (1,))
    assert result["n"] == 2 and result["executable"] == 1
    assert result["detector_bypass_at"] == {"1": 1}
    assert result["asr_action_at"] == {"detection": {"1": 1}, "provenance": {"1": 0}}
    assert result["excluded_from_asr"][0]["id"] == "held"


@pytest.mark.parametrize("budgets", [(), (0,), (2, 1), (1, 1), (True,)])
def test_rejects_invalid_budgets(budgets):
    with pytest.raises(ValueError):
        search_scenario(FakeRunner(dict(seed=.5)), SCENARIO, budgets)


def test_invalid_scores_abort_without_counting_detector_success():
    runner = FakeRunner(dict(seed=float("nan")))
    with pytest.raises(ValueError, match="window scores"):
        search_scenario(runner, SCENARIO, (1,))
    assert runner.attempts == []
    assert runner.e.actions.exposure_mode == "detection"


def test_zero_executable_denominator_is_null_and_plot_is_exportable(tmp_path):
    row = search_scenario(FakeRunner(dict(seed=.5), control="BLOCK"), SCENARIO, (1,), transform=lambda t, lang: [])
    result = summarize([row], (1,))
    assert result["asr_action_at"]["provenance"]["1"] is None
    output = tmp_path / "adaptive.png"
    plot_result(result, output)
    assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
