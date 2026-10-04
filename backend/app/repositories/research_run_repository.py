from app.models import ResearchRun
from app.repositories.base import Repository


class ResearchRunRepository(Repository[ResearchRun]):
    model = ResearchRun
