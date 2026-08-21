"""Derives CodeWiki's own job id for a repository.

CodeWiki's web frontend gives no machine-readable job id in its ``POST /``
response (codewiki/src/fe/web_app.py). It derives the id deterministically as
``f"{owner}--{repo}"`` (routes.py::_repo_full_name_to_job_id) from the
repository it was given. CodeOops reproduces that same derivation so it can
poll ``GET /api/job/{job_id}`` immediately after submitting, without waiting
on a response body CodeWiki never provides — the derived id is then confirmed
against that endpoint, which is authoritative.
"""

from __future__ import annotations


def derive_codewiki_job_id(owner: str, name: str) -> str:
    return f"{owner}--{name}"
