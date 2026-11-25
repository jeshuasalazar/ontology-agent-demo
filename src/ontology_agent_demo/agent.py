"""LangGraph workflow: plan -> validate -> compute -> (evidence) -> answer.

Only the optional LLM planner can spend tokens. Computation, rules and the
answer itself are deterministic, so they are reproducible and auditable.
"""

from __future__ import annotations

import os
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from .engine import Engine, Result
from .planner import Plan, deterministic_plan, llm_plan


class State(TypedDict, total=False):
    question: str
    plan: Plan
    errors: list[str]
    result: Result
    answer: str
    llm_tokens: int


def build_agent(engine: Engine, use_llm: bool | None = None):
    use_llm = bool(os.getenv("ANTHROPIC_API_KEY")) if use_llm is None else use_llm

    def plan(state: State) -> State:
        p = deterministic_plan(state["question"])
        if p.query is None and use_llm:  # tokens only for what the vocabulary cannot map
            p = llm_plan(state["question"], engine.ontology)
        return {"plan": p, "llm_tokens": p.llm_tokens}

    def validate(state: State) -> State:
        q = state["plan"].query
        return {"errors": [state["plan"].note or "could not map the question"] if q is None else engine.validate(q)}

    def compute(state: State) -> State:
        return {"result": engine.run(state["plan"].query)}

    def answer(state: State) -> State:
        r = state["result"]
        m = engine.ontology.metrics[r.query.metric]
        parts = [f"{', '.join(row.dims.values())}: {_fmt(row.value, m.unit)}" for row in r.rows]
        scope = f" ({', '.join(f'{k}={v}' for k, v in r.query.filters.items())})" if r.query.filters else ""
        text = (
            f"{m.label}{scope} as of {r.query.as_of}: "
            + "; ".join(parts)
            + f". Definition v{r.audit['ontology_version']}: {m.description.strip()}"
        )
        return {"answer": text}

    def clarify(state: State) -> State:
        known = ", ".join(engine.ontology.metrics)
        return {
            "answer": f"I can't answer that deterministically ({'; '.join(state['errors'])}). Known metrics: {known}."
        }

    g = StateGraph(State)
    for name, fn in [
        ("plan", plan),
        ("validate", validate),
        ("compute", compute),
        ("answer", answer),
        ("clarify", clarify),
    ]:
        g.add_node(name, fn)
    g.set_entry_point("plan")
    g.add_edge("plan", "validate")
    g.add_conditional_edges("validate", lambda s: "clarify" if s["errors"] else "compute")
    g.add_edge("compute", "answer")
    g.add_edge("answer", END)
    g.add_edge("clarify", END)
    return g.compile()


def _fmt(v: float | None, unit: str) -> str:
    if v is None:
        return "undefined (no sales in window)"
    return {"MXN": f"${v:,.2f} MXN", "percent": f"{v:.2f}%", "days": f"{v:.1f} days"}.get(unit, f"{v:,.0f} {unit}")


def ask(agent, question: str) -> dict[str, Any]:
    return agent.invoke({"question": question, "llm_tokens": 0})
