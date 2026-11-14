"""Map library quantities to Home Assistant device classes."""

from aaos_logging_drive.measurements import (
    TIMESTAMPS, car_sensor, dashboard_field, label, series_info,
    measurement as describe_measurement,
)

_DEVICE_CLASSES = {
    "timestamp": "timestamp", "stored_volume": "volume_storage",
    "charge_percentage": "battery", "volume": "volume", "duration": "duration",
    "speed": "speed", "distance": "distance", "energy": "energy", "power": "power",
    "temperature": "temperature", "pressure": "pressure", "precipitation": "precipitation",
}


def measurement(field):
    unit, quantity, factor = describe_measurement(field)
    return unit, _DEVICE_CLASSES.get(quantity), factor
