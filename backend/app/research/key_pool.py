from dataclasses import dataclass


def parse_key_pool(plural: str | None, singular: str | None) -> list[str]:
    """Return a stable, de-duplicated key pool without ever logging key material."""
    candidates = plural.split(",") if plural and plural.strip() else []
    keys: list[str] = []
    for candidate in candidates:
        key = candidate.strip() if candidate else ""
        if key and key not in keys:
            keys.append(key)
    if not keys and singular and singular.strip():
        keys.append(singular.strip())
    return keys


@dataclass(frozen=True)
class KeyLease:
    index: int
    key: str


class ProviderKeyPool:
    """Deterministic sequential credential pool for single-request execution."""

    def __init__(self, keys: list[str]):
        self._keys = list(keys)
        self._disabled: set[int] = set()

    def available(self) -> list[KeyLease]:
        return [
            KeyLease(index=index, key=key)
            for index, key in enumerate(self._keys, start=1)
            if index not in self._disabled
        ]

    def disable(self, index: int) -> None:
        self._disabled.add(index)

    def is_disabled(self, index: int) -> bool:
        return index in self._disabled

    def __bool__(self) -> bool:
        return bool(self.available())
