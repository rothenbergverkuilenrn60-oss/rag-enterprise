"""
tests/unit/test_rules_engine_abc.py
TDD RED: Rule as ABC with @abstractmethod check() (OPS-02)

Tests verify:
  - Concrete Rule subclass missing check() raises TypeError at instantiation
  - PromptInjectionRule (implements check()) instantiates without error
  - RulesEngine() instantiates without error (all 7 builtin rules implement check())
  - RulesEngine().run("pre_query", {"query": "safe input"}) returns PASS
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")


class TestRuleABC:
    def test_rule_subclass_without_check_raises_type_error(self):
        """Concrete subclass missing check() raises TypeError at instantiation."""
        from services.rules.rules_engine import Rule

        with pytest.raises(TypeError):
            class BrokenRule(Rule):
                pass
            BrokenRule(rule_id="X", description="broken", stage="pre_query")

    def test_prompt_injection_rule_instantiates(self):
        """PromptInjectionRule (implements check()) instantiates without error."""
        from services.rules.rules_engine import PromptInjectionRule

        rule = PromptInjectionRule(
            rule_id="S001", description="Prompt injection detection",
            stage="pre_query", priority=1,
        )
        assert rule.rule_id == "S001"
        assert rule.stage == "pre_query"

    def test_rules_engine_instantiates_with_7_builtin_rules(self):
        """RulesEngine() builds all 7 builtin rules without error."""
        from services.rules.rules_engine import RulesEngine

        engine = RulesEngine()
        assert len(engine._rules) == 7

    def test_rules_engine_run_returns_pass_for_safe_input(self):
        """RulesEngine.run() returns PASS for a normal safe query."""
        from services.rules.rules_engine import RulesEngine, RuleAction

        engine = RulesEngine()
        result = engine.run("pre_query", {"query": "What is the leave policy?"})
        assert result.action == RuleAction.PASS
