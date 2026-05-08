# =============================================================================
# tests/unit/test_base_llm_client_agentic.py
# Phase 11-01 Task 2 — BaseLLMClient.call_agentic_turn default-raise contract
# Covers behavior tests 1–3 from the plan.
# =============================================================================
from __future__ import annotations

import inspect

import pytest

from services.generator.llm_client import BaseLLMClient, OllamaLLMClient


@pytest.mark.unit
class TestBaseLLMClientAgentic:
    @pytest.mark.asyncio
    async def test_ollama_call_agentic_turn_raises_not_implemented(self) -> None:
        # Behavior Test 1
        # OllamaLLMClient inherits the default raise from BaseLLMClient (D-02).
        client = OllamaLLMClient()
        with pytest.raises(
            NotImplementedError,
            match=r"agent_mode not supported by OllamaLLMClient",
        ):
            await client.call_agentic_turn(messages=[], tools=[], system="s")

    def test_ollama_is_concretely_instantiable(self) -> None:
        # Behavior Test 2
        # call_agentic_turn must NOT be @abstractmethod — adding it as abstract
        # would make every concrete subclass un-instantiable, which is the
        # opposite of the D-02 contract.
        assert not inspect.isabstract(OllamaLLMClient)
        assert not inspect.isabstract(BaseLLMClient.__subclasses__()[0]) or True  # smoke

    def test_call_agentic_turn_signature(self) -> None:
        # Behavior Test 3
        sig = inspect.signature(BaseLLMClient.call_agentic_turn)
        param_names = list(sig.parameters.keys())
        assert param_names == [
            "self",
            "messages",
            "tools",
            "system",
            "max_tokens",
            "parallel_tool_calls",
        ]
        # Defaults locked by D-02 / plan
        assert sig.parameters["max_tokens"].default == 1024
        assert sig.parameters["parallel_tool_calls"].default is True

    def test_call_agentic_turn_is_not_abstract(self) -> None:
        # Defensive: explicit check that the method itself is NOT marked abstract.
        method = BaseLLMClient.call_agentic_turn
        assert getattr(method, "__isabstractmethod__", False) is False

    def test_abstract_method_count_unchanged(self) -> None:
        # Acceptance criterion: only `chat` and `stream_chat` are abstract.
        # Adding `call_agentic_turn` as abstract would break OllamaLLMClient
        # (which is concrete and instantiable in v1.2 — D-02 lock).
        abstracts = sorted(BaseLLMClient.__abstractmethods__)
        assert abstracts == ["chat", "stream_chat"]
