"""Shared names and units for current entities and historical series."""

import re
from .const import BINARY_FIELDS

TIMESTAMPS = {"recordedAt", "startedAt", "endedAt", "capturedAt", "generatedAt", "firstTripAt", "lastTripAt", "lastChecked"}


def car_sensor(key):
    """Measured fields have stable entities; timestamps and summaries are attributes/data."""
    group, _, field = key.partition(".")
    return group in {"telemetry", "weather", "route"} and field not in TIMESTAMPS and field != "powerSource"


def label(key):
    group, _, field = key.partition(".")
    field = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", field).replace(".", " ")
    prefix = {"telemetry": "Telemetry", "trip": "Trip", "weather": "Weather", "route": "Route", "vehicle": "Vehicle", "dataset": "Dataset", "month": "Month", "index": "Index"}.get(group, group)
    return f"{prefix} {field.lower()}"


def measurement(field):
    if field in TIMESTAMPS:
        return None, "timestamp", 1
    if field == "efficiencyKwhPer100Km":
        return "kWh/100 km", None, 1
    if field == "drivingTimeMs":
        return "s", "duration", 0.001
    if field == "durationSeconds":
        return "s", "duration", 1
    if field.endswith("Kph"):
        return "km/h", "speed", 1
    if field.endswith("Km"):
        return "km", "distance", 1
    if field.endswith("Kwh"):
        return "kWh", "energy", 1
    if field.endswith("Wh"):
        return "Wh", "energy", 1
    if field.endswith("Kw"):
        return "kW", "power", 1
    if field.endswith("Percent") or "Percent" in field:
        return "%", "battery" if field == "batteryPercent" else None, 1
    if "TemperatureC" in field or field == "temperatureC":
        return "°C", "temperature", 1
    if "PressureKpa" in field:
        return "kPa", "pressure", 1
    if field == "precipitationMm":
        return "mm", "precipitation", 1
    if field.endswith("Deg"):
        return "°", None, 1
    if field == "adaptiveCruiseLeadDistanceM":
        return "m", "distance", 1
    if field in {"lateralG", "longitudinalG", "maxAccelerationG", "maxBrakingG", "maxLateralG"}:
        return "g", None, 1
    if field == "engineRpm":
        return "rpm", None, 1
    if field == "fuelCapacityLiters":
        return "L", "volume", 1
    if field == "fuelCapacityMilliliters":
        return "mL", "volume", 1
    return None, None, 1


def series_info(key):
    field = key.rsplit(".", 1)[-1]
    unit, device_class, factor = measurement(field)
    if key.startswith("vehicle.specifications.exteriorDimensionsMm."):
        unit = "mm"
    return {"field": key, "name": label(key), "unit": "ms" if factor == 0.001 else unit,
            "timestamp_value": device_class == "timestamp", "statistic_unit": unit,
            "statistic_factor": factor, "categorical": field in BINARY_FIELDS or field.endswith("State")
            or field.startswith("seatOccupancy") or field in {"currentGear", "gearSelection", "turnSignalState", "engineOilLevel", "regenerativeBrakingLevel", "evStoppingMode"}}
