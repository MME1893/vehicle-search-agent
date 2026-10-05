"""extend vehicle variants and engine-oil package products

Downgrade refuses to proceed when multiple package-volume products would collapse
to the same pre-package EngineOil identity. No rows are merged or deleted.
"""

import re
import unicodedata
from decimal import Decimal

import sqlalchemy as sa
from alembic import op

revision = "0006_vehicle_oil_catalog"
down_revision = "0005_current_integrity"
branch_labels = None
depends_on = None


def _part(value):
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).casefold().strip()
    return re.sub(r"[^\w]+", "", text)


def _sae(value):
    return re.sub(r"[^0-9W]", "", unicodedata.normalize("NFKC", value).upper())


def _volume(value):
    if value is None or value == "":
        return ""
    decimal_value = Decimal(str(value))
    if decimal_value == 0:
        return "0"
    return format(decimal_value.normalize(), "f")


def _vehicle_key(row, extended=True):
    values = [
        row.manufacturer,
        row.model,
        row.trim,
        row.production_year_from,
        row.production_year_to,
        row.engine_code,
        row.engine_displacement,
    ]
    if extended:
        values.append(row.engine_type)
    values.append(row.fuel_type)
    if extended:
        values.extend(
            (row.transmission, row.drivetrain, row.body_type, row.body_style)
        )
    return "|".join(_part(value) for value in values)


def _oil_key(row, include_volume=True):
    values = [_part(row.brand), _part(row.name), _sae(row.sae_viscosity)]
    if include_volume:
        values.append(_volume(row.package_volume_liters))
    return "|".join(values)


def _target_keys(table, key_function):
    rows = list(
        op.get_bind().execute(sa.text(f"SELECT * FROM {table} ORDER BY id")).mappings()
    )
    keyed = [(row.id, key_function(row)) for row in rows]
    seen = {}
    for ident, key in keyed:
        if key in seen:
            raise RuntimeError(
                f"cannot rebuild {table} identities: ids {seen[key]} and {ident} "
                f"normalize to duplicate identity {key!r}"
            )
        seen[key] = ident
    return keyed


def _apply_keys(table, constraint, keyed):
    bind = op.get_bind()
    op.drop_constraint(constraint, table, type_="unique")
    for ident, key in keyed:
        bind.execute(
            sa.text(f"UPDATE {table} SET identity_key=:key WHERE id=:id"),
            {"key": key, "id": ident},
        )
    op.create_unique_constraint(constraint, table, ["identity_key"])


def upgrade():
    for column in (
        sa.Column("engine_type", sa.String(80)),
        sa.Column("power_hp", sa.Integer()),
        sa.Column("torque_nm", sa.Integer()),
        sa.Column("transmission", sa.String(80)),
        sa.Column("drivetrain", sa.String(40)),
        sa.Column("body_type", sa.String(40)),
        sa.Column("body_style", sa.String(80)),
    ):
        op.add_column("vehicles", column)
    op.create_check_constraint(
        "ck_vehicles_power_hp_positive",
        "vehicles",
        "power_hp IS NULL OR power_hp > 0",
    )
    op.create_check_constraint(
        "ck_vehicles_torque_nm_positive",
        "vehicles",
        "torque_nm IS NULL OR torque_nm > 0",
    )

    for column in (
        sa.Column("ilsac_spec", sa.String(20)),
        sa.Column("package_volume_liters", sa.Numeric(6, 2)),
        sa.Column("package_volume_label", sa.String(40)),
        sa.Column("claimed_service_interval_km", sa.Integer()),
    ):
        op.add_column("engine_oils", column)
    op.create_index("ix_engine_oils_ilsac_spec", "engine_oils", ["ilsac_spec"])
    op.create_check_constraint(
        "ck_engine_oils_package_volume_liters_positive",
        "engine_oils",
        "package_volume_liters IS NULL OR package_volume_liters > 0",
    )
    op.create_check_constraint(
        "ck_engine_oils_claimed_service_interval_km_positive",
        "engine_oils",
        "claimed_service_interval_km IS NULL OR claimed_service_interval_km > 0",
    )

    vehicle_keys = _target_keys("vehicles", lambda row: _vehicle_key(row, True))
    oil_keys = _target_keys("engine_oils", lambda row: _oil_key(row, True))
    _apply_keys("vehicles", "uq_vehicles_identity_key", vehicle_keys)
    _apply_keys("engine_oils", "uq_engine_oils_identity_key", oil_keys)


def downgrade():
    vehicle_keys = _target_keys("vehicles", lambda row: _vehicle_key(row, False))
    oil_keys = _target_keys("engine_oils", lambda row: _oil_key(row, False))
    _apply_keys("vehicles", "uq_vehicles_identity_key", vehicle_keys)
    _apply_keys("engine_oils", "uq_engine_oils_identity_key", oil_keys)

    op.drop_constraint(
        "ck_engine_oils_claimed_service_interval_km_positive",
        "engine_oils",
        type_="check",
    )
    op.drop_constraint(
        "ck_engine_oils_package_volume_liters_positive",
        "engine_oils",
        type_="check",
    )
    op.drop_index("ix_engine_oils_ilsac_spec", table_name="engine_oils")
    for column in (
        "claimed_service_interval_km",
        "package_volume_label",
        "package_volume_liters",
        "ilsac_spec",
    ):
        op.drop_column("engine_oils", column)

    op.drop_constraint("ck_vehicles_torque_nm_positive", "vehicles", type_="check")
    op.drop_constraint("ck_vehicles_power_hp_positive", "vehicles", type_="check")
    for column in (
        "body_style",
        "body_type",
        "drivetrain",
        "transmission",
        "torque_nm",
        "power_hp",
        "engine_type",
    ):
        op.drop_column("vehicles", column)
