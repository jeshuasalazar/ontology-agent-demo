"""The rules reproduce the decisions of the LLM invoice agent, with zero tokens."""

from datetime import date
from decimal import Decimal

from ontology_agent_demo.payables import reconcile


def test_same_decisions_as_the_llm_agent():
    run = reconcile(date(2026, 10, 13))
    status = {d.invoice.file[:2]: d.status for d in run.decisions}
    assert status == {"01": "pay", "02": "pay", "03": "pay", "04": "clarify", "05": "clarify", "06": "reject"}
    assert run.scheduled_total == Decimal("32190.00") and run.remaining == Decimal("7810.00")
    assert run.llm_tokens == 0


def test_each_decision_cites_the_failed_check():
    by = {d.invoice.file[:2]: d for d in reconcile(date(2026, 10, 13)).decisions}
    assert by["04"].failed_checks == ["totals_add_up"] and "diff 127.00" in by["04"].detail
    assert by["05"].failed_checks == ["receiver_rfc"]
    assert by["06"].failed_checks == ["unique_uuid"]
