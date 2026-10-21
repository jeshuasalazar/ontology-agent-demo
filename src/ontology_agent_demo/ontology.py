"""Load and validate the business ontology (the single source of metric definitions)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ONTOLOGY = ROOT / "ontology" / "retail.yaml"


class Metric(BaseModel):
    label: str
    unit: str
    description: str
    sql: str
    params: dict[str, int] = Field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        """Hash of the exact definition, so an audit record proves which formula ran."""
        return hashlib.sha256(self.sql.encode()).hexdigest()[:16]


class Rule(BaseModel):
    description: str
    metric: str
    grain: list[str]
    safety_stock_days: int
    lead_time_source: str


class Ontology(BaseModel):
    version: str
    domain: str
    entities: dict[str, dict]
    facts: dict[str, dict]
    dimensions: list[str]
    metrics: dict[str, Metric]
    rules: dict[str, Rule] = Field(default_factory=dict)

    @property
    def tables(self) -> list[str]:
        return [e["table"] for e in self.entities.values()] + [f["table"] for f in self.facts.values()]


def load_ontology(path: Path = DEFAULT_ONTOLOGY) -> Ontology:
    return Ontology.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
