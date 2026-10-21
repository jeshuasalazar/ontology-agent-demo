"""Symbolic engine: compiles ontology metrics to SQL and runs them deterministically.

No LLM is involved here. The same metric, filters and date over the same data
always return the same value, and every result carries an audit record.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Protocol

import duckdb
from pydantic import BaseModel

from .ontology import ROOT, Ontology

DATA_DIR = ROOT / "data"

# Where each dimension lives in the metric SQL (p = products, st = stores).
DIMENSION_COLUMNS = {"store_id": "st.store_id", "sku": "p.sku", "category": "p.category", "region": "st.region"}


class Query(BaseModel):
    """A fully structured request. The neural layer's only job is to produce one."""

    metric: str
    group_by: list[str] = []
    filters: dict[str, str] = {}
    as_of: date | None = None
    window_days: int | None = None


class Row(BaseModel):
    dims: dict[str, str]
    value: float | None


class Result(BaseModel):
    query: Query
    rows: list[Row]
    audit: dict[str, Any]


class Backend(Protocol):
    name: str

    def run(self, sql: str, params: dict[str, Any]) -> list[tuple]: ...
    def table(self, name: str) -> str: ...
    def max_date(self) -> date: ...
    def fingerprint(self) -> str: ...


class DuckDBBackend:
    """Local backend over the CSV files in data/ (same SQL that runs on BigQuery)."""

    name = "duckdb"

    def __init__(self, data_dir: Path = DATA_DIR, tables: list[str] | None = None):
        self.data_dir = data_dir
        self.con = duckdb.connect()
        for t in tables or ["products", "stores", "suppliers", "sales", "inventory"]:
            self.con.execute(f"CREATE VIEW {t} AS SELECT * FROM read_csv_auto('{data_dir / (t + '.csv')}')")

    def run(self, sql: str, params: dict[str, Any]) -> list[tuple]:
        sql = re.sub(r":(\w+)", r"$\1", sql)
        return self.con.execute(sql, params).fetchall()

    def table(self, name: str) -> str:
        return name

    def max_date(self) -> date:
        return self.con.execute("SELECT MAX(date) FROM sales").fetchone()[0]

    def fingerprint(self) -> str:
        if not hasattr(self, "_fp"):  # the CSVs are read-only for the life of the process
            h = hashlib.sha256()
            for f in sorted(self.data_dir.glob("*.csv")):
                h.update(f.read_bytes())
            self._fp = h.hexdigest()[:16]
        return self._fp


class BigQueryBackend:
    """Same compiled SQL on BigQuery. Set GCP project and dataset to use it."""

    name = "bigquery"

    def __init__(self, project: str, dataset: str):
        from google.cloud import bigquery  # optional dependency

        self.bq, self.client = bigquery, bigquery.Client(project=project)
        self.prefix = f"`{project}.{dataset}"

    def run(self, sql: str, params: dict[str, Any]) -> list[tuple]:
        sql = re.sub(r":(\w+)", r"@\1", sql)
        qp = [self.bq.ScalarQueryParameter(k, _bq_type(v), v) for k, v in params.items()]
        job = self.client.query(sql, job_config=self.bq.QueryJobConfig(query_parameters=qp))
        return [tuple(r.values()) for r in job.result()]

    def table(self, name: str) -> str:
        return f"{self.prefix}.{name}`"

    def max_date(self) -> date:
        return self.run(f"SELECT MAX(date) FROM {self.table('sales')}", {})[0][0]

    def fingerprint(self) -> str:
        rows = self.run(f"SELECT COUNT(*), SUM(units) FROM {self.table('sales')}", {})
        return hashlib.sha256(repr(rows).encode()).hexdigest()[:16]


def _bq_type(v: Any) -> str:
    return "DATE" if isinstance(v, date) else "INT64" if isinstance(v, int) else "STRING"


class UnknownMetric(ValueError):
    pass


class Engine:
    def __init__(self, ontology: Ontology, backend: Backend):
        self.ontology, self.backend = ontology, backend

    def validate(self, q: Query) -> list[str]:
        """Reject anything the ontology does not define, instead of guessing."""
        errors = []
        if q.metric not in self.ontology.metrics:
            errors.append(f"unknown metric '{q.metric}'")
        for d in [*q.group_by, *q.filters]:
            if d not in DIMENSION_COLUMNS:
                errors.append(f"unknown dimension '{d}'")
        return errors

    def compile(self, q: Query) -> tuple[str, dict[str, Any]]:
        if errors := self.validate(q):
            raise UnknownMetric("; ".join(errors))
        metric = self.ontology.metrics[q.metric]
        as_of = q.as_of or self.backend.max_date()
        window = q.window_days or metric.params.get("window_days", 28)
        params: dict[str, Any] = {"as_of": as_of, "start_date": as_of - timedelta(days=window - 1)}
        if ":window_days" in metric.sql:
            params["window_days"] = window
        cols = [DIMENSION_COLUMNS[d] for d in q.group_by] or ["'total'"]
        filters = ""
        for i, (dim, value) in enumerate(sorted(q.filters.items())):
            filters += f" AND {DIMENSION_COLUMNS[dim]} = :f{i}"
            params[f"f{i}"] = value
        tables = {t: self.backend.table(t) for t in self.ontology.tables}
        sql = metric.sql.format(
            group_cols=", ".join(cols),
            group_by=", ".join(str(i + 1) for i in range(len(cols))),
            filters=filters,
            **tables,
        )
        return sql, params

    def run(self, q: Query) -> Result:
        sql, params = self.compile(q)
        raw = sorted(self.backend.run(sql, params), key=lambda r: tuple(str(x) for x in r[:-1]))
        dims = q.group_by or ["scope"]
        rows = [Row(dims=dict(zip(dims, map(str, r[:-1]))), value=_num(r[-1])) for r in raw]
        metric = self.ontology.metrics[q.metric]
        audit = {
            "ontology_version": self.ontology.version,
            "metric": q.metric,
            "metric_fingerprint": metric.fingerprint,
            "backend": self.backend.name,
            "data_fingerprint": self.backend.fingerprint(),
            "params": {k: str(v) for k, v in params.items()},
            "sql": sql,
            "llm_tokens": 0,
        }
        audit["result_hash"] = _hash([r.model_dump() for r in rows])
        return Result(query=q.model_copy(update={"as_of": params["as_of"]}), rows=rows, audit=audit)


def _num(v: Any) -> float | None:
    return None if v is None else float(v)


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]
