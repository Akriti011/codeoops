"""Reads CodeWiki's own output files directly from the shared volume.

``/static-docs`` returns rendered HTML, not Markdown
(codewiki/src/fe/web_app.py), so the raw ``overview.md`` is read from disk —
the ``./output`` directory the CodeOops and CodeWiki containers share —
rather than scraped out of a rendered page.

``metadata.json`` is written by CodeWiki beside the documentation
(codewiki/src/be/documentation_generator.py) and is the only source of truth
for which checkout actually produced a given directory's contents; see
``app.services.codewiki.binding``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.services.codewiki.errors import (
    ArtifactDirNotFoundError,
    MetadataNotFoundError,
    MetadataUnreadableError,
    OverviewEmptyError,
    OverviewNotFoundError,
)

OVERVIEW_FILENAME = "overview.md"
METADATA_FILENAME = "metadata.json"


@dataclass(frozen=True, slots=True)
class CodeWikiArtifactMetadata:
    timestamp: str | None
    main_model: str | None
    generator_version: str | None
    repo_path: str | None
    commit_id: str | None


def read_overview(docs_dir: Path) -> str:
    if not docs_dir.is_dir():
        raise ArtifactDirNotFoundError(
            "CodeWiki's documentation directory does not exist on the shared volume.",
            details={"docs_dir": str(docs_dir)},
        )
    overview_path = docs_dir / OVERVIEW_FILENAME
    if not overview_path.is_file():
        raise OverviewNotFoundError(
            "CodeWiki did not produce an overview document for this repository.",
            details={"path": str(overview_path)},
        )
    text = overview_path.read_text(encoding="utf-8")
    if not text.strip():
        raise OverviewEmptyError(
            "CodeWiki produced an empty overview document.",
            details={"path": str(overview_path)},
        )
    return text


# Downstream artifacts the pipeline may produce beside overview.md. Optional:
# an older CodeWiki build, or HLD/LLD disabled, means they simply are not there.
DOWNSTREAM_DOCUMENTS = (
    "overview.json",
    "hld.md",
    "hld.validation.json",
    "lld.md",
    "lld.validation.json",
)


def read_optional_document(docs_dir: Path, name: str) -> bytes | None:
    """Raw bytes of one downstream document, or ``None`` if it was not produced."""
    if name not in DOWNSTREAM_DOCUMENTS:
        raise ValueError(f"unknown downstream document: {name!r}")
    path = docs_dir / name
    if not path.is_file():
        return None
    data = path.read_bytes()
    return data or None


def read_metadata(docs_dir: Path) -> CodeWikiArtifactMetadata:
    metadata_path = docs_dir / METADATA_FILENAME
    if not metadata_path.is_file():
        raise MetadataNotFoundError(
            "CodeWiki did not write metadata.json for this repository.",
            details={"path": str(metadata_path)},
        )
    try:
        raw = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MetadataUnreadableError(
            "CodeWiki's metadata.json could not be read.",
            details={"path": str(metadata_path), "reason": str(exc)},
        ) from exc

    info = raw.get("generation_info", {}) if isinstance(raw, dict) else {}
    return CodeWikiArtifactMetadata(
        timestamp=info.get("timestamp"),
        main_model=info.get("main_model"),
        generator_version=info.get("generator_version"),
        repo_path=info.get("repo_path"),
        commit_id=info.get("commit_id"),
    )
