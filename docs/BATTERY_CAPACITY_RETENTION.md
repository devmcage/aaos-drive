# Estimated battery capacity retention

After installing this integration update, restart/reload the integration and refresh the dashboard browser cache. Install the updated AAOS Logging car app, record a trip and complete Drive synchronization. Both vehicle capacity properties must be available; older recordings cannot supply missing historical capacities.

New recorded telemetry sensors:

- Battery current usable capacity (`telemetry.batteryCurrentCapacityWh`, Wh).
- Battery nominal usable capacity (`telemetry.batteryNominalCapacityWh`, Wh).
- Estimated battery capacity retention (`telemetry.batteryCapacityRetentionPercent`, %).

These use the existing car-specific entity identity, recorded timestamps, dashboard history, statistics and CSV paths. The percentage is calculated from finite positive capacities in the **same sample**. Missing/invalid readings remain unavailable, and values above 100% are not capped. A declared upstream percentage is not trusted independently of the pair. No estimate is reconstructed from charge level, remaining energy, range, static catalog metadata or older samples.

This is **not verified battery state of health**, permanent degradation or a warranty assessment. Temperature and battery-management estimates can change it. The percentage has no battery-charge device class. Sensor attributes explicitly identify the estimate, source capacities, battery temperature, recorded time and `is_verified_state_of_health: false`. The history chart includes the limitation text.

The processing-version upgrade recalculates local derived history once from the retained original exports, without Drive redownloads. Original trip JSON remains unchanged. Existing recordings without capacity data remain readable and the new unsupported entities follow existing unavailable/visibility rules. The integration remains read-only toward Google Drive. Drive values are the last recorded/synced observations, not live car measurements.

Portable verification includes source-field parity against the adjacent car exporter, real car-generated backup input, sensor metadata/units, timestamps and gaps, invalid and over-100% cases, local migration and original-trip preservation. A running Home Assistant instance and physical vehicle still need deployment validation.
