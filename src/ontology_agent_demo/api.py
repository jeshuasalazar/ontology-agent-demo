"""FastAPI service: ask questions, compute metrics, run rules and verify the audit trail."""

from __future__ import annotations

import os
import time
from datetime import date
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .agent import ask, build_agent
from .audit import AuditLog
from .engine import BigQueryBackend, DuckDBBackend, Engine, Query, UnknownMetric
from .ontology import ROOT, load_ontology
from .payables import reconcile
from .retrieval import ElasticsearchRetriever, LocalRetriever
from .rules import reorder_report

app = FastAPI(
    title="Ontology Agent Demo",
    version="0.1.0",
    description="Deterministic, auditable answers over a business ontology, with near-zero LLM tokens.",
)


@lru_cache
def engine() -> Engine:
    if project := os.getenv("BIGQUERY_PROJECT"):
        backend = BigQueryBackend(project, os.getenv("BIGQUERY_DATASET", "ontology_demo"))
    else:
        backend = DuckDBBackend()
    return Engine(load_ontology(), backend)


@lru_cache
def retriever():
    url = os.getenv("ELASTICSEARCH_URL")
    return ElasticsearchRetriever(url) if url else LocalRetriever()


@lru_cache
def agent():
    return build_agent(engine())


@lru_cache
def audit() -> AuditLog:
    return AuditLog(Path(os.getenv("AUDIT_LOG", ROOT / "var" / "audit.jsonl")))


class Ask(BaseModel):
    question: str


@app.get("/health")
def health():
    e = engine()
    return {"status": "ok", "backend": e.backend.name, "retriever": retriever().name, "ontology": e.ontology.version}


@app.get("/ontology")
def ontology():
    o = engine().ontology
    return {
        "version": o.version,
        "dimensions": o.dimensions,
        "metrics": {
            k: {"label": m.label, "unit": m.unit, "description": m.description, "fingerprint": m.fingerprint}
            for k, m in o.metrics.items()
        },
    }


@app.post("/metrics")
def metric(q: Query):
    t0 = time.perf_counter()
    try:
        r = engine().run(q)
    except UnknownMetric as e:
        raise HTTPException(422, str(e)) from e
    audit_id = audit().append({"kind": "metric", **r.audit})
    return {
        "rows": [row.model_dump() for row in r.rows],
        "query": r.query,
        "audit_id": audit_id,
        "llm_tokens": 0,
        "ms": round(1000 * (time.perf_counter() - t0), 1),
    }


@app.post("/ask")
def ask_question(body: Ask):
    t0 = time.perf_counter()
    s = ask(agent(), body.question)
    out = {"answer": s["answer"], "planner": s["plan"].planner, "llm_tokens": s.get("llm_tokens", 0)}
    if r := s.get("result"):
        out["audit_id"] = audit().append(
            {"kind": "ask", "question": body.question, "llm_tokens": out["llm_tokens"], **r.audit}
        )
        out["rows"] = [row.model_dump() for row in r.rows]
    out["ms"] = round(1000 * (time.perf_counter() - t0), 1)
    return out


@app.get("/rules/reorder")
def reorder(as_of: date | None = None):
    decisions = reorder_report(engine(), retriever(), as_of)
    audit_id = audit().append(
        {
            "kind": "rule",
            "rule": "reorder_needed",
            "as_of": str(as_of),
            "reorders": sum(d.reorder for d in decisions),
            "llm_tokens": 0,
        }
    )
    return {"decisions": [d.model_dump() for d in decisions], "audit_id": audit_id, "llm_tokens": 0}


@app.get("/payables/run")
def payables(run_date: date = date(2026, 10, 13)):
    run = reconcile(run_date)
    audit_id = audit().append(
        {"kind": "payables", "run_date": str(run_date), "scheduled_total": str(run.scheduled_total), "llm_tokens": 0}
    )
    return {**run.model_dump(mode="json"), "audit_id": audit_id}


@app.get("/audit/verify")
def verify():
    return audit().verify()


@app.get("/audit/{audit_id}")
def audit_record(audit_id: str):
    if (r := audit().get(audit_id)) is None:
        raise HTTPException(404, "audit record not found")
    return r
