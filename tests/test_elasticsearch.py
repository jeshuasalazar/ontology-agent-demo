"""Run with ELASTICSEARCH_URL set (docker-compose up) to check parity with the local retriever."""

import os

import pytest

from ontology_agent_demo.retrieval import extract_lead_time

pytestmark = pytest.mark.skipif(not os.getenv("ELASTICSEARCH_URL"), reason="needs ELASTICSEARCH_URL")


def test_elasticsearch_extracts_the_same_lead_times(retriever):
    from ontology_agent_demo.retrieval import ElasticsearchRetriever

    es = ElasticsearchRetriever(os.environ["ELASTICSEARCH_URL"], index="supplier-docs-test")
    for sup in ["SUP-FN", "SUP-CA", "SUP-BR"]:
        assert extract_lead_time(sup, es) == extract_lead_time(sup, retriever)
