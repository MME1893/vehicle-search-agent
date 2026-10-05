__all__ = ["ResearchOutcome", "ResearchService"]


def __getattr__(name: str):
    if name in __all__:
        from app.research.service import ResearchOutcome, ResearchService

        return {"ResearchOutcome": ResearchOutcome, "ResearchService": ResearchService}[name]
    raise AttributeError(name)
