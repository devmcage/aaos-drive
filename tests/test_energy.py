"""Battery recovery, lossless storage and incremental upgrades, without Drive writes."""

import asyncio
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from . import bootstrap, ha_stub
from .fixtures import FakeDrive, day_document, fuel_day
from custom_components.aaos_drive.energy import BatteryPowerWindow, effective_telemetry, review_energy
from custom_components.aaos_drive.history import HistoryStore, sync_history
from custom_components.aaos_drive.measurements import car_sensor, dashboard_field
from custom_components.aaos_drive.model import InvalidExport, trip_summary
from custom_components.aaos_drive.repository import DriveRepository
from custom_components.aaos_drive.sensor import AAOSSensor


def zero_power_day(energy=0, source='vehicle_sensor', delta_wh=10):
    day = day_document('2026-10-04', 'dataset-a-2')
    trip = day['trips'][0]
    template = trip['telemetry'][0]
    trip.update(energyKwh=energy, energySource=source, vehicleType='ELECTRIC')
    trip['telemetry'] = [{**template, 'recordedAt': trip['startedAt'] + i * 1000,
                          'speedKph': 60, 'powerKw': 0, 'powerSource': 'vehicle_sensor',
                          'batteryEnergyWh': 50000 - delta_wh * i} for i in range(61)]
    return day


