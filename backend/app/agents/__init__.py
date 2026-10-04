from app.agents.evaluator import evaluate_research
from app.agents.schemas import EngineOilResearchResult, ResearchEvaluation

__all__ = [
    "EngineOilResearchResult",
    "OpenCodeResearchAgent",
    "ResearchAgent",
    "ResearchEvaluation",
    "evaluate_research",
]


def __getattr__(name: str):
    if name == "OpenCodeResearchAgent":
        from app.agents.opencode_research_agent import OpenCodeResearchAgent

        return OpenCodeResearchAgent
    if name == "ResearchAgent":
        from app.agents.research_agent import ResearchAgent

        return ResearchAgent
    raise AttributeError(name)
