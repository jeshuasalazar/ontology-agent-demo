from ontology_agent_demo.retrieval import extract_lead_time
from ontology_agent_demo.rules import reorder_report


def test_lead_times_come_from_supplier_emails_with_citation(retriever):
    fn = extract_lead_time("SUP-FN", retriever)
    assert (fn.days, fn.source) == (21, "2026-09-02_frio-norte.md")  # the new value, not the old 14
    assert extract_lead_time("SUP-CA", retriever).days == 10
    assert extract_lead_time("SUP-BR", retriever).days == 30  # "30 días en lugar de los 18"


def test_reorder_rule_uses_lead_time_plus_safety_stock(engine, retriever):
    report = reorder_report(engine, retriever)
    for d in report:
        if d.days_of_inventory is not None and d.threshold_days is not None:
            assert d.reorder == (d.days_of_inventory < d.lead_time.days + 7)
    assert any(d.reorder for d in report)
