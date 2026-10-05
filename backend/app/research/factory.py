from app.core.config import Settings
from app.research.contracts import ResearchProvider
from app.research.errors import ResearchProviderConfigurationError
from app.research.providers.gemini.client import GeminiClient
from app.research.providers.gemini.provider import GeminiResearchProvider
from app.research.providers.opencode.client import OpenCodeClient
from app.research.providers.opencode.provider import OpenCodeResearchProvider
from app.research.providers.openrouter.client import OpenRouterClient
from app.research.providers.openrouter.provider import OpenRouterResearchProvider


def create_research_provider(settings: Settings) -> ResearchProvider:
    if (
        settings.matching_strategy == "provider_catalog"
        and settings.research_provider != "gemini"
    ):
        raise ResearchProviderConfigurationError(
            "MATCHING_STRATEGY=provider_catalog is supported only by Gemini"
        )
    if settings.research_provider == "gemini":
        return GeminiResearchProvider(GeminiClient(settings))
    if settings.research_provider == "opencode":
        return OpenCodeResearchProvider(OpenCodeClient(settings))
    if settings.research_provider == "openrouter":
        return OpenRouterResearchProvider(OpenRouterClient(settings), settings)
    raise ResearchProviderConfigurationError(
        f"Unsupported research provider: {settings.research_provider}"
    )


create_research_agent = create_research_provider
