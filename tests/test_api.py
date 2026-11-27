"""API tests. The model pipeline is replaced by a fake, so these run offline."""
import pytest
from fastapi.testclient import TestClient

import main

FAKE_RESULT = {
    "kind": "policy",
    "search_text": "reporting",
    "hits": [({"clause": "8.1", "section": "8. General conditions", "text": "..."}, 0.91)],
    "reply": "You must tell us within 14 days [8.1].",
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "load_index", lambda: ([{"clause": "8.1"}], None))
    monkeypatch.setattr(main, "run_pipeline", lambda q, c, v: FAKE_RESULT)
    monkeypatch.delenv("API_KEY", raising=False)
    with TestClient(main.app) as c:   # "with" runs the start-up code
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "clauses_loaded": 1}


def test_ask_returns_answer_citations_and_disclaimer(client):
    r = client.post("/ask", json={"question": "How long do I have to report an incident?"})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"].endswith("[8.1].")
    assert body["kind"] == "policy"
    assert body["citations"][0]["clause"] == "8.1"
    assert "claims handler" in body["disclaimer"]


def test_too_short_question_is_rejected(client):
    assert client.post("/ask", json={"question": "hi"}).status_code == 422


def test_missing_question_is_rejected(client):
    assert client.post("/ask", json={}).status_code == 422


def test_api_key_required_when_configured(client, monkeypatch):
    monkeypatch.setenv("API_KEY", "secret-key")
    body = {"question": "How long do I have to report an incident?"}
    assert client.post("/ask", json=body).status_code == 401
    assert client.post("/ask", json=body, headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.post("/ask", json=body, headers={"X-API-Key": "secret-key"}).status_code == 200


def test_pipeline_failure_returns_502_without_leaking_details(client, monkeypatch):
    def boom(q, c, v):
        raise RuntimeError("internal endpoint https://secret.example")
    monkeypatch.setattr(main, "run_pipeline", boom)
    r = client.post("/ask", json={"question": "How long do I have to report an incident?"})
    assert r.status_code == 502
    assert "secret" not in r.text
    assert "reference" in r.text
