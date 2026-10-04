import re

from app.core.constants import API_RANK

_API_PREFIX = re.compile(r"^\s*(?:minimum\s+)?api(?:\s*[-:]\s*|\s+)", re.IGNORECASE)


def normalize_api_spec(value: str | None) -> str:
    if not value:
        return ""
    normalized = _API_PREFIX.sub("", value, count=1)
    return " ".join(normalized.strip().upper().split())


def extract_gasoline_api_categories(value: str | None) -> list[str]:
    normalized = normalize_api_spec(value)
    if not normalized:
        return []
    return [
        category
        for part in normalized.split("/")
        if (category := part.strip()) in API_RANK
    ]


def api_satisfies(actual: str | None, minimum: str | None) -> bool:
    if not minimum:
        return True
    actual_categories = extract_gasoline_api_categories(actual)
    minimum_categories = extract_gasoline_api_categories(minimum)
    if not actual_categories or not minimum_categories:
        return False
    actual_rank = max(API_RANK[category] for category in actual_categories)
    minimum_rank = max(API_RANK[category] for category in minimum_categories)
    return actual_rank >= minimum_rank


def overlap(left: list[str], right: list[str]) -> list[str]:
    right_normalized = {x.strip().upper() for x in right}
    return [x for x in left if x.strip().upper() in right_normalized]
