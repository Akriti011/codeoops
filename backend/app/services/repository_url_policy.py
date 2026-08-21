"""Repository URL validation and normalisation.

One place decides what a submittable repository URL is. Routes never parse URLs.

Policy for this phase: public GitHub over HTTPS only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.core.errors import InvalidRepositoryUrlError

_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_ALLOWED_SCHEMES = frozenset({"https"})


@dataclass(frozen=True, slots=True)
class RepositoryCoordinates:
    """The normalised result of parsing a submitted repository URL."""

    host: str
    owner: str
    name: str
    canonical_url: str

    @property
    def identity_key(self) -> str:
        return f"github:{self.owner.lower()}/{self.name.lower()}"


class RepositoryUrlPolicy:
    """Validates and normalises repository URLs against an allowed host list."""

    def __init__(self, allowed_hosts: list[str]) -> None:
        self._allowed_hosts = {host.lower().lstrip("www.") for host in allowed_hosts}

    def parse(self, raw_url: str) -> RepositoryCoordinates:
        """Parse ``raw_url`` into canonical coordinates.

        Raises:
            InvalidRepositoryUrlError: if the URL is not an acceptable
                repository URL for a currently allowed host.
        """
        candidate = (raw_url or "").strip()
        if not candidate:
            raise InvalidRepositoryUrlError("Enter a GitHub repository URL.")

        if "://" not in candidate:
            raise InvalidRepositoryUrlError(
                "The URL must start with https://",
                details={"repository_url": raw_url},
            )

        parts = urlsplit(candidate)

        if parts.scheme.lower() not in _ALLOWED_SCHEMES:
            raise InvalidRepositoryUrlError(
                "Only https:// repository URLs are accepted.",
                details={"scheme": parts.scheme},
            )

        if "@" in parts.netloc:
            raise InvalidRepositoryUrlError(
                "Repository URLs must not contain credentials.",
            )

        if parts.port is not None:
            raise InvalidRepositoryUrlError(
                "Repository URLs must not specify a port.",
                details={"port": parts.port},
            )

        host = (parts.hostname or "").lower()
        normalised_host = host[4:] if host.startswith("www.") else host
        if normalised_host not in self._allowed_hosts:
            raise InvalidRepositoryUrlError(
                f"Only repositories hosted on {', '.join(sorted(self._allowed_hosts))} "
                "are supported.",
                details={"host": host or None},
            )

        segments = [segment for segment in parts.path.split("/") if segment]
        if len(segments) != 2:
            raise InvalidRepositoryUrlError(
                "The URL must point at a repository, e.g. "
                "https://github.com/owner/repository.",
                details={"path": parts.path},
            )

        owner, name = segments
        if name.endswith(".git"):
            name = name[: -len(".git")]

        for label, segment in (("owner", owner), ("repository", name)):
            if not _SEGMENT.match(segment):
                raise InvalidRepositoryUrlError(
                    f"'{segment}' is not a valid {label} name.",
                    details={label: segment},
                )

        return RepositoryCoordinates(
            host=normalised_host,
            owner=owner,
            name=name,
            canonical_url=f"https://{normalised_host}/{owner}/{name}",
        )
