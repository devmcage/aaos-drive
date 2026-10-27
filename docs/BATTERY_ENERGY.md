# Battery energy reliability

Version 0.4.7 applies the battery-energy safeguards used by the AAOS Logging
car and Companion apps. This also repairs eligible historical recordings
locally. The Google Drive connection stays read-only.

## What changes

- Valid measured trip energy and power stay exact, including negative regeneration,
  true zero readings and measured peaks above 250 kW.
- Existing `derived_battery_energy` and `mixed_vehicle_sensor_and_derived` sources
  remain labelled as estimates. The new `unavailable_energy` source means missing
  battery consumption, even if its legacy numeric slot contains zero.
- A moving trip with all-zero reported power can qualify for recovery when
  changing battery energy contradicts the zero signal. Net energy comes from
  the difference between qualified first/last battery readings in Wh. Battery
  percentage, tank-level drops and nominal battery capacity are not used.
- Without reliable evidence, energy and consumption are unavailable and omitted
  from numeric statistics and consumption averages. Missing consumption is never
  presented as an excellent zero-consumption trip.
- Fuel and battery energy stay separate. No fuel use is inferred from battery
  depletion. Existing fuel estimates and coverage are preserved for hybrids.

## Qualification and limits

Recovery requires finite, nonnegative battery Wh readings throughout the trip,
strictly increasing timestamps no more than 15 seconds apart, and no charging
connection or active charging state. Endpoints must be within 10 seconds of the
trip boundaries and span at least 10 seconds. Counter resets and implausible
steps are rejected: a step may not exceed the greater of 50 Wh or the energy
equivalent of 500 kW over the sample interval. The absolute average estimate
may not exceed 250 kW. These limits apply to estimates, never measured peaks.

The all-zero detector requires at least four finite power readings, no absolute
power above 0.01 kW, a trip of at least 30 seconds, and at least 10 seconds of
adjacent moving observations at 3 km/h or above. Contradictory battery evidence
requires three changes of at least 1 Wh and at least 20 Wh net change. An all-zero
signal without qualified battery evidence is unavailable when those movement
conditions are met. A supported, qualified true zero remains zero.

Recovered power is a signed rolling battery estimate over 10–60 seconds.
The initial warm-up stays unavailable. Missing values, charging, timestamp gaps,
resets and implausible steps reset the window. Separate trips never share a
window. It includes auxiliaries and regeneration, but cannot reconstruct precise
power peaks, coasting or pedal behaviour. Trip energy uses the endpoint difference,
not integration of the smoothed power curve.

## Display and provenance

The dashboard labels estimated trip energy and explains smoothed power beneath
affected graphs. Power sensor attributes include `power_quality`,
`energy_description`, and, when repaired locally, `reported_power_kw` and
`reported_power_source`. History point results and CSV exports carry `quality`
and `source`; repaired power additionally carries the original reported value
and source. These metadata fields do not create extra car sensors or statistics.

Trip summaries expose `energyQuality` (`measured`, `estimated`, `recovered`,
`unavailable`), `energyReviewVersion`, `energyDescription`, `reportedEnergyKwh`
and `reportedEnergySource`. Energy and efficiency are null when unusable.

Current snapshot dataset/month values include energy recorded, unavailable and
estimated trip counts. When a period contains locally recovered/unavailable
energy, its energy total is null if coverage is incomplete. `knownEnergyKwh`
and `energyCoveredDistanceKm` describe the usable portion; its consumption
average divides that energy by the distance of those same usable trips.
Unaffected catalog totals remain exact. Raw catalog/index actions and their
historical metadata series continue to describe the original export; use the
reviewed trip summaries for recovered consumption reporting.

## Upgrading and privacy

The local SQLite processing version advances from 2 to 3. On the first restart,
cached originals are reviewed one trip at a time in a transaction. Summaries and
affected query rows are rebuilt without redownloading archives or changing raw
recordings. Sample identities/timestamps, artifact hashes, configuration and
vehicle selection are retained. Query cursors from an older processing version
must be restarted. Later unchanged-generation polls reuse persisted reviews.

Home Assistant's existing statistics reconciliation replaces corrected hourly
values and removes obsolete zero-valued hours owned by this integration. Other
vehicles and unrelated entities are untouched. No new network requests or external
services are added. The complete-trip action still returns the exact original
recording, and the car and Companion files in Drive are never modified.
