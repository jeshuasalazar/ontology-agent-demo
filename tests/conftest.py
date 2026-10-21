import pytest

from ontology_agent_demo.engine import DuckDBBackend, Engine
from ontology_agent_demo.ontology import load_ontology
from ontology_agent_demo.retrieval import LocalRetriever


@pytest.fixture(scope="session")
def engine():
    return Engine(load_ontology(), DuckDBBackend())


@pytest.fixture(scope="session")
def retriever():
    return LocalRetriever()
