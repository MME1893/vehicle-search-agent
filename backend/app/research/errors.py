class ResearchProviderError(RuntimeError):
    """Base error for research-provider configuration and execution failures."""


class ResearchProviderConfigurationError(ResearchProviderError):
    pass


class ResearchProviderTimeoutError(ResearchProviderError):
    pass


class GeminiProviderError(ResearchProviderError):
    pass
