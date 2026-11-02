"""The in-process local provider (WP8): lazy load, and a load failure is a provider error, not a crash."""
import pytest

from firewall.llm_provider import LLMError, LocalHFProvider, get_provider


def test_local_provider_is_lazy_and_fails_as_a_provider_error(monkeypatch):
    provider = get_provider("local", model="nonexistent-org/no-such-model")
    assert isinstance(provider, LocalHFProvider) and provider._model is None     # nothing loaded until the first call
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    with pytest.raises(LLMError, match="could not load"):
        provider.complete("hello", max_tokens=5, temperature=0.0)


def test_unknown_provider_lists_local():
    with pytest.raises(LLMError, match="local"):
        get_provider("no-such-provider")
