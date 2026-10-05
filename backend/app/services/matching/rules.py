import re

from app.core.constants import API_RANK, DIESEL_API_RANK

_API_PREFIX = re.compile(r"^\s*(?:minimum\s+)?api(?:\s*[-:]\s*|\s+)", re.IGNORECASE)
_CATEGORY = re.compile(
    r"(?<![A-Z0-9])(?:SN\s*(?:PLUS|\+)|S[A-Z]|C[FGHIJK]-?4|CF|FA-4)(?![A-Z0-9])"
)


def normalize_api_spec(value: str | None) -> str:
    if not value:
        return ""
    normalized = _API_PREFIX.sub("", value, count=1).strip().upper()
    normalized = re.sub(
        r"\bSN(?:\s*\+|[\s_-]+PLUS)(?=$|[^A-Z0-9])", "SN PLUS", normalized
    )
    return " ".join(normalized.split())


def extract_api_categories(value: str | None) -> list[str]:
    normalized = normalize_api_spec(value)
    categories: list[str] = []
    for match in _CATEGORY.finditer(normalized):
        category = re.sub(r"\s+", " ", match.group()).replace("SN +", "SN PLUS")
        if category.startswith(("CF", "CG", "CH", "CI", "CJ", "CK")) and len(category) > 2:
            category = category[:2] + "-4"
        if category not in categories:
            categories.append(category)
    return categories


def extract_gasoline_api_categories(value: str | None) -> list[str]:
    return [category for category in extract_api_categories(value) if category in API_RANK]


def extract_diesel_api_categories(value: str | None) -> list[str]:
    return [
        category
        for category in extract_api_categories(value)
        if category in DIESEL_API_RANK or category == "FA-4"
    ]


def normalize_fuel_type(value: str | None) -> str | None:
    normalized = (value or "").strip().casefold()
    if normalized in {"gasoline", "petrol", "gas"}:
        return "gasoline"
    if normalized in {"diesel", "gasoil"}:
        return "diesel"
    return None


def resolve_api_family(fuel_type: str | None, minimum: str | None) -> str | None:
    explicit = normalize_fuel_type(fuel_type)
    if explicit:
        return explicit
    if fuel_type and fuel_type.strip():
        return None
    categories = extract_api_categories(minimum)
    has_gasoline = any(category in API_RANK for category in categories)
    has_diesel = any(
        category in DIESEL_API_RANK or category == "FA-4" for category in categories
    )
    if has_gasoline != has_diesel:
        return "gasoline" if has_gasoline else "diesel"
    return None


def api_satisfies(
    actual: str | None, minimum: str | None, fuel_type: str | None = None
) -> bool:
    if not minimum:
        return True
    family = resolve_api_family(fuel_type, minimum)
    if family == "diesel":
        actual_categories = extract_diesel_api_categories(actual)
        minimum_categories = extract_diesel_api_categories(minimum)
        if "FA-4" in minimum_categories:
            return "FA-4" in actual_categories
        ranked_actual = [DIESEL_API_RANK[x] for x in actual_categories if x in DIESEL_API_RANK]
        ranked_minimum = [DIESEL_API_RANK[x] for x in minimum_categories if x in DIESEL_API_RANK]
        return bool(ranked_actual and ranked_minimum) and max(ranked_actual) >= max(ranked_minimum)
    if family == "gasoline":
        actual_categories = extract_gasoline_api_categories(actual)
        minimum_categories = extract_gasoline_api_categories(minimum)
        return bool(actual_categories and minimum_categories) and max(
            API_RANK[x] for x in actual_categories
        ) >= max(API_RANK[x] for x in minimum_categories)
    return False


def overlap(left: list[str], right: list[str]) -> list[str]:
    right_normalized = {x.strip().upper() for x in right}
    return [x for x in left if x.strip().upper() in right_normalized]
