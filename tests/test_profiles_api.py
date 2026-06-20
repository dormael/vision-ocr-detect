"""End-to-end tests for /api/profiles via TestClient + in-memory lifespan."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_list_empty(client_with_fake):
    client, _ = client_with_fake
    assert client.get("/api/profiles").json() == []


def test_create_get_update_delete_cycle(client_with_fake):
    client, _ = client_with_fake
    body = {
        "name": "ocr",
        "provider": "local-ollama",
        "model": "glm-ocr:latest",
        "prompt": "Extract text.",
    }
    r = client.post("/api/profiles", json=body)
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "ocr"

    r = client.get("/api/profiles/ocr")
    assert r.status_code == 200
    assert r.json()["prompt"] == "Extract text."

    r = client.put("/api/profiles/ocr", json={"prompt": "new"})
    assert r.status_code == 200
    assert r.json()["prompt"] == "new"
    # created_at preserved
    assert r.json()["created_at"] == client.get("/api/profiles/ocr").json()["created_at"]

    r = client.delete("/api/profiles/ocr")
    assert r.status_code == 204

    r = client.get("/api/profiles/ocr")
    assert r.status_code == 404


def test_create_duplicate_returns_409(client_with_fake):
    client, _ = client_with_fake
    body = {"name": "x", "provider": "local-ollama", "model": "m", "prompt": "p"}
    assert client.post("/api/profiles", json=body).status_code == 201
    assert client.post("/api/profiles", json=body).status_code == 409


def test_create_unknown_provider_returns_400(client_with_fake):
    client, _ = client_with_fake
    body = {"name": "x", "provider": "ghost", "model": "m", "prompt": "p"}
    r = client.post("/api/profiles", json=body)
    assert r.status_code == 400
    assert "unknown provider" in r.json()["detail"]


def test_name_pattern_enforced(client_with_fake):
    client, _ = client_with_fake
    body = {"name": "has space", "provider": "local-ollama", "model": "m", "prompt": "p"}
    assert client.post("/api/profiles", json=body).status_code == 422


def test_update_unknown_returns_404(client_with_fake):
    client, _ = client_with_fake
    assert client.put("/api/profiles/ghost", json={"prompt": "x"}).status_code == 404
