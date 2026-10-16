"""AAOS Logging import constants."""

DOMAIN = "aaos_drive"
NAME = "AAOS Logging Drive"
READ_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
API_ROOT = "https://www.googleapis.com/drive/v3"
FOLDER_MIME = "application/vnd.google-apps.folder"
DEFAULT_SCAN_MINUTES = 15
DEFAULT_STALE_HOURS = 24
MAX_FILE_BYTES = 128 * 1024 * 1024
MAX_ZIP_BYTES = 512 * 1024 * 1024
HISTORY_PROCESSING_VERSION = 2


def readonly_grant(token: dict) -> bool:
    scopes = set(token.get("scope", "").split())
    return READ_SCOPE in scopes and not any(
        s.startswith("https://www.googleapis.com/auth/drive") and s != READ_SCOPE for s in scopes
    )

# Exact keys from AAOS Logging's TelemetryJsonContract (trip schema 17).
TELEMETRY_FIELDS = (
    "recordedAt", "vehicleType", "vehicleTypeSource", "fuelLevelLiters",
    "fuelCapacityLiters", "fuelLevelLow", "fuelDoorOpen", "fuelConsumptionLitersPer100Km",
    "speedKph", "acceleratorPercent", "brakePercent", "lateralG",
    "longitudinalG", "powerKw", "powerSource", "powerSignalDirection", "batteryEnergyWh", "turnSignalState",
    "steeringAngleDeg", "batteryPercent", "batteryTemperatureC",
    "vehicleOutsideTemperatureC", "chargePortConnected", "chargePortOpen", "chargeState",
    "tirePressureKpaLeftFront", "tirePressureKpaRightFront", "tirePressureKpaLeftRear",
    "tirePressureKpaRightRear", "brakeFluidLevelLow", "brakePadWearPercentLeftFront",
    "brakePadWearPercentRightFront", "brakePadWearPercentLeftRear",
    "brakePadWearPercentRightRear", "headlightsState", "highBeamLightsState",
    "fogLightsState", "frontFogLightsState", "rearFogLightsState", "hazardLightsState",
    "windshieldWipersState", "absActive", "tractionControlActive",
    "electronicStabilityControlState", "currentGear", "parkingBrakeOn",
    "parkingBrakeAutoApply", "regenerativeBrakingLevel", "evStoppingMode", "nightMode",
    "wheelTickResetCount", "wheelTickLeftFront", "wheelTickRightFront", "wheelTickRightRear",
    "wheelTickLeftRear", "seatOccupancyFrontLeft", "seatOccupancyFrontRight",
    "seatOccupancyRearLeft", "seatOccupancyRearRight", "engineRpm",
    "engineCoolantTemperatureC", "engineOilTemperatureC", "engineOilLevel",
    "engineOilPressureKpa", "forwardCollisionWarningState", "automaticEmergencyBrakingState",
    "laneDepartureWarningState", "laneKeepAssistState", "laneCenteringAssistState",
    "blindSpotWarningLeftState", "blindSpotWarningRightState", "cruiseControlState",
    "cruiseControlTargetSpeedKph", "adaptiveCruiseLeadDistanceM", "rangeKm", "gearSelection",
)
BINARY_FIELDS = frozenset({
    "chargePortConnected", "chargePortOpen", "brakeFluidLevelLow", "absActive",
    "tractionControlActive", "parkingBrakeOn", "parkingBrakeAutoApply", "nightMode",
    "fuelLevelLow", "fuelDoorOpen",
})
FUEL_USAGE_MEASUREMENTS = (
    "movingFuelLiters", "movingConsumptionLitersPer100Km", "coveredDistanceKm",
    "observedDistanceKm", "tripDistanceKm", "engineRunningSeconds", "engineObservedSeconds",
    "engineOffMovingSeconds", "coveragePercent",
)
FUEL_USAGE_FIELDS = (*FUEL_USAGE_MEASUREMENTS, "source", "includesStationaryFuel", "limitations")
TRIP_FIELDS = (
    "tripId", "localId", "startedAt", "endedAt", "storageUnitSystem", "distanceKm",
    "energyKwh", "energySource", "powerSignalDirection", "averageSpeedKph", "maxSpeedKph", "maxAccelerationG",
    "maxBrakingG", "maxLateralG", "startLat", "startLon", "endLat", "endLon", "routeKey",
    "durationSeconds", "efficiencyKwhPer100Km", "telemetryCount", "routePointCount",
    "weatherSampleCount",
    "vehicleType", "vehicleTypeSource", "powertrainSchemaVersion",
    *(f"fuelUsage.{key}" for key in FUEL_USAGE_FIELDS),
)
WEATHER_FIELDS = ("temperatureC", "windKph", "precipitationMm", "capturedAt", "latitude", "longitude")
