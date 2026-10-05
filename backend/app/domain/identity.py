import re
import unicodedata
from decimal import Decimal


def normalize_identity_part(value: object | None) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).casefold().strip()
    return re.sub(r"[^\w]+", "", text)


def normalize_sae(value: str) -> str:
    return re.sub(r"[^0-9W]", "", unicodedata.normalize("NFKC", value).upper())


def normalize_package_volume(value: object | None) -> str:
    if value is None or value == "":
        return ""
    decimal_value = Decimal(str(value))
    if not decimal_value.is_finite():
        raise ValueError("package volume must be finite")
    if decimal_value == 0:
        return "0"
    return format(decimal_value.normalize(), "f")


def engine_oil_identity_key(
    brand: str,
    name: str,
    sae_viscosity: str,
    package_volume_liters: object | None = None,
) -> str:
    return "|".join(
        (
            normalize_identity_part(brand),
            normalize_identity_part(name),
            normalize_sae(sae_viscosity),
            normalize_package_volume(package_volume_liters),
        )
    )


def vehicle_identity_key(
    manufacturer: str,
    model: str,
    trim: str | None,
    production_year_from: int | None,
    production_year_to: int | None,
    engine_code: str | None,
    engine_displacement: str | None,
    engine_type: str | None,
    fuel_type: str | None,
    transmission: str | None,
    drivetrain: str | None,
    body_type: str | None,
    body_style: str | None,
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
            engine_type,
            fuel_type,
            transmission,
            drivetrain,
            body_type,
            body_style,
        )
    )
