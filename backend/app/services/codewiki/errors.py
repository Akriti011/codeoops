"""Failure vocabulary for CodeWiki orchestration.

These are internal to the job pipeline — caught by
``app.services.jobs.job_runner`` and written onto the job record's
``error_code``/``error_message`` rather than raised as HTTP responses. They
are still "reachable, all surfaced verbatim": through the job a client polls,
not through a synchronous exception at submission time (submission always
returns immediately; see app/services/documentation/job_service.py).
"""

from __future__ import annotations

from typing import Any


class CodeWikiError(Exception):
    """Base class for a failure encountered while orchestrating one job."""

    code: str = "CODEWIKI_ERROR"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class CodeWikiUnreachableError(CodeWikiError):
    code = "CODEWIKI_UNREACHABLE"


class CodeWikiSubmitRejectedError(CodeWikiError):
    code = "CODEWIKI_SUBMIT_REJECTED"


class CodeWikiJobNotFoundError(CodeWikiError):
    code = "CODEWIKI_JOB_NOT_FOUND"


class CodeWikiFailedError(CodeWikiError):
    code = "CODEWIKI_FAILED"


class CodeWikiTimeoutError(CodeWikiError):
    code = "CODEWIKI_TIMEOUT"


class DocsPathMissingError(CodeWikiError):
    code = "DOCS_PATH_MISSING"


class UploadWorkspaceOutsideSharedVolumeError(CodeWikiError):
    """The repository's upload workspace isn't under the configured shared volume.

    Would mean CodeWiki's container has no way to see the extracted files —
    caught before submission rather than left to fail as a confusing
    not-found error once CodeWiki tries to analyze it.
    """

    code = "UPLOAD_WORKSPACE_OUTSIDE_SHARED_VOLUME"


class ArtifactDirNotFoundError(CodeWikiError):
    code = "ARTIFACT_DIR_NOT_FOUND"


class OverviewNotFoundError(CodeWikiError):
    code = "OVERVIEW_NOT_FOUND"


class OverviewEmptyError(CodeWikiError):
    code = "OVERVIEW_EMPTY"


class MetadataNotFoundError(CodeWikiError):
    code = "METADATA_NOT_FOUND"


class MetadataUnreadableError(CodeWikiError):
    code = "METADATA_UNREADABLE"


class ArtifactBindingMismatchError(CodeWikiError):
    code = "ARTIFACT_BINDING_MISMATCH"


class RunnerError(CodeWikiError):
    code = "RUNNER_ERROR"
