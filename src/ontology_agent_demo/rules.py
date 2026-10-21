"""Business rules on top of ontology metrics: deterministic decisions with evidence."""

from __future__ import annotations

from pydantic import BaseModel

from .engine import Engine, Query
from .retrieval import LeadTime, extract_lead_time


class ReorderDecision(BaseModel):
    store_id: str
    sku: str
    days_of_inventory: float | None
    lead_time: LeadTime | None
    threshold_days: int | None
    reorder: bool
    reason: str


def reorder_report(engine: Engine, retriever, as_of=None) -> list[ReorderDecision]:
    rule = engine.ontology.rules["reorder_needed"]
    doi = engine.run(Query(metric=rule.metric, group_by=rule.grain, as_of=as_of))
    suppliers = dict(engine.backend.run(f"SELECT sku, supplier_id FROM {engine.backend.table('products')}", {}))
    cache: dict[str, LeadTime | None] = {}
    out = []
    for row in doi.rows:
        sku, store = row.dims["sku"], row.dims["store_id"]
        sup = suppliers[sku]
        if sup not in cache:
            cache[sup] = extract_lead_time(sup, retriever)
        lt = cache[sup]
        if lt is None:
            out.append(ReorderDecision(store_id=store, sku=sku, days_of_inventory=row.value, lead_time=None,
                                       threshold_days=None, reorder=False, reason="no lead-time evidence: escalate to a human"))
            continue
        threshold = lt.days + rule.safety_stock_days
        if row.value is None:
            reorder, reason = False, "no sales in window: coverage undefined"
        else:
            reorder = row.value < threshold
            reason = f"{row.value} days < {lt.days} lead time + {rule.safety_stock_days} safety" if reorder else "covered"
        out.append(ReorderDecision(store_id=store, sku=sku, days_of_inventory=row.value, lead_time=lt,
                                   threshold_days=threshold, reorder=reorder, reason=reason))
    return out
