"""The documentation provider boundary.

    Angular  ->  FastAPI  ->  DocumentationProvider  ->  CodeWiki

This module defines the *port* only. There is intentionally no implementation
in this build, and no default/fallback implementation anywhere in the codebase.

Rules this boundary exists to enforce:

* CodeOops orchestrates a documentation engine. It is not one.
* No LLM client, no Markdown authoring, no templated "sample" documentation,
  and no placeholder artifact may ever be produced on this side of the port.
* If no provider is registered, the honest answer is
  :class:`~app.models.enums.DocumentationStatus.NOT_GENERATED` for reads and
  ``501 DOCUMENTATION_PROVIDER_NOT_CONFIGURED`` for generation requests.

The one adapter, ``CodeWikiProvider`` (app/providers/codewiki_provider.py),
talks to a real CodeWiki web app instance over HTTP and returns references to
the files CodeWiki itself wrote. Adding it did not require changing this
file — only ``get_documentation_provider`` below, which is the single wiring
point the brief always intended it to be.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod

from app.core.config import Settings, get_settings
from app.models.documentation import DocumentationState
from app.models.repository import Repository


class DocumentationProvider(ABC):
    """Port for an external documentation-generation engine."""

    #: Stable identifier of the concrete engine, e.g. ``"codewiki"``.
    name: str

    @abstractmethod
    async def get_state(self, repository: Repository) -> DocumentationState:
        """Return the current documentation state for ``repository``.

        Implementations must report only what the engine actually produced.
        """

    @abstractmethod
    async def request_generation(self, repository: Repository) -> DocumentationState:
        """Ask the engine to generate documentation for ``repository``.

        Implementations must not block until generation finishes; they return the
        state of the newly created engine job.
        """

    @abstractmethod
    async def read_document(
        self, repository: Repository, artifact_id: uuid.UUID, document_path: str
    ) -> bytes:
        """Return the exact bytes of one document the engine produced.

        Implementations return engine output verbatim. No transformation,
        re-rendering, or summarisation is permitted here.
        """


def get_documentation_provider(settings: Settings | None = None) -> DocumentationProvider | None:
    """Resolve the configured provider from ``settings`` (or the global default).

    Returns ``None`` unless ``DOCUMENTATION_PROVIDER=codewiki`` and a
    ``CODEWIKI_BASE_URL`` are both configured — this function is the single
    wiring point; nothing else in the application needs to know a provider is
    connected. Deferred import below avoids a cycle: ``codewiki_provider``
    imports the ``DocumentationProvider`` ABC from this module. The provider
    instance itself is cheap and stateless — the state that matters (jobs,
    artifacts) lives in the singletons ``get_job_service`` composes, so there
    is nothing to cache here.
    """
    settings = settings or get_settings()
    if settings.documentation_provider != "codewiki" or not settings.codewiki_base_url:
        return None

    from app.providers.codewiki_provider import CodeWikiProvider
    from app.services.documentation.job_service import get_job_service

    return CodeWikiProvider(get_job_service(settings))
