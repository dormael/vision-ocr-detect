"""Tests for config loading and validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vision_ocr_detect.config import (
    ProviderConfig,
    Settings,
    find_config_path,
    load_settings,
)


def test_settings_defaults_when_minimal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"providers": {"p": {"type": "ollama", "base_url": "x"}}}))
    monkeypatch.setenv("VISION_OCR_CONFIG", str(cfg))
    s = load_settings()
    assert s.server.host == "0.0.0.0"
    assert s.server.port == 8000
    assert s.server.max_concurrent_requests == 4
    assert "p" in s.providers


def test_settings_rejects_empty_providers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"providers": {}}))
    monkeypatch.setenv("VISION_OCR_CONFIG", str(cfg))
    with pytest.raises(ValueError, match="at least one provider"):
        load_settings()


def test_settings_rejects_unsupported_provider_type(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"providers": {"p": {"type": "openai", "base_url": "x"}}}))
    monkeypatch.setenv("VISION_OCR_CONFIG", str(cfg))
    with pytest.raises(ValueError):
        load_settings()


def test_settings_rejects_zero_port(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "server": {"port": 0},
        "providers": {"p": {"type": "ollama", "base_url": "x"}},
    }))
    monkeypatch.setenv("VISION_OCR_CONFIG", str(cfg))
    with pytest.raises(ValueError):
        load_settings()


def test_load_settings_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VISION_OCR_CONFIG", str(tmp_path / "nope.json"))
    with pytest.raises(FileNotFoundError):
        load_settings()


def test_find_config_path_prefers_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VISION_OCR_CONFIG", "/tmp/x.json")
    assert str(find_config_path()).endswith("x.json")
