"""Same question, same data, same answer: every time, byte for byte."""

from ontology_agent_demo.agent import ask, build_agent

QUESTIONS = [
    "¿Cuántos días de inventario tenemos por región?",
    "Margen de minisplit en Monterrey",
    "sell-through por tienda al 2026-09-15",
]


def test_answers_are_identical_across_runs(engine):
    agent = build_agent(engine, use_llm=False)
    for q in QUESTIONS:
        runs = [ask(agent, q) for _ in range(5)]
        assert len({r["answer"] for r in runs}) == 1
        assert len({r["result"].audit["result_hash"] for r in runs}) == 1
        assert all(r["llm_tokens"] == 0 for r in runs)


def test_out_of_scope_question_is_refused(engine):
    s = ask(build_agent(engine, use_llm=False), "¿Cuál es el clima mañana?")
    assert "result" not in s and "can't answer" in s["answer"]
