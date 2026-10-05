import re
import unicodedata


def normalize_identity_part(value: object | None) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).casefold().strip()
    return re.sub(r"[^\w]+", "", text)


def normalize_sae(value: str) -> str:
    return re.sub(r"[^0-9W]", "", unicodedata.normalize("NFKC", value).upper())


def engine_oil_identity_key(brand: str, name: str, sae_viscosity: str) -> str:
    return "|".join(
        (normalize_identity_part(brand), normalize_identity_part(name), normalize_sae(sae_viscosity))
    )


def vehicle_identity_key(
    manufacturer: str,
    model: str,
    trim: str | None,
    production_year_from: int | None,
    production_year_to: int | None,
    engine_code: str | None,
    engine_displacement: str | None,
    fuel_type: str | None,
) -> str:
    return "|".join(
        normalize_identity_part(value)
        for value in (
            manufacturer,
            model,
            trim,
            production_year_from,
            production_year_to,
            engine_code,
            engine_displacement,
            fuel_type,
        )
    )
