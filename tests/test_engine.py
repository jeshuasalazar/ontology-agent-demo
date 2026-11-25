"""Metric values are checked against an independent pure-Python computation."""

import csv
from datetime import date, timedelta

import pytest

from ontology_agent_demo.engine import Query, UnknownMetric
from ontology_agent_demo.ontology import ROOT

AS_OF = date(2026, 9, 30)
START = AS_OF - timedelta(days=27)


def rows(name):
    with open(ROOT / "data" / f"{name}.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def in_window(r):
    return START <= date.fromisoformat(r["date"]) <= AS_OF


def test_units_sold_matches_python(engine):
    expected = sum(int(r["units"]) for r in rows("sales") if in_window(r))
    assert engine.run(Query(metric="units_sold")).rows[0].value == expected


def test_days_of_inventory_matches_python(engine):
    store, sku = "GDL-CEN", "MS-12K-INV"
    sold = sum(int(r["units"]) for r in rows("sales") if in_window(r) and r["store_id"] == store and r["sku"] == sku)
    on_hand = next(
        int(r["on_hand"])
        for r in rows("inventory")
        if r["date"] == AS_OF.isoformat() and r["store_id"] == store and r["sku"] == sku
    )
    got = engine.run(Query(metric="days_of_inventory", filters={"store_id": store, "sku": sku})).rows[0].value
    assert got == round(on_hand / (sold / 28), 1)


def test_gross_margin_matches_python(engine):
    cost = {r["sku"]: float(r["unit_cost"]) for r in rows("products")}
    sales = [r for r in rows("sales") if in_window(r)]
    rev = sum(int(r["units"]) * float(r["unit_price"]) for r in sales)
    cogs = sum(int(r["units"]) * cost[r["sku"]] for r in sales)
    assert engine.run(Query(metric="gross_margin_pct")).rows[0].value == round(100 * (rev - cogs) / rev, 2)


def test_unknown_metric_is_rejected_not_guessed(engine):
    with pytest.raises(UnknownMetric):
        engine.run(Query(metric="customer_happiness"))


def test_audit_record_proves_what_ran(engine):
    a = engine.run(Query(metric="revenue", group_by=["region"])).audit
    assert a["ontology_version"] == "1.0.0"
    assert a["metric_fingerprint"] == engine.ontology.metrics["revenue"].fingerprint
    assert a["llm_tokens"] == 0 and len(a["result_hash"]) == 16
