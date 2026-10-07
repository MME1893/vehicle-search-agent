class ResearchProviderError(RuntimeError):
    """Base error for research-provider configuration and execution failures."""


class ResearchProviderConfigurationError(ResearchProviderError):
    pass


class ResearchProviderTimeoutError(ResearchProviderError):
    pass


class ProviderAuthenticationError(ResearchProviderError):
    """The supplied credential is invalid and should not be retried."""


class ProviderQuotaError(ResearchProviderError):
    """The credential has no remaining credit/quota and should be disabled."""


class ProviderRateLimitError(ResearchProviderError):
    """A temporary provider throttle; another credential may be attempted."""


class ProviderExecutionError(ResearchProviderError):
    """A provider/model failed to execute a research request."""


class GeminiProviderError(ProviderExecutionError):
    pass
