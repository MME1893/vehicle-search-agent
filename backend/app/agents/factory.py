from app.agents.client import OpenRouterClient
from app.agents.errors import ResearchProviderConfigurationError
from app.agents.gemini_client import GeminiClient
from app.agents.gemini_research_adapter import GeminiResearchAdapter
from app.agents.opencode_client import OpenCodeClient
from app.agents.opencode_research_agent import OpenCodeResearchAgent
from app.agents.protocols import ResearchProvider
from app.agents.research_agent import ResearchAgent
from app.core.config import Settings


def create_research_provider(settings: Settings) -> ResearchProvider:
    if (
        settings.matching_strategy == "provider_catalog"
        and settings.research_provider != "gemini"
    ):
        raise ResearchProviderConfigurationError(
            "MATCHING_STRATEGY=provider_catalog is supported only by Gemini"
        )
    if settings.research_provider == "gemini":
        return GeminiResearchAdapter(GeminiClient(settings))
    if settings.research_provider == "opencode":
        return OpenCodeResearchAgent(OpenCodeClient(settings))
    if settings.research_provider == "openrouter":
        return ResearchAgent(OpenRouterClient(settings), settings)
    raise ResearchProviderConfigurationError(
        f"Unsupported research provider: {settings.research_provider}"
    )


create_research_agent = create_research_provider
