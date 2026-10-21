"""Unstructured data: find supplier evidence and extract lead times, with citations.

LocalRetriever ranks with BM25 in pure Python. ElasticsearchRetriever runs the
same query on Elasticsearch. Extraction is a deterministic pattern, not an LLM,
so the number that feeds a business rule is reproducible and points to its source.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

from pydantic import BaseModel

from .ontology import ROOT

DOCS_DIR = ROOT / "docs" / "suppliers"
SUPPLIER_ALIASES = {"SUP-FN": "frio norte", "SUP-CA": "clima andino", "SUP-BR": "brisa pacifico"}


class Passage(BaseModel):
    source: str
    text: str
    score: float = 0.0


class LeadTime(BaseModel):
    supplier_id: str
    days: int
    source: str
    quote: str


def _tokens(text: str) -> list[str]:
    text = text.lower().translate(str.maketrans("áéíóúñ", "aeioun"))
    return re.findall(r"[a-z0-9]+", text)


class LocalRetriever:
    name = "local-bm25"

    def __init__(self, docs_dir: Path = DOCS_DIR):
        self.docs = [Passage(source=p.name, text=p.read_text(encoding="utf-8")) for p in sorted(docs_dir.glob("*.md"))]
        self.tf = [Counter(_tokens(d.text)) for d in self.docs]
        self.avg = sum(sum(t.values()) for t in self.tf) / max(len(self.tf), 1)

    def search(self, query: str, k: int = 3) -> list[Passage]:
        n, q = len(self.docs), _tokens(query)
        scored = []
        for doc, tf in zip(self.docs, self.tf):
            length, s = sum(tf.values()), 0.0
            for term in q:
                df = sum(1 for t in self.tf if term in t)
                if not df:
                    continue
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                s += idf * tf[term] * 2.2 / (tf[term] + 1.2 * (0.25 + 0.75 * length / self.avg))
            if s > 0:
                scored.append(doc.model_copy(update={"score": round(s, 4)}))
        return sorted(scored, key=lambda p: (-p.score, p.source))[:k]


class ElasticsearchRetriever:
    """Same interface on Elasticsearch (docker compose up provides one on :9200)."""

    name = "elasticsearch"

    def __init__(self, url: str, index: str = "supplier-docs", docs_dir: Path = DOCS_DIR):
        from elasticsearch import Elasticsearch  # optional dependency

        self.es, self.index = Elasticsearch(url), index
        if not self.es.indices.exists(index=index):
            self.es.indices.create(index=index, mappings={"properties": {"text": {"type": "text"}, "source": {"type": "keyword"}}})
            for p in sorted(docs_dir.glob("*.md")):
                self.es.index(index=index, id=p.name, document={"source": p.name, "text": p.read_text(encoding="utf-8")})
            self.es.indices.refresh(index=index)

    def search(self, query: str, k: int = 3) -> list[Passage]:
        hits = self.es.search(index=self.index, query={"match": {"text": query}}, size=k)["hits"]["hits"]
        return [Passage(source=h["_source"]["source"], text=h["_source"]["text"], score=h["_score"]) for h in hits]


_RANGE = re.compile(r"de\s+(\d+)\s+a\s+(\d+)\s+d[ií]as", re.I)
_INSTEAD = re.compile(r"(\d+)\s+d[ií]as\s+en\s+lugar\s+de", re.I)
_PLAIN = re.compile(r"(?:lead time|tiempo de entrega)\s*:?\s*(\d+)\s*(?:days|d[ií]as)", re.I)


def extract_lead_time(supplier_id: str, retriever) -> LeadTime | None:
    """Read the most relevant supplier email and pull the current lead time from it."""
    name = SUPPLIER_ALIASES[supplier_id]
    for p in retriever.search(f"{name} tiempo de entrega lead time dias entregas"):
        if name not in " ".join(_tokens(p.text)):
            continue
        for pattern, group in ((_RANGE, 2), (_INSTEAD, 1), (_PLAIN, 1)):
            if m := pattern.search(p.text):
                return LeadTime(supplier_id=supplier_id, days=int(m.group(group)), source=p.source, quote=m.group(0))
    return None
