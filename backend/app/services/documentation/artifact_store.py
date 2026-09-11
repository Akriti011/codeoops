"""Storage for verified CodeWiki artifacts, keyed by CodeOops's own job id.

CodeWiki reuses one output directory per repository and overwrites it on
every run (see the module docstring in
``app.services.codewiki.artifacts``). CodeOops therefore copies the verified
bytes out immediately on completion, so an older completed job keeps
returning what it actually produced even after a newer run overwrites
CodeWiki's own copy.
"""

from __future__ import annotations

import shutil
import threading
import uuid
from pathlib import Path

OVERVIEW_FILENAME = "overview.md"


class ArtifactStore:
    """Filesystem-backed store: one directory per CodeOops job id."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._lock = threading.RLock()

    def save_overview(self, job_id: uuid.UUID, content: bytes) -> Path:
        with self._lock:
            job_dir = self._job_dir(job_id)
            job_dir.mkdir(parents=True, exist_ok=True)
            path = job_dir / OVERVIEW_FILENAME
            path.write_bytes(content)
            return path

    def read_overview(self, job_id: uuid.UUID) -> bytes | None:
        path = self._job_dir(job_id) / OVERVIEW_FILENAME
        if not path.is_file():
            return None
        return path.read_bytes()

    def save_document(self, job_id: uuid.UUID, name: str, content: bytes) -> Path:
        """Store one downstream document (overview.json / hld.md / lld.md / …)
        next to the overview. ``name`` is a bare filename, never a path."""
        safe = Path(name).name
        with self._lock:
            job_dir = self._job_dir(job_id)
            job_dir.mkdir(parents=True, exist_ok=True)
            path = job_dir / safe
            path.write_bytes(content)
            return path

    def read_document(self, job_id: uuid.UUID, name: str) -> bytes | None:
        path = self._job_dir(job_id) / Path(name).name
        if not path.is_file():
            return None
        return path.read_bytes()

    def list_documents(self, job_id: uuid.UUID) -> list[str]:
        job_dir = self._job_dir(job_id)
        if not job_dir.is_dir():
            return []
        return sorted(p.name for p in job_dir.iterdir() if p.is_file() and p.name != OVERVIEW_FILENAME)

    def delete(self, job_id: uuid.UUID) -> None:
        """Remove this job's verified-artifact directory. Idempotent."""
        with self._lock:
            shutil.rmtree(self._job_dir(job_id), ignore_errors=True)

    def _job_dir(self, job_id: uuid.UUID) -> Path:
        return self._root / str(job_id)
