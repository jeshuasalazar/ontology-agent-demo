"""Neural layer: turn a natural-language question into a structured Query.

The deterministic planner matches the question against the ontology's own
vocabulary and costs zero tokens. The optional LLM planner (Claude) handles
phrasings the vocabulary misses; its output goes through the same validation,
so the LLM can choose what to compute but never what the numbers are.
"""

from __future__ import annotations

import os
import re
import unicodedata
from datetime import date

from pydantic import BaseModel

from .engine import Query

METRIC_WORDS = {
    "days_of_inventory": ["dias de inventario", "days of inventory", "cobertura", "coverage", "doi"],
    "sell_through_pct": ["sell-through", "sell through", "sellthrough", "desplazamiento"],
    "gross_margin_pct": ["margen", "margin"],
    "revenue": ["ventas en pesos", "revenue", "ingresos", "facturacion"],
    "units_sold": ["unidades", "units", "piezas", "cuantos vendimos", "ventas"],
}
GROUP_WORDS = {
    "region": ["por region", "by region"],
    "store_id": ["por tienda", "by store"],
    "sku": ["por producto", "por sku", "by product", "by sku"],
    "category": ["por categoria", "by category"],
}
VALUES = {
    "region": {"norte": "norte", "centro": "centro", "occidente": "occidente"},
    "store_id": {
        "monterrey": "MTY-VAL",
        "valle oriente": "MTY-VAL",
        "polanco": "CDMX-POL",
        "ciudad de mexico": "CDMX-POL",
        "guadalajara": "GDL-CEN",
    },
    "category": {
        "minisplit": "minisplit",
        "portatil": "portable",
        "portable": "portable",
        "ventana": "window",
        "window": "window",
        "ventilador": "fan",
        "fan": "fan",
    },
}
SKU = re.compile(r"\b(MS-\d+K-(?:INV|STD)|PT-\d+K|WN-\d+K|FAN-TWR)\b", re.I)
DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")
WINDOW = re.compile(r"(\d+)\s*(?:dias|days)\b")


class Plan(BaseModel):
    query: Query | None
    planner: str
    llm_tokens: int = 0
    note: str = ""


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def deterministic_plan(question: str) -> Plan:
    q = _norm(question)
    metric = next((m for m, words in METRIC_WORDS.items() if any(w in q for w in words)), None)
    if metric is None:
        return Plan(query=None, planner="deterministic", note="no ontology metric matches the question")
    group_by = [d for d, words in GROUP_WORDS.items() if any(w in q for w in words)]
    filters = {}
    for dim, vocab in VALUES.items():
        if dim in group_by:
            continue
        for word, value in vocab.items():
            if re.search(rf"\b{word}(?:es|s)?\b", q):
                filters[dim] = value
                break
    if m := SKU.search(question):
        filters["sku"] = m.group(1).upper()
    as_of = date.fromisoformat(m.group(1)) if (m := DATE.search(q)) else None
    window = int(m.group(1)) if (m := WINDOW.search(q.replace(as_of.isoformat() if as_of else "\0", ""))) else None
    return Plan(
        query=Query(metric=metric, group_by=group_by, filters=filters, as_of=as_of, window_days=window),
        planner="deterministic",
    )


def llm_plan(question: str, ontology) -> Plan:
    """Claude picks metric and filters from the ontology; it never sees or produces values."""
    from langchain_anthropic import ChatAnthropic  # optional dependency

    model = ChatAnthropic(model=os.getenv("ONTOLOGY_LLM_MODEL", "claude-haiku-5-5"), temperature=0, max_tokens=300)
    structured = model.with_structured_output(Query, include_raw=True)
    catalog = "\n".join(f"- {k}: {m.description}" for k, m in ontology.metrics.items())
    prompt = (
        f"Map the question to one metric from this ontology. Dimensions: {ontology.dimensions}. "
        f"Store ids: CDMX-POL, GDL-CEN, MTY-VAL. Regions: norte, centro, occidente.\n{catalog}\n\nQuestion: {question}"
    )
    out = structured.invoke(prompt)
    usage = getattr(out["raw"], "usage_metadata", None) or {}
    return Plan(query=out["parsed"], planner="llm", llm_tokens=usage.get("total_tokens", 0))
