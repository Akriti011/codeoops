"""Orchestrates ZIP-upload ingestion: save, validate, extract, register.

Pure orchestration over :mod:`app.services.uploads.zip_ingestion` (archive
safety/extraction) and :class:`~app.services.repository_service.RepositoryService`
(repository registration) — no repository-analysis or documentation-generation
logic of any kind lives here. CodeWiki remains the only system that reads the
extracted files for meaning.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.core.errors import ArchiveTooLargeError
from app.models.repository import Repository
from app.services.repository_service import RepositoryService
from app.services.uploads.zip_ingestion import ZipIngestionLimits, validate_and_extract

_UPLOAD_CHUNK_BYTES = 1024 * 1024


class ZipUploadService:
    """Turns an uploaded ZIP into a registered, CodeWiki-visible :class:`Repository`."""

    def __init__(
        self,
        repositories: RepositoryService,
        output_root: Path,
        limits: ZipIngestionLimits,
    ) -> None:
        self._repositories = repositories
        self._output_root = output_root
        self._limits = limits

    async def ingest(self, upload: UploadFile) -> Repository:
        repository_id = uuid.uuid4()
        job_dir = self._output_root / "uploads" / str(repository_id)
        input_dir = job_dir / "input"
        repo_dir = job_dir / "repo"

        try:
            input_dir.mkdir(parents=True, exist_ok=True)
            archive_path = input_dir / "upload.zip"
            await self._save_upload(upload, archive_path)

            ingested = validate_and_extract(archive_path, repo_dir, self._limits)

            # The raw archive itself isn't needed once its contents are
            # extracted and validated.
            archive_path.unlink(missing_ok=True)

            original_filename = upload.filename or "upload.zip"
            project_name = _derive_project_name(repo_dir, ingested.repo_root, original_filename)

            return self._repositories.register_upload(
                repository_id=repository_id,
                name=project_name,
                workspace_path=ingested.repo_root,
                original_filename=original_filename,
                file_count=ingested.file_count,
                total_bytes=ingested.total_bytes,
            )
        except Exception:
            # Never leave a partially-extracted or rejected workspace behind.
            shutil.rmtree(job_dir, ignore_errors=True)
            raise

    async def _save_upload(self, upload: UploadFile, destination: Path) -> None:
        """Stream the upload to disk, aborting as soon as it exceeds the size limit.

        Checked while streaming rather than only after — a client claiming a
        small Content-Length but sending more (or a request with none at
        all) shouldn't be able to write past the configured limit.
        """
        written = 0
        with destination.open("wb") as out:
            while chunk := await upload.read(_UPLOAD_CHUNK_BYTES):
                written += len(chunk)
                if written > self._limits.max_archive_bytes:
                    raise ArchiveTooLargeError(
                        f"The archive exceeds the {self._limits.max_archive_bytes}-byte limit.",
                        details={"limit": self._limits.max_archive_bytes},
                    )
                out.write(chunk)


def _derive_project_name(extraction_dir: Path, repo_root: Path, original_filename: str) -> str:
    """Prefer the archive's own single top-level directory name, when there was one.

    When the archive had files directly at its root instead, ``repo_root``
    is just ``extraction_dir`` itself (a fixed, meaningless "repo" workspace
    name) — fall back to the uploaded file's own name in that case.
    """
    if repo_root != extraction_dir and repo_root.name:
        return repo_root.name
    stem = Path(original_filename).stem
    return stem or "uploaded-repository"
