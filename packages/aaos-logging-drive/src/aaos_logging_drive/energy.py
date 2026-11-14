"""Conservative battery-energy recovery, shared in behaviour with both Android apps.

Never mutates an export. Trip energy uses qualified endpoints, not integration
of the smoothed power estimate. Fuel use is never inferred from battery depletion.
"""

from collections import deque
from dataclasses import dataclass
import math

DERIVED = {"derived_battery_energy", "mixed_vehicle_sensor_and_derived"}
KNOWN = DERIVED | {"vehicle_sensor"}
REVIEW_VERSION = 1
QUALITY_FIELDS = {"reportedPowerKw", "reportedPowerSource", "powerQuality"}


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def charging(point):
    return point.get("chargePortConnected") is True or point.get("chargeState") == 1


class BatteryEvidence:
    def __init__(self):
        self.first_at = self.last_at = None
        self.first_wh = self.last_wh = None
        self.previous_at = self.previous_wh = self.observation_at = None
        self.invalid = False
        self.changes = self.moving_ms = self.power_count = self.nonzero_count = 0

    def add(self, point):
        at, power, wh, speed = (point.get(k) for k in ("recordedAt", "powerKw", "batteryEnergyWh", "speedKph"))
        if finite(power):
            self.power_count += 1
            self.nonzero_count += abs(power) > .01
        if self.observation_at is not None and finite(speed) and abs(speed) >= 3 and 1 <= at - self.observation_at <= 15000:
            self.moving_ms += at - self.observation_at
        self.observation_at = at
        if charging(point) or not finite(wh) or wh < 0:
            self.invalid = True
            return
        if self.previous_at is None:
            self.first_at, self.first_wh = at, wh
        else:
            elapsed = at - self.previous_at
            delta = abs(wh - self.previous_wh)
            if not 1 <= elapsed <= 15000 or delta > max(50, max(0, elapsed) * 500 / 3600):
                self.invalid = True
            self.changes += delta >= 1
        self.previous_at, self.previous_wh = at, wh
        self.last_at, self.last_wh = at, wh

    def battery_kwh(self, start, end):
        if (self.invalid or self.first_wh is None or not finite(end) or end <= start or
                self.last_at - self.first_at < 10000 or abs(self.first_at - start) > 10000 or abs(end - self.last_at) > 10000):
            return None
        energy = (self.first_wh - self.last_wh) / 1000
        return energy if abs(energy) * 3600000 / (end - start) <= 250 else None

    def suspect_zero(self, start, end):
        if not finite(end) or end - start < 30000 or self.nonzero_count or self.power_count < 4 or self.moving_ms < 10000:
            return False
        contradiction = (self.changes >= 3 and self.first_wh is not None and self.last_wh is not None and
                         abs(self.first_wh - self.last_wh) >= 20)
        return contradiction or self.battery_kwh(start, end) is None


class BatteryPowerWindow:
    def __init__(self):
        self.samples = deque()

    def add(self, point):
        at, wh = point.get("recordedAt"), point.get("batteryEnergyWh")
        if charging(point) or not finite(wh) or wh < 0:
            self.samples.clear()
            return None
        if self.samples:
            last_at, last_wh = self.samples[-1]
            elapsed = at - last_at
            if not 1 <= elapsed <= 15000 or abs(wh - last_wh) > max(50, max(0, elapsed) * 500 / 3600):
                self.samples.clear()
        self.samples.append((at, wh))
        while len(self.samples) > 1 and at - self.samples[0][0] > 60000:
            self.samples.popleft()
        first_at, first_wh = self.samples[0]
        if at - first_at < 10000:
            return None
        power = (first_wh - wh) * 3600 / (at - first_at)
        return power if finite(power) and abs(power) <= 250 else None


@dataclass(frozen=True)
class EnergyReview:
    energy: float | None
    source: str | None
    quality: str
    repair_power: bool = False


def review_energy(trip):
    energy, source = trip.get("energyKwh"), trip.get("energySource")
    if trip.get("vehicleType") == "FUEL":
        usable = finite(energy) and source in KNOWN
        return EnergyReview(energy if usable else None, source, "estimated" if usable and source in DERIVED else "measured" if usable else "unavailable")
    # Normal measured history needs no battery scan and has no artificial power cap.
    if finite(energy) and energy != 0 and source != "unavailable_energy":
        return EnergyReview(energy, source, "estimated" if source in DERIVED else "measured")
    evidence = BatteryEvidence()
    for point in trip.get("telemetry", []):
        evidence.add(point)
    start, end = trip["startedAt"], trip.get("endedAt")
    suspect = energy == 0 and evidence.suspect_zero(start, end)
    missing = (source == "unavailable_energy" or not finite(energy) or
               energy == 0 and evidence.power_count == 0 and source not in KNOWN)
    if suspect or missing:
        recovered = evidence.battery_kwh(start, end)
        if recovered is not None:
            return EnergyReview(recovered, "derived_battery_energy", "recovered", True)
        return EnergyReview(None, "unavailable_energy", "unavailable", True)
    return EnergyReview(energy, source, "estimated" if source in DERIVED else "measured")


def effective_telemetry(trip, review):
    """One bounded rolling window per affected trip; all other readings stay exact."""
    window = BatteryPowerWindow()
    for point in trip.get("telemetry", []):
        if not review.repair_power:
            yield point
            continue
        power = window.add(point) if review.quality == "recovered" else None
        yield {**point, "reportedPowerKw": point.get("powerKw"), "reportedPowerSource": point.get("powerSource"),
               "powerKw": power, "powerSource": review.source,
               "powerQuality": "estimated" if power is not None else "unavailable"}


def energy_description(quality):
    if quality in {"recovered", "estimated"}:
        return "Estimated net battery energy, including regeneration and auxiliaries. Smoothed power cannot show precise peaks. Hybrid fuel use is separate."
    if quality == "unavailable":
        return "Battery consumption unavailable: insufficient reliable energy readings; excluded from consumption averages."
    return "Vehicle-measured battery energy."
