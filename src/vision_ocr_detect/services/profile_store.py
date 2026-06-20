"""Profile persistence backed by a JSON file.

The store keeps an in-memory dict as the source of truth and persists to
`profiles.json` on every mutation. Concurrency is protected with an
`flock`-based lock file so multiple processes (e.g. server + admin tool)
don't corrupt the file.

Atomic write strategy:
  1. Acquire exclusive flock on `<path>.lock`
  2. Write to `<path>.tmp`
  3. `Path.replace()` → atomic rename over `<path>`
  4. Release flock
"""

from __future__ import annotations

import fcntl
import json
from pathlib import Path
from typing import Iterator

from vision_ocr_detect.models.profile import Profile, utcnow


class ProfileAlreadyExists(Exception):
    """Raised when creating a profile whose name is already taken."""


class ProfileNotFound(Exception):
    """Raised when reading/updating/deleting an unknown profile."""


class ProfileStore:
    """JSON-file backed profile store."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock_path = path.with_suffix(path.suffix + ".lock")
        self._cache: dict[str, Profile] = {}
        self._loaded = False

    # ----- public API -----

    def list(self) -> list[Profile]:
        self._ensure_loaded()
        return list(self._cache.values())

    def get(self, name: str) -> Profile:
        self._ensure_loaded()
        try:
            return self._cache[name]
        except KeyError as e:
            raise ProfileNotFound(name) from e

    def create(self, profile: Profile) -> Profile:
        self._ensure_loaded()
        with self._exclusive_lock():
            if profile.name in self._cache:
                raise ProfileAlreadyExists(profile.name)
            self._cache[profile.name] = profile
            self._flush_unlocked()
        return profile

    def update(
        self,
        name: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        prompt: str | None = None,
    ) -> Profile:
        self._ensure_loaded()
        with self._exclusive_lock():
            current = self._cache.get(name)
            if current is None:
                raise ProfileNotFound(name)
            updated = current.model_copy(
                update={
                    "provider": provider if provider is not None else current.provider,
                    "model": model if model is not None else current.model,
                    "prompt": prompt if prompt is not None else current.prompt,
                    "updated_at": utcnow(),
                }
            )
            self._cache[name] = updated
            self._flush_unlocked()
        return updated

    def delete(self, name: str) -> None:
        self._ensure_loaded()
        with self._exclusive_lock():
            if name not in self._cache:
                raise ProfileNotFound(name)
            del self._cache[name]
            self._flush_unlocked()

    def reload(self) -> None:
        """Force a re-read from disk. Used by tests; not on the hot path."""
        with self._exclusive_lock():
            self._load_unlocked()
            self._loaded = True

    # ----- internals -----

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._shared_lock():
            self._load_unlocked()
        self._loaded = True

    def _load_unlocked(self) -> None:
        if not self._path.exists():
            self._cache = {}
            return
        raw = self._path.read_text(encoding="utf-8")
        if not raw.strip():
            self._cache = {}
            return
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError(f"{self._path} must contain a JSON object at the top level")
        self._cache = {k: Profile.model_validate(v) for k, v in data.items()}

    def _flush_unlocked(self) -> None:
        """Serialize cache to disk atomically. Caller must hold exclusive lock."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        payload = {
            name: p.model_dump(mode="json") for name, p in self._cache.items()
        }
        tmp.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(self._path)

    # ----- file locking helpers -----

    def _exclusive_lock(self) -> "_Lock":
        return _Lock(self._lock_path, fcntl.LOCK_EX)

    def _shared_lock(self) -> "_Lock":
        return _Lock(self._lock_path, fcntl.LOCK_SH)


class _Lock:
    """Context manager wrapping fcntl.flock on a sidecar file."""

    def __init__(self, path: Path, mode: int) -> None:
        self._path = path
        self._mode = mode
        self._fp = None  # type: ignore[assignment]

    def __enter__(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fp = self._path.open("a+", encoding="utf-8")
        fcntl.flock(self._fp.fileno(), self._mode)

    def __exit__(self, *_: object) -> None:
        if self._fp is not None:
            fcntl.flock(self._fp.fileno(), fcntl.LOCK_UN)
            self._fp.close()
            self._fp = None
