"""Tests for ProfileStore (CRUD, file lock semantics, atomic writes)."""

from __future__ import annotations
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from vision_ocr_detect.models.profile import Profile, utcnow
from vision_ocr_detect.services.profile_store import (
    ProfileAlreadyExists,
    ProfileNotFound,
    ProfileStore,
)


def _prof(name: str) -> Profile:
    now = utcnow()
    return Profile(
        name=name, provider="local-ollama", model="m", prompt="p",
        created_at=now, updated_at=now,
    )


def test_create_and_get(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path / "p.json")
    store.create(_prof("a"))
    assert store.get("a").name == "a"


def test_duplicate_create_raises(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path / "p.json")
    store.create(_prof("a"))
    with pytest.raises(ProfileAlreadyExists):
        store.create(_prof("a"))


def test_get_unknown_raises(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path / "p.json")
    with pytest.raises(ProfileNotFound):
        store.get("nope")


def test_update_changes_fields_and_bumps_updated_at(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path / "p.json")
    p = _prof("a")
    store.create(p)
    updated = store.update("a", prompt="new prompt")
    assert updated.prompt == "new prompt"
    assert updated.created_at == p.created_at
    assert updated.updated_at >= p.updated_at


def test_update_unknown_raises(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path / "p.json")
    with pytest.raises(ProfileNotFound):
        store.update("nope", prompt="x")


def test_delete_removes_and_persists(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path / "p.json")
    store.create(_prof("a"))
    store.delete("a")
    assert store.list() == []
    # re-load from disk to confirm
    store2 = ProfileStore(tmp_path / "p.json")
    store2.reload()
    assert store2.list() == []


def test_persists_across_instances(tmp_path: Path) -> None:
    p_path = tmp_path / "p.json"
    s1 = ProfileStore(p_path)
    s1.create(_prof("a"))
    s2 = ProfileStore(p_path)
    s2.reload()
    assert [p.name for p in s2.list()] == ["a"]


def test_concurrent_writes_do_not_corrupt(tmp_path: Path) -> None:
    """Hammer the store from multiple threads; final state must be consistent."""
    p_path = tmp_path / "p.json"
    store = ProfileStore(p_path)

    def writer(name: str) -> None:
        for _ in range(5):
            try:
                store.create(_prof(name))
            except ProfileAlreadyExists:
                pass

    threads = [threading.Thread(target=writer, args=(f"p{i}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    final = ProfileStore(p_path)
    final.reload()
    names = sorted(p.name for p in final.list())
    assert names == sorted(f"p{i}" for i in range(8))
