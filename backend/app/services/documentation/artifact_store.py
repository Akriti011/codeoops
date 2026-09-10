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

    def delete(self, job_id: uuid.UUID) -> None:
        """Remove this job's verified-artifact directory. Idempotent."""
        with self._lock:
            shutil.rmtree(self._job_dir(job_id), ignore_errors=True)

    def _job_dir(self, job_id: uuid.UUID) -> Path:
        return self._root / str(job_id)
