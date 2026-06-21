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


# ----------------------------------------------------------------------
# tags + description (#8 profile metadata)
# ----------------------------------------------------------------------


def test_create_profile_with_tags_and_description(client_with_fake):
    client, _ = client_with_fake
    body = {
        "name": "ocr-layout",
        "provider": "local-ollama",
        "model": "qwen2.5vl:7b",
        "prompt": "Extract layout.",
        "description": "Concert-hall seat layout parser",
        "tags": ["layout", "seat-map", "venue"],
    }
    r = client.post("/api/profiles", json=body)
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["description"] == "Concert-hall seat layout parser"
    assert p["tags"] == ["layout", "seat-map", "venue"]


def test_create_profile_default_tags_empty(client_with_fake):
    """No tags → empty list (not null, not missing)."""
    client, _ = client_with_fake
    body = {
        "name": "plain",
        "provider": "local-ollama",
        "model": "m",
        "prompt": "p",
    }
    r = client.post("/api/profiles", json=body)
    assert r.status_code == 201, r.text
    assert r.json()["tags"] == []
    assert r.json()["description"] is None


def test_create_profile_normalizes_tags(client_with_fake):
    """Tags are lowercased, stripped, and deduplicated."""
    client, _ = client_with_fake
    body = {
        "name": "x",
        "provider": "local-ollama",
        "model": "m",
        "prompt": "p",
        "tags": ["  Layout ", "layout", "VENUE", "venue", "venue"],
    }
    r = client.post("/api/profiles", json=body)
    assert r.status_code == 201, r.text
    assert r.json()["tags"] == ["layout", "venue"]


def test_create_profile_rejects_invalid_tag(client_with_fake):
    client, _ = client_with_fake
    body = {
        "name": "x",
        "provider": "local-ollama",
        "model": "m",
        "prompt": "p",
        "tags": ["has space", "ok-tag"],
    }
    r = client.post("/api/profiles", json=body)
    assert r.status_code == 422
    assert "tag" in r.text.lower()


def test_list_profiles_filter_by_tag(client_with_fake):
    client, _ = client_with_fake
    for n, tags in [
        ("layout-1", ["layout", "venue"]),
        ("layout-2", ["layout"]),
        ("ocr-1", ["ocr"]),
    ]:
        r = client.post("/api/profiles", json={
            "name": n, "provider": "local-ollama", "model": "m",
            "prompt": "p", "tags": tags,
        })
        assert r.status_code == 201, r.text

    r = client.get("/api/profiles?tag=layout")
    assert r.status_code == 200
    names = sorted(p["name"] for p in r.json())
    assert names == ["layout-1", "layout-2"]

    r = client.get("/api/profiles?tag=venue")
    assert r.status_code == 200
    assert [p["name"] for p in r.json()] == ["layout-1"]

    # No tag → all profiles
    r = client.get("/api/profiles")
    assert sorted(p["name"] for p in r.json()) == ["layout-1", "layout-2", "ocr-1"]


def test_list_profiles_filter_tag_is_case_insensitive(client_with_fake):
    client, _ = client_with_fake
    client.post("/api/profiles", json={
        "name": "x", "provider": "local-ollama", "model": "m",
        "prompt": "p", "tags": ["Layout"],
    })
    r = client.get("/api/profiles?tag=LAYOUT")
    assert r.status_code == 200
    assert [p["name"] for p in r.json()] == ["x"]


def test_update_profile_sets_tags_and_description(client_with_fake):
    client, _ = client_with_fake
    client.post("/api/profiles", json={
        "name": "x", "provider": "local-ollama", "model": "m", "prompt": "p",
    })
    r = client.put("/api/profiles/x", json={
        "tags": ["new-tag"],
        "description": "now documented",
    })
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["tags"] == ["new-tag"]
    assert p["description"] == "now documented"


def test_update_profile_clears_description_with_null(client_with_fake):
    """PUT description=null explicitly clears it (vs. omitting the field)."""
    client, _ = client_with_fake
    client.post("/api/profiles", json={
        "name": "x", "provider": "local-ollama", "model": "m", "prompt": "p",
        "description": "first",
    })
    r = client.put("/api/profiles/x", json={"description": None})
    assert r.status_code == 200
    assert r.json()["description"] is None


def test_update_profile_leaves_metadata_untouched_when_omitted(client_with_fake):
    client, _ = client_with_fake
    client.post("/api/profiles", json={
        "name": "x", "provider": "local-ollama", "model": "m", "prompt": "p",
        "description": "kept",
        "tags": ["a"],
    })
    r = client.put("/api/profiles/x", json={"prompt": "new"})
    assert r.status_code == 200
    p = r.json()
    assert p["prompt"] == "new"
    assert p["description"] == "kept"
    assert p["tags"] == ["a"]


def test_backward_compatible_legacy_profile_json(tmp_path, monkeypatch):
    """Profiles written without tags/description (legacy) load with defaults."""
    import json

    from vision_ocr_detect.config import ProviderConfig, ServerConfig, Settings
    from vision_ocr_detect import deps as deps_mod
    from vision_ocr_detect import main as main_mod
    from vision_ocr_detect.providers.registry import ProviderRegistry
    from fastapi.testclient import TestClient

    profiles = tmp_path / "profiles.json"
    # Legacy entry: no tags, no description.
    profiles.write_text(json.dumps({
        "legacy": {
            "name": "legacy",
            "provider": "local-ollama",
            "model": "m",
            "prompt": "p",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
    }), encoding="utf-8")

    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "server": {"host": "127.0.0.1", "port": 8765, "max_concurrent_requests": 2},
        "providers": {"local-ollama": {"type": "ollama", "base_url": "http://localhost:11434", "timeout_seconds": 30}},
    }), encoding="utf-8")

    monkeypatch.setenv("VISION_OCR_CONFIG", str(config))
    monkeypatch.setenv("VISION_OCR_PROFILES", str(profiles))

    settings = Settings.model_validate(json.loads(config.read_text()))
    registry = ProviderRegistry()
    registry.register("local-ollama", __import__(
        "vision_ocr_detect.providers.ollama", fromlist=["OllamaProvider"]
    ).OllamaProvider("local-ollama", ProviderConfig(
        type="ollama", base_url="http://localhost:11434", timeout_seconds=30
    )))
    app = main_mod.create_app(settings=settings)
    app.dependency_overrides[deps_mod.get_provider_registry] = lambda: registry

    with TestClient(app) as client:
        r = client.get("/api/profiles/legacy")
        assert r.status_code == 200, r.text
        p = r.json()
        assert p["tags"] == []
        assert p["description"] is None
