"""ZIP archive validation, safe extraction, and repository-root detection.

An uploaded archive is untrusted input. Every check here exists to keep a
malicious or malformed archive from writing outside its own job workspace,
exhausting disk space, or overwhelming CodeWiki's analysis with an
unreasonable file count — nothing here inspects *what* the archive contains
beyond that; language/content understanding is entirely CodeWiki's job.
"""

from __future__ import annotations

import os
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.core.errors import ArchiveTooLargeError, EmptyRepositoryError, InvalidArchiveError, UnsafeArchiveError

_S_IFLNK = 0o120000
_IGNORED_TOP_LEVEL_NAMES = frozenset({"__MACOSX"})


@dataclass(frozen=True, slots=True)
class ZipIngestionLimits:
    max_archive_bytes: int
    max_extracted_bytes: int
    max_file_count: int


@dataclass(frozen=True, slots=True)
class IngestedRepository:
    """Where the archive ended up and what its detected repository root is."""

    repo_root: Path
    file_count: int
    total_bytes: int


def validate_and_extract(
    archive_path: Path,
    extraction_dir: Path,
    limits: ZipIngestionLimits,
) -> IngestedRepository:
    """Validate ``archive_path`` and extract it into ``extraction_dir``.

    Raises an ``AppError`` subclass (never a bare exception) for every
    rejection reason, so callers get the right HTTP status without needing
    to inspect the failure by hand. ``extraction_dir`` is created if needed;
    nothing is written to disk until every member has passed validation.
    """
    try:
        archive_size = archive_path.stat().st_size
    except OSError as exc:
        raise InvalidArchiveError("The uploaded file could not be read.") from exc

    if archive_size > limits.max_archive_bytes:
        raise ArchiveTooLargeError(
            f"The archive is {archive_size} bytes, exceeding the "
            f"{limits.max_archive_bytes}-byte limit.",
            details={"archive_bytes": archive_size, "limit": limits.max_archive_bytes},
        )

    try:
        zf = zipfile.ZipFile(archive_path)
    except zipfile.BadZipFile as exc:
        raise InvalidArchiveError("The uploaded file is not a valid ZIP archive.") from exc

    with zf:
        infos = zf.infolist()
        if not infos:
            raise EmptyRepositoryError("The uploaded archive is empty.")

        if len(infos) > limits.max_file_count:
            raise ArchiveTooLargeError(
                f"The archive contains {len(infos)} entries, exceeding the "
                f"{limits.max_file_count}-entry limit.",
                details={"entry_count": len(infos), "limit": limits.max_file_count},
            )

        total_uncompressed = 0
        for info in infos:
            _assert_safe_member(info)
            total_uncompressed += info.file_size
            if total_uncompressed > limits.max_extracted_bytes:
                raise ArchiveTooLargeError(
                    "The archive would extract to more than "
                    f"{limits.max_extracted_bytes} bytes.",
                    details={"limit": limits.max_extracted_bytes},
                )

        extraction_dir.mkdir(parents=True, exist_ok=True)
        # Safe now — every member name was validated above, so extractall
        # cannot write outside extraction_dir.
        zf.extractall(extraction_dir)

    repo_root = _detect_repository_root(extraction_dir)
    file_count, total_bytes = _measure(repo_root)
    if file_count == 0:
        raise EmptyRepositoryError("The archive does not contain any files to analyze.")

    return IngestedRepository(repo_root=repo_root, file_count=file_count, total_bytes=total_bytes)


def _assert_safe_member(info: zipfile.ZipInfo) -> None:
    """Reject any archive member that could escape the extraction directory."""
    name = info.filename
    if not name or name.startswith("/") or name.startswith("\\"):
        raise UnsafeArchiveError(f"Unsafe archive entry: {name!r}")

    normalised = name.replace("\\", "/")
    if PurePosixPath(normalised).is_absolute():
        raise UnsafeArchiveError(f"Unsafe archive entry: {name!r}")
    if ":" in normalised:
        # Windows drive letters ("C:evil") aren't meaningful on POSIX
        # extraction, but reject them outright rather than relying on that.
        raise UnsafeArchiveError(f"Unsafe archive entry: {name!r}")
    if ".." in normalised.split("/"):
        raise UnsafeArchiveError(f"Path traversal attempt in archive entry: {name!r}")

    # zipfile can materialize a real symlink from an entry whose external_attr
    # encodes S_IFLNK — if its target (the entry's own file content) points
    # outside the extraction directory, later reads through that symlink
    # would escape it. Refuse any symlink entry outright.
    mode = info.external_attr >> 16
    if stat.S_ISLNK(mode) or (mode & 0o170000) == _S_IFLNK:
        raise UnsafeArchiveError(f"Archive entry is a symlink, which is not allowed: {name!r}")


def _detect_repository_root(extraction_dir: Path) -> Path:
    """Normalise "files at root" vs "single top-level directory" archive layouts.

    If, ignoring known noise entries (e.g. macOS's ``__MACOSX``), the
    archive's top level contains exactly one entry and it's a directory, the
    repository root is that directory — the common "GitHub export" shape
    (``my-project/src/...``, ``my-project/pom.xml``). Otherwise the
    extraction directory itself is the repository root.
    """
    entries = [
        path
        for path in extraction_dir.iterdir()
        if path.name not in _IGNORED_TOP_LEVEL_NAMES
    ]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return extraction_dir


def _measure(root: Path) -> tuple[int, int]:
    file_count = 0
    total_bytes = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            file_count += 1
            try:
                total_bytes += (Path(dirpath) / filename).stat().st_size
            except OSError:
                pass
    return file_count, total_bytes