class EnergyTests(unittest.TestCase):
    def test_moving_all_zero_power_is_recovered_from_wh_not_percent(self):
        trip = zero_power_day()['trips'][0]
        original = copy.deepcopy(trip)
        trip['telemetry'][0]['batteryPercent'] = 1  # Not a source of inferred energy.
        review = review_energy(trip)
        self.assertEqual((review.energy, review.source, review.quality), (.6, 'derived_battery_energy', 'recovered'))
        effective = list(effective_telemetry(trip, review))
        self.assertTrue(all(p['powerKw'] is None for p in effective[:10]))
        self.assertEqual(effective[-1]['powerKw'], 36)
        self.assertEqual(effective[-1]['reportedPowerKw'], 0)
        self.assertEqual(effective[-1]['powerQuality'], 'estimated')
        self.assertEqual(trip['telemetry'][-1], original['telemetry'][-1])
        summary = trip_summary(trip, review)
        self.assertEqual(summary['efficiencyKwhPer100Km'], 50)
        self.assertEqual(summary['reportedEnergyKwh'], 0)

    def test_signed_battery_gain_is_negative_and_does_not_become_fuel(self):
        trip = zero_power_day(delta_wh=-10)['trips'][0]
        review = review_energy(trip)
        self.assertEqual(review.energy, -.6)
        self.assertEqual(list(effective_telemetry(trip, review))[-1]['powerKw'], -36)
        self.assertNotIn('fuelUsage', trip_summary(trip))

    def test_measured_nonzero_trip_and_true_zero_samples_are_preserved_without_evidence_scan(self):
        for energy in (1.5, -.3):
            with self.subTest(energy=energy):
                trip = zero_power_day(energy=energy)['trips'][0]
                trip['telemetry'][0]['powerKw'] = 311.638944
                trip['telemetry'][1]['powerKw'] = -97.948128
                with patch('custom_components.aaos_drive.energy.BatteryEvidence.add', side_effect=AssertionError('Unexpected scan')):
                    review = review_energy(trip)
                self.assertEqual(review.energy, energy)
                self.assertFalse(review.repair_power)
                self.assertEqual(list(effective_telemetry(trip, review)), trip['telemetry'])

    def test_real_zero_moving_or_stationary_is_not_misclassified(self):
        for speed in (0, 60):
            trip = zero_power_day(delta_wh=0)['trips'][0]
            for p in trip['telemetry']:
                p['speedKph'] = speed
            review = review_energy(trip)
            self.assertEqual(review.energy, 0)
            self.assertEqual(review.quality, 'measured')
            self.assertFalse(review.repair_power)

    def test_nonzero_power_prevents_zero_trip_false_positive(self):
        trip = zero_power_day()['trips'][0]
        trip['telemetry'][10]['powerKw'] = -.1
        self.assertFalse(review_energy(trip).repair_power)

    def test_missing_energy_and_new_unavailable_marker_can_recover(self):
        for energy, source in ((None, 'unknown'), (0, 'unknown'), (0, 'unavailable_energy'), (9, 'unavailable_energy')):
            trip = zero_power_day(energy, source)['trips'][0]
            if source == 'unknown':
                for p in trip['telemetry']:
                    p['powerKw'] = None
            self.assertEqual(review_energy(trip).energy, .6)
            self.assertEqual(review_energy(trip).quality, 'recovered')

    def test_bad_battery_evidence_is_unavailable_not_zero(self):
        mutations = {
            'missing': lambda t: t['telemetry'][30].update(batteryEnergyWh=None),
            'negative': lambda t: t['telemetry'][30].update(batteryEnergyWh=-1),
            'nonfinite': lambda t: t['telemetry'][30].update(batteryEnergyWh=float('nan')),
            'boolean': lambda t: t['telemetry'][30].update(batteryEnergyWh=True),
            'connected': lambda t: t['telemetry'][30].update(chargePortConnected=True),
            'charging': lambda t: t['telemetry'][30].update(chargeState=1),
            'reset': lambda t: t['telemetry'][30].update(batteryEnergyWh=1),
            'duplicate': lambda t: t['telemetry'][30].update(recordedAt=t['telemetry'][29]['recordedAt']),
            'out_of_order': lambda t: t['telemetry'][30].update(recordedAt=t['telemetry'][20]['recordedAt']),
            'gap': lambda t: t['telemetry'].__delitem__(slice(10, 30)),
            'endpoints': lambda t: t['telemetry'].__delitem__(slice(-12, None)),
        }
        for name, mutate in mutations.items():
            with self.subTest(reason=name):
                trip = zero_power_day()['trips'][0]
                mutate(trip)
                review = review_energy(trip)
                self.assertIsNone(review.energy)
                self.assertEqual(review.quality, 'unavailable')
                self.assertTrue(all(p['powerKw'] is None for p in effective_telemetry(trip, review)))
                self.assertIsNone(trip_summary(trip)['efficiencyKwhPer100Km'])

    def test_estimate_power_cap_does_not_cap_measured_power(self):
        trip = zero_power_day(delta_wh=80)['trips'][0]  # Under the step limit, above the 250 kW estimate cap.
        self.assertEqual(review_energy(trip).quality, 'unavailable')
        window = BatteryPowerWindow()
        self.assertTrue(all(window.add(p) is None for p in trip['telemetry']))

    def test_rolling_window_does_not_bridge_gaps_or_charge_connections(self):
        trip = zero_power_day()['trips'][0]
        window = BatteryPowerWindow()
        for p in trip['telemetry'][:11]:
            value = window.add(p)
        self.assertEqual(value, 36)
        self.assertIsNone(window.add(trip['telemetry'][40]))
        for p in trip['telemetry'][41:51]:
            value = window.add(p)
        self.assertEqual(value, 36)
        self.assertIsNone(window.add({**trip['telemetry'][51], 'chargePortConnected': True}))
        self.assertIsNone(window.add(trip['telemetry'][52]))

    def test_rolling_window_is_bounded_to_sixty_seconds(self):
        window = BatteryPowerWindow()
        for i in range(10000):
            window.add({'recordedAt': i * 1000, 'batteryEnergyWh': 200000-i})
        self.assertEqual(len(window.samples), 61)

    def test_original_derived_sources_remain_estimated_and_exact(self):
        for source in ('derived_battery_energy', 'mixed_vehicle_sensor_and_derived'):
            trip = zero_power_day(1.234, source)['trips'][0]
            self.assertEqual(review_energy(trip).quality, 'estimated')
            self.assertEqual(trip_summary(trip)['energyKwh'], 1.234)
            self.assertFalse(review_energy(trip).repair_power)

    def test_fuel_is_never_derived_from_battery_and_hybrid_keeps_fuel_exact(self):
        trip = zero_power_day()['trips'][0]
        trip.update(vehicleType='FUEL', energySource='unknown')
        self.assertIsNone(review_energy(trip).energy)
        self.assertFalse(review_energy(trip).repair_power)
        trip.update(vehicleType='HYBRID', fuelUsage=fuel_day()['trips'][0]['fuelUsage'])
        summary = trip_summary(trip)
        self.assertEqual(summary['energyKwh'], .6)
        self.assertEqual(summary['fuelUsage']['movingFuelLiters'], trip['fuelUsage']['movingFuelLiters'])
        self.assertEqual(summary['fuelUsage']['movingConsumptionLitersPer100Km'], 6)


class EnergyHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.history = HistoryStore(Path(temporary.name) / 'history.sqlite')
        self.history.initialize()
        self.drive = FakeDrive(uniform=True, include_history=False, latest_day=zero_power_day())
        self.repo = DriveRepository(self.drive, 'car', asyncio.to_thread)

    async def sync(self):
        snapshot = await self.repo.refresh()
        await sync_history(self.history, self.repo, snapshot, asyncio.to_thread)
        return snapshot

    async def test_lossless_original_effective_queries_live_sensor_and_statistics(self):
        snapshot = await self.sync()
        self.assertEqual(self.history.trip(), self.drive.day['trips'][0])
        self.assertEqual(self.history.summaries()[0]['energyKwh'], .6)
        choice = self.history.trip_index()['trips'][0]
        self.assertEqual(choice['energy_kwh'], .6)
        self.assertEqual(choice['energy_quality'], 'recovered')
        page = self.history.points('telemetry.powerKw')
        self.assertIsNone(page['points'][0]['value'])
        self.assertEqual(page['points'][-1]['value'], 36)
        self.assertEqual(page['points'][-1]['quality'], 'estimated')
        self.assertEqual(page['points'][-1]['reported_value'], 0)
        self.assertEqual(self.history.hourly()['telemetry.powerKw'][0]['mean'], 36)
        self.assertNotIn('telemetry.reportedPowerKw', self.history.hourly())
        self.assertNotIn('trip.reportedEnergyKwh', self.history.hourly())
        self.assertEqual(snapshot.values()['dataset.energyKwh'], .6)
        self.assertEqual(snapshot.values()['month.2026-10.energyKwh'], .6)
        coordinator = SimpleNamespace(data=snapshot, entry=SimpleNamespace(unique_id='car', entry_id='entry'))
        sensor = AAOSSensor(coordinator, 'telemetry.powerKw')
        self.assertEqual(sensor.native_value, 36)
        self.assertEqual(sensor.extra_state_attributes['power_quality'], 'estimated')
        self.assertEqual(sensor.extra_state_attributes['reported_power_kw'], 0)
        self.assertIn('cannot show precise peaks', sensor.extra_state_attributes['energy_description'])
        for key in ('telemetry.reportedPowerKw', 'telemetry.reportedPowerSource', 'telemetry.powerQuality'):
            self.assertFalse(car_sensor(key))
            self.assertFalse(dashboard_field(key))

    async def test_unavailable_excluded_from_statistics_and_consumption_totals(self):
        day = zero_power_day()
        day['trips'][0]['telemetry'][30]['batteryEnergyWh'] = None
        self.drive.publish(2, uniform=True, include_history=False, latest_day=day)
        snapshot = await self.sync()
        self.assertNotIn('telemetry.powerKw', self.history.fields_with_data())
        self.assertNotIn('telemetry.powerKw', self.history.hourly())
        self.assertNotIn('trip.energyKwh', self.history.hourly())
        self.assertIsNone(snapshot.values()['dataset.energyKwh'])
        self.assertIsNone(snapshot.values()['month.2026-10.energyKwh'])
        self.assertEqual(snapshot.values()['dataset.energyUnavailableTripCount'], 1)
        self.assertIsNone(snapshot.values()['telemetry.powerKw'])

    async def test_mixed_coverage_average_excludes_unknown_distance_as_well_as_energy(self):
        day = zero_power_day()
        missing = copy.deepcopy(day['trips'][0])
        missing['tripId'] = 'missing'
        missing['distanceKm'] = 500
        missing['telemetry'][30]['batteryEnergyWh'] = None
        day['trips'].append(missing)
        self.drive.publish(2, uniform=True, include_history=False, latest_day=day)
        snapshot = await self.sync()
        self.assertIsNone(snapshot.values()['dataset.energyKwh'])
        self.assertEqual(snapshot.values()['dataset.knownEnergyKwh'], .6)
        self.assertEqual(snapshot.values()['dataset.energyCoveredDistanceKm'], 1.2)
        self.assertEqual(snapshot.values()['dataset.efficiencyKwhPer100Km'], 50)

    async def test_processing_upgrade_repairs_local_rows_once_no_redownload_or_loss(self):
        snapshot = await self.sync()
        old_count = self.history.overview()['record_count']
        cursor = self.history.points('telemetry.powerKw', limit=2)['next_cursor']
        with self.history.connect() as db:
            self.history.put(db, 'processing_version', 2)
            self.history.put(db, 'generation_revision', snapshot.manifest_hash)
            db.execute('DELETE FROM trip_summaries')
            # Model the previous version's zero-valued history and summary.
            for row_id, data in db.execute("SELECT id,data FROM records WHERE kind='telemetry'"):
                sample = json.loads(data)
                sample.update(powerKw=0, powerSource='vehicle_sensor')
                for key in ('powerQuality', 'reportedPowerKw', 'reportedPowerSource'):
                    sample.pop(key, None)
                db.execute('UPDATE records SET data=? WHERE id=?', (json.dumps(sample), row_id))
        self.history.statistics_done({})
        self.drive.downloads.clear()
        self.history.initialize()
        with self.assertRaises(InvalidExport):
            self.history.points('telemetry.powerKw', limit=2, cursor={**cursor, 'generation_revision': snapshot.manifest_hash})
        await sync_history(self.history, self.repo, snapshot, asyncio.to_thread)
        self.assertEqual(self.drive.downloads, [])
        self.assertEqual(self.history.overview()['record_count'], old_count)
        self.assertEqual(self.history.trip(), self.drive.day['trips'][0])
        self.assertEqual(self.history.points('telemetry.powerKw')['points'][-1]['value'], 36)
        self.assertEqual(snapshot.values()['trip.energyQuality'], 'recovered')
        self.assertTrue(self.history.state()['statistics_pending'])
        self.history.statistics_done({})
        with patch('custom_components.aaos_drive.history.review_energy', side_effect=AssertionError('Repeated review')):
            self.history.initialize()
            await sync_history(self.history, self.repo, snapshot, asyncio.to_thread)
            self.history.trip_index()
            self.history.summaries()
        self.assertFalse(self.history.state()['statistics_pending'])
