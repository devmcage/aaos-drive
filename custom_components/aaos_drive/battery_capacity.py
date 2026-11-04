"""Paired, timestamped usable-capacity estimate; never a certified SoH sensor."""

from math import isfinite

FIELDS = frozenset({"batteryCurrentCapacityWh", "batteryNominalCapacityWh", "batteryCapacityRetentionPercent"})
NOTICE = ("Estimated battery capacity retention, not verified battery state of health. "
          "Current usable capacity / nominal usable capacity when new × 100. "
          "Temperature and battery-management estimates affect this value; it does not measure permanent degradation. "
          "Values above 100% are not capped. Missing capacities are not inferred from charge level, range or remaining energy.")


def positive(value):
    try:
        return value if type(value) in (int, float) and isfinite(value) and value > 0 else None
    except OverflowError:
        return None


def capacity_telemetry(point):
    """Return a derived view, without modifying the original exported trip."""
    result = dict(point)
    current = positive(point.get("batteryCurrentCapacityWh"))
    nominal = positive(point.get("batteryNominalCapacityWh"))
    ratio = current / nominal * 100 if current is not None and nominal is not None else None
    result.update(batteryCurrentCapacityWh=current, batteryNominalCapacityWh=nominal,
                  batteryCapacityRetentionPercent=positive(ratio))
    return result
