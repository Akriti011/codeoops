"""Confirms a CodeWiki artifact actually belongs to the repository CodeOops asked for.

``metadata.json``'s ``repo_path`` records, in the engine's own words, which
checkout was analysed. What counts as a match depends on how the repository
reached CodeWiki, and the two sources are genuinely different shapes here —
not a case that was relaxed for uploads, but two separate real checks:

* **GitHub-sourced**: CodeWiki clones the repository itself, into a directory
  *it* names — ``output/temp/{owner}--{repo}`` — whose final path segment is,
  by CodeWiki's own convention, exactly the job id CodeOops derived
  (``identity.derive_codewiki_job_id``). Comparing that segment against the
  expected job id is correct and is the only thing CodeOops can check, since
  it never learns the clone's full path.

* **Upload-sourced**: there is no such convention to rely on. CodeOops itself
  extracts the archive and hands CodeWiki an already-existing local path to
  analyse (see ``job_runner._to_container_local_path``) — ``config.repo_path``
  on CodeWiki's side is *exactly* that path, verbatim, and its final segment
  is whatever the archive's own top-level folder (or the uploaded filename)
  happened to be named. It was never going to equal the job id, for any
  upload, ever — that's not a mismatch signal for this source, it's a
  guaranteed false positive. The real check is the one CodeOops can actually
  make with certainty: does ``repo_path`` equal the exact path CodeOops
  itself told CodeWiki to analyse?

Either way, if the check fails, the artifact is refused rather than served —
this is what keeps a stale or cross-repository CodeWiki output directory from
ever being presented as this repository's documentation.
"""

from __future__ import annotations

from app.services.codewiki.artifacts import CodeWikiArtifactMetadata
from app.services.codewiki.errors import ArtifactBindingMismatchError


def verify_binding(
    metadata: CodeWikiArtifactMetadata,
    expected_codewiki_job_id: str,
    *,
    expected_repo_path: str | None = None,
) -> None:
    """Verify ``metadata`` was produced for the repository CodeOops expects.

    Pass ``expected_repo_path`` (the exact local path CodeOops submitted —
    see ``job_runner._to_container_local_path``) for an upload-sourced job;
    leave it ``None`` for a GitHub-sourced job, where CodeOops has no such
    path to compare and the job-id-suffix convention applies instead.
    """
    repo_path = metadata.repo_path or ""

    if expected_repo_path is not None:
        if repo_path.rstrip("/") != expected_repo_path.rstrip("/"):
            raise ArtifactBindingMismatchError(
                "The retrieved artifact does not belong to the requested repository.",
                details={
                    "expected_repo_path": expected_repo_path,
                    "actual_repo_path": metadata.repo_path,
                },
            )
        return

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
