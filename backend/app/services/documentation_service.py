"""Documentation orchestration.

This service owns exactly one decision: *ask the configured documentation
provider what exists*. It never produces documentation content itself.

With no provider configured (this phase), the answer is always
``NOT_GENERATED`` with a ``null`` artifact.
"""

from __future__ import annotations

from app.core.errors import DocumentationProviderNotConfiguredError
from app.models.documentation import DocumentationState
from app.models.enums import DocumentationStatus
from app.models.repository import Repository
from app.providers.documentation_provider import DocumentationProvider

_NO_PROVIDER_DETAIL = (
    "No documentation provider is connected. CodeWiki integration is not "
    "enabled in this build."
)


class DocumentationService:
    def __init__(self, provider: DocumentationProvider | None) -> None:
        self._provider = provider

    @property
    def provider_name(self) -> str | None:
        return self._provider.name if self._provider is not None else None

    async def get_state(self, repository: Repository) -> DocumentationState:
        """Report the documentation state of ``repository``.

        There is no fallback branch that synthesises content: when no provider
        is connected the state is NOT_GENERATED and the artifact is None.
        """
        if self._provider is None:
            return DocumentationState(
                repository_id=repository.id,
                status=DocumentationStatus.NOT_GENERATED,
                artifact=None,
                detail=_NO_PROVIDER_DETAIL,
            )
        return await self._provider.get_state(repository)

    async def request_generation(self, repository: Repository) -> DocumentationState:
        """Ask the provider to generate documentation.

        Fails loudly when no engine is connected rather than producing anything.
        """
        if self._provider is None:
            raise DocumentationProviderNotConfiguredError(_NO_PROVIDER_DETAIL)
        return await self._provider.request_generation(repository)
