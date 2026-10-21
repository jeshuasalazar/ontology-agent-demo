from fastapi.testclient import TestClient

from ontology_agent_demo import api


def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    api.audit.cache_clear()
    api.agent.cache_clear()
    return TestClient(api.app)


def test_ask_then_fetch_and_verify_audit(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    r = c.post("/ask", json={"question": "días de inventario por región"}).json()
    assert r["llm_tokens"] == 0 and r["planner"] == "deterministic"
    rec = c.get(f"/audit/{r['audit_id']}").json()
    assert rec["metric"] == "days_of_inventory" and rec["prev"] == "genesis"
    c.get("/payables/run")
    assert c.get("/audit/verify").json() == {"valid": True, "records": 2}


def test_tampering_breaks_the_chain(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    c.post("/metrics", json={"metric": "revenue"})
    c.post("/metrics", json={"metric": "units_sold"})
    log = tmp_path / "audit.jsonl"
    log.write_text(log.read_text().replace('"revenue"', '"units_sold"', 1))
    assert c.get("/audit/verify").json() == {"valid": False, "broken_at": 1}


def test_unknown_metric_returns_422(tmp_path, monkeypatch):
    assert client(tmp_path, monkeypatch).post("/metrics", json={"metric": "vibes"}).status_code == 422
