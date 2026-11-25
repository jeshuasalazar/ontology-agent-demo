"""Planner accuracy on the golden set, plus the token bill of each architecture.

ontology-first: tokens actually spent (0 with the deterministic planner).
llm-only (estimated): tokens needed just to put the question's raw data in a
prompt, at ~4 characters per token. That is a floor: it excludes instructions,
reasoning and output, and it is paid again on every question.
"""

import csv
import io
import time
from pathlib import Path

import yaml

from ontology_agent_demo.agent import ask, build_agent
from ontology_agent_demo.engine import DuckDBBackend, Engine
from ontology_agent_demo.ontology import load_ontology
from ontology_agent_demo.payables import INVOICES, reconcile

HERE = Path(__file__).parent


def raw_window_tokens(engine, q) -> int:
    _sql, params = engine.compile(q)
    rows = engine.backend.run(
        "SELECT * FROM sales WHERE date BETWEEN $start_date AND $as_of",
        {"start_date": params["start_date"], "as_of": params["as_of"]},
    ) + engine.backend.run("SELECT * FROM inventory WHERE date = $as_of", {"as_of": params["as_of"]})
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return len(buf.getvalue()) // 4


def main() -> None:
    engine = Engine(load_ontology(), DuckDBBackend())
    agent = build_agent(engine, use_llm=False)
    cases = yaml.safe_load((HERE / "questions.yaml").read_text(encoding="utf-8"))
    ok, spent, floor, ms = 0, 0, 0, []
    print(f"{'question':58} {'ok':>3} {'tokens':>6} {'llm-only est.':>13} {'ms':>6}")
    for c in cases:
        t0 = time.perf_counter()
        s = ask(agent, c["q"])
        ms.append(1000 * (time.perf_counter() - t0))
        q, e = s["plan"].query, c["expect"]
        hit = q is not None and (q.metric, sorted(q.group_by), q.filters) == (
            e["metric"],
            sorted(e["group_by"]),
            e["filters"],
        )
        est = raw_window_tokens(engine, q) if q else 0
        ok, spent, floor = ok + hit, spent + s["llm_tokens"], floor + est
        print(f"{c['q'][:58]:58} {'✓' if hit else '✗':>3} {s['llm_tokens']:>6} {est:>13,} {ms[-1]:>6.1f}")
    t0 = time.perf_counter()
    run = reconcile(__import__("datetime").date(2026, 10, 13))
    ap_ms = 1000 * (time.perf_counter() - t0)
    xml_tokens = sum(len(p.read_text(encoding="utf-8")) for p in INVOICES.glob("*.xml")) // 4
    print(f"\nPlanner accuracy: {ok}/{len(cases)}")
    print(f"Tokens spent, ontology-first: {spent}  |  llm-only floor (estimated): {floor:,}")
    print(f"Median latency: {sorted(ms)[len(ms) // 2]:.1f} ms per question")
    print(
        f"Invoice run: {len(run.decisions)} CFDI, ${run.scheduled_total} scheduled, 0 tokens, {ap_ms:.1f} ms "
        f"(an LLM reading the same XML needs >= {xml_tokens:,} input tokens per run)"
    )


if __name__ == "__main__":
    main()
