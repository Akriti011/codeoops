"""Domain enumerations.

Note on unused members: several states below are declared but never assigned in
this phase. They describe the lifecycle the CodeWiki integration will drive, and
they are declared here so the frontend contract does not change when that phase
lands. Nothing in this codebase transitions a record into them.
"""

from __future__ import annotations

from enum import StrEnum


class RepositoryStatus(StrEnum):
    """Lifecycle of a submitted repository record."""

    READY = "READY"
    """Accepted and stored. The only status assigned in this phase."""

    GENERATING = "GENERATING"
    """Reserved: a CodeWiki documentation job is running. Never set yet."""

    COMPLETED = "COMPLETED"
    """Reserved: CodeWiki produced an artifact. Never set yet."""

    FAILED = "FAILED"
    """Reserved: CodeWiki generation failed. Never set yet."""


class DocumentationStatus(StrEnum):
    """State of the documentation belonging to a repository."""

    NOT_GENERATED = "NOT_GENERATED"
    """No CodeWiki artifact exists. The only status returned with no provider."""

    QUEUED = "QUEUED"
    """A job is queued with the documentation provider."""

    GENERATING = "GENERATING"
    """CodeWiki is generating."""

    COMPLETED = "COMPLETED"
    """A verified CodeWiki artifact is available."""

    FAILED = "FAILED"
    """CodeWiki reported a failure."""


class RepositorySource(StrEnum):
    """How a repository's source code reached CodeOops."""

    GITHUB = "GITHUB"
    """Submitted as a public GitHub URL; CodeWiki clones it directly."""

    UPLOAD = "UPLOAD"
    """Submitted as an uploaded ZIP archive; CodeOops extracts it onto the
    shared CodeWiki volume and CodeWiki analyzes that checkout directly,
    skipping its own git-clone step."""


class JobStatus(StrEnum):
    """Lifecycle of one CodeOops-tracked documentation generation attempt.

    Distinct from :class:`DocumentationStatus`, which is the coarser,
    provider-facing vocabulary a repository's *latest* job is mapped onto.
    """

    SUBMITTING = "SUBMITTING"
    """CodeOops is handing the repository to CodeWiki."""

    GENERATING = "GENERATING"
    """CodeWiki accepted the job and is generating documentation."""

    RETRIEVING = "RETRIEVING"
    """CodeWiki finished; CodeOops is verifying and copying the artifact."""

    COMPLETED = "COMPLETED"
    """A verified artifact was copied into CodeOops's own artifact store."""

    FAILED = "FAILED"
    """The job did not produce a verified artifact. See error_code/error_message."""
