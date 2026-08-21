"""Confirms a CodeWiki artifact actually belongs to the repository CodeOops asked for.

``metadata.json``'s ``repo_path`` records, in the engine's own words, which
checkout was analysed (``output/temp/{owner}--{repo}``). Its final path
segment is CodeWiki's job id for that repository. If that disagrees with the
job CodeOops is retrieving for, the artifact is refused rather than served —
this is what keeps a stale or cross-repository CodeWiki output directory from
ever being presented as this repository's documentation.
"""

from __future__ import annotations

from app.services.codewiki.artifacts import CodeWikiArtifactMetadata
from app.services.codewiki.errors import ArtifactBindingMismatchError


def verify_binding(metadata: CodeWikiArtifactMetadata, expected_codewiki_job_id: str) -> None:
    repo_path = metadata.repo_path or ""
    actual_job_id = repo_path.rstrip("/").rsplit("/", 1)[-1] if repo_path else ""
    if actual_job_id != expected_codewiki_job_id:
        raise ArtifactBindingMismatchError(
            "The retrieved artifact does not belong to the requested repository.",
            details={
                "expected_codewiki_job_id": expected_codewiki_job_id,
                "actual_codewiki_job_id": actual_job_id or None,
                "repo_path": metadata.repo_path,
            },
        )
