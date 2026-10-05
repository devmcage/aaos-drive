# AAOS Logging Drive — attributes and data reference

This document explains the data available in integration **0.4.2**, using AAOS Logging's Drive sync **V3** and trip schema **17**. It covers all **68 telemetry fields**, route/weather fields, trip measurements, vehicle specifications, export metadata and integration-added entity attributes. Installation and dashboard setup are described in [INSTALLATION.md](INSTALLATION.md).

The names below are the exact source/history keys. Home Assistant displays readable names, such as **Telemetry battery percent**, and assigns entity IDs that may vary between installations. Use the entity's `history_field` attribute to find its source key.

## On this page

- [How to interpret recorded data](#how-to-interpret-recorded-data)
- [Telemetry fields](#telemetry-fields)
- [Raw status and enum codes](#raw-status-and-enum-codes)
- [Weather and route fields](#weather-and-route-fields)
- [Trip measurements and complete trip records](#trip-measurements-and-complete-trip-records)
- [Home Assistant entity attributes](#home-assistant-entity-attributes)
- [Device details and diagnostic entities](#device-details-and-diagnostic-entities)
- [Vehicle metadata and specifications](#vehicle-metadata-and-specifications)
- [Catalog, period and export metadata](#catalog-period-and-export-metadata)
- [Actions and history results](#actions-and-history-results)
- [Examples of interpreting values](#examples-of-interpreting-values)

## How to interpret recorded data

### Current state, samples and statistics

| View | What its values represent | Appropriate use |
| --- | --- | --- |
| Car's sensor entities | Most recent sample from the latest imported trip. Its source time is in `recorded_at_unix_ms`. | See the last recorded state and use it in Home Assistant. It is not a live reading. |
| AAOS trip dashboard / `get_history` | Individual samples at their original timestamps, within the selected trip/date range. | Compare speed, battery, power and recorded states during trips. |
| Complete-trip action | Original trip JSON, including telemetry, route and weather arrays. | Inspect every exported value and its provenance. |
| Native History / Statistics graphs | Imported hourly means, minima and maxima for numeric measurements with recognized units, plus ordinary states received after installation. | Compare numeric trends over longer periods. An hourly point is not a single original sample. |
| Trip summaries / catalog / indexes | Per-trip measurements or totals for a source period/dataset. | Report trip distances, energy and trip counts without creating month-specific device sensors. |

Imported statistics use the arithmetic mean of valid samples in each original UTC hour. Missing values are ignored for numeric aggregation; no values are invented for hours without samples. Several trips in one hour can contribute to the same hourly series. A mean is sample-weighted, not time-weighted. Per-trip summary statistics are assigned to the trip's ending hour.

Raw original records remain in the local AAOS database independently of Recorder's ordinary state-history retention. Numeric entity state classes are `measurement`, not cumulative energy-meter state classes. Trip energy is a net amount for that trip; battery energy is a remaining quantity. Neither should be interpreted as a monotonically increasing lifetime consumption meter.

### Missing values and visibility

- `null` means no reading was exported at that timestamp. Unsupported vehicle properties, permission limitations and temporarily unavailable readings can all produce nulls.
- Home Assistant `unknown` corresponds to a missing/unusable current reading. The integration does not carry an older value forward to fill it.
- `unavailable` means the current refresh/entity is unavailable. A failed Drive refresh does not discard previously imported history.
- Numeric `0` and boolean `false` are valid recorded values. They are not missing data.
- An enum code such as `0` can have a named enum meaning of Unknown while still being an actual recorded code. It is different from a missing Home Assistant state.
- A field with no usable readings anywhere in the first full import defaults to hidden. Its entity remains enabled and its raw samples remain accessible. A later valid reading can automatically show it. Once visible, a temporarily missing latest reading does not hide it again; manual visibility choices are preserved after the initial default.

### Units, times and directions

The export uses metric storage units: km, km/h, kW, kWh, Wh, °C, kPa, degrees and the units specified in the tables. Vehicle dashboard display-unit preferences do not change those stored units.

Timestamp fields ending in `At`, and `recorded_at_unix_ms`, are Unix **milliseconds**, not seconds. Divide by 1,000 when converting with a function expecting Unix seconds. The trip dashboard displays local browser time; CSV also includes UTC time and the original milliseconds. Source period names use the export's `timeZone`; hourly statistics are grouped in UTC.

Left/right wheel and seat labels refer to the vehicle's left/right side. Front-left is not necessarily the driver's seat: that depends on the vehicle. GPS latitude is positive north and longitude positive east. Signed motion/steering values must be interpreted using their source convention; a sign does not universally encode left/right across every vehicle.

## Telemetry fields

Each `telemetry.*` value belongs to an original telemetry sample. There are **58 measured sensor fields**, **8 binary sensor fields**, and **2 timestamp/source metadata fields**. Tables label raw enums as **code**; they are categorical states, not physical quantities.

### Time, speed, pedals and motion

| Field | Value / unit | Meaning and interpretation |
| --- | --- | --- |
| `telemetry.recordedAt` | Unix ms; metadata | Time this sample was recorded by the logger. Use it to align readings, rather than the time Home Assistant downloaded them. No separate timestamp sensor is created. |
| `telemetry.speedKph` | Number; km/h | Vehicle speed exported by the logger. `0` is a recorded stopped reading. An hourly mean can include stops and multiple trips. |
| `telemetry.acceleratorPercent` | Number; % | Accelerator pedal compression/position reported through the vehicle property available to the app. Normally 0 means released and 100 full compression; alternate OEM property aliases are retained as reported. It is not an engine-power percentage. |
| `telemetry.brakePercent` | Number; % | Brake pedal compression/position. When only a pressed/not-pressed property is available, the logger can export 100/0, so two-valued readings do not prove the pedal was fully compressed. It is not regenerative-braking power. |
| `telemetry.lateralG` | Number; g | Sideways acceleration estimated by the logger's motion processing. Compare absolute magnitude for cornering intensity; retain the sign for the source's sideways direction. |
| `telemetry.longitudinalG` | Number; g | Forward/backward acceleration from the logger. Positive values contribute to acceleration peaks; negative values to braking peaks. `-0.2 g` is braking magnitude of about 0.2 g. |
| `telemetry.steeringAngleDeg` | Number; ° | Steering angle from the vehicle property. Magnitude describes steering displacement; confirm the source's sign convention before labeling left/right turns. |
| `telemetry.rangeKm` | Number; km | Estimated remaining driving range reported by the vehicle. It is not trip distance or an odometer and can change as the vehicle updates its estimate. |

### Battery, power and charging

| Field | Value / unit | Meaning and interpretation |
| --- | --- | --- |
| `telemetry.powerKw` | Number; kW | Instantaneous battery power in the logger's convention: positive consumption, negative energy flowing into the battery, including regeneration. Check `powerSource` to distinguish direct measurements from estimates. |
| `telemetry.powerSource` | Text; metadata | Origin of the power value. Codes are explained below. Exposed as the telemetry entity attribute `power_source` and retained in raw history; no separate power-source sensor is created. |
| `telemetry.batteryEnergyWh` | Number; Wh | Remaining traction-battery energy reported by the vehicle. Divide by 1,000 for kWh. It is not energy used since the previous trip. |
| `telemetry.batteryPercent` | Number; % | Battery percentage computed by the logger from remaining energy and available capacity. Current usable capacity is preferred; nominal capacity is a fallback. The percentage source itself is not exported in this telemetry contract. |
| `telemetry.batteryTemperatureC` | Number; °C | Battery temperature/average-temperature property when exposed to the app. Null does not imply a cold battery or a temperature fault. |
| `telemetry.chargePortConnected` | Boolean; binary sensor | True when the vehicle reports its charging connector connected; false means a recorded disconnected state. Connected does not necessarily mean charging. |
| `telemetry.chargePortOpen` | Boolean; binary sensor | True when the charge-port flap/door is reported open; false when closed. This is independent of connector connection and charge state. |
| `telemetry.chargeState` | Integer; code | EV charging state. The standard codes are shown in [Raw status and enum codes](#raw-status-and-enum-codes); null means no state reading. Trip logs do not constitute a complete continuous charging-session history. |

Power/energy source strings are defined by the logger:

| Source string | Interpretation |
| --- | --- |
| `vehicle_sensor` | Direct vehicle power readings contributed to the value/energy calculation. |
| `derived_battery_energy` | Power/energy was derived from changes in remaining battery energy. It is an estimate and can be coarse when that source updates infrequently. |
| `mixed_vehicle_sensor_and_derived` | A trip's accumulated energy involved both direct and derived data. This is mainly useful in `trip.energySource`. |
| `unknown` / null | Source not identified or no applicable value. Do not infer a direct measurement. |

### Tyre pressures and brake-pad wear

| Field | Value / unit | Meaning and interpretation |
| --- | --- | --- |
| `telemetry.tirePressureKpaLeftFront` | Number; kPa | Pressure reported for the front-left tyre. Compare with the vehicle's recommended pressure; 100 kPa equals 1 bar. |
| `telemetry.tirePressureKpaRightFront` | Number; kPa | Pressure reported for the front-right tyre. Compare like-for-like conditions such as temperature. |
| `telemetry.tirePressureKpaLeftRear` | Number; kPa | Pressure reported for the rear-left tyre. A null value means no available reading for that wheel. |
| `telemetry.tirePressureKpaRightRear` | Number; kPa | Pressure reported for the rear-right tyre. The integration preserves the exported value without inferring a warning threshold. |
| `telemetry.brakePadWearPercentLeftFront` | Number; % | Accumulated wear for the front-left brake pad: 0 means no wear, 100 maximum wear. |
| `telemetry.brakePadWearPercentRightFront` | Number; % | Accumulated wear for the front-right brake pad; increasing values mean more wear. |
| `telemetry.brakePadWearPercentLeftRear` | Number; % | Accumulated wear for the rear-left brake pad, not percentage of pad remaining. |
| `telemetry.brakePadWearPercentRightRear` | Number; % | Accumulated wear for the rear-right brake pad, not a brake-pedal position. |

Brake-pad wear follows the Android property's [wear-percentage definition](https://developer.android.com/reference/android/car/VehiclePropertyIds#BRAKE_PAD_WEAR_PERCENTAGE).

### Brakes and stability systems

| Field | Value / unit | Meaning and interpretation |
| --- | --- | --- |
| `telemetry.brakeFluidLevelLow` | Boolean; binary sensor | True means the vehicle reports low brake fluid; false means the low-level condition is not reported at that sample. Null is not a healthy-state confirmation. |
| `telemetry.absActive` | Boolean; binary sensor | Whether anti-lock braking intervention was active at the sample. False does not mean ABS is unsupported or switched off. |
| `telemetry.tractionControlActive` | Boolean; binary sensor | Whether traction-control intervention was active. Distinguish active intervention from the system being available/enabled. |
| `telemetry.electronicStabilityControlState` | Integer; code | Electronic stability-control status. Decode the applicable AAOS/OEM enum; do not treat every nonzero code as intervention. |
| `telemetry.parkingBrakeOn` | Boolean; binary sensor | True when the vehicle reports the parking brake engaged. This is distinct from Park gear. |
| `telemetry.parkingBrakeAutoApply` | Boolean; binary sensor | Recorded setting/state for automatic parking-brake application. True alone does not establish that the brake is currently engaged. |

### Lights, wipers and outside conditions

| Field | Value / unit | Meaning and interpretation |
| --- | --- | --- |
| `telemetry.turnSignalState` | Integer; code | Recorded indicator state, such as left/right/off according to its enum. It is not a boolean and is separate from hazard-light status. |
| `telemetry.headlightsState` | Integer; code | Headlight state reported by the vehicle. State and switch-position enums can differ; this field reads the state property. |
| `telemetry.highBeamLightsState` | Integer; code | High-beam state. Preserve and decode its code before treating it as on/off. |
| `telemetry.fogLightsState` | Integer; code | General fog-light state if the vehicle exposes that property. It may coexist with separate front/rear fields. |
| `telemetry.frontFogLightsState` | Integer; code | Front fog-light state. A vehicle without readable front fog-light data can export null. |
| `telemetry.rearFogLightsState` | Integer; code | Rear fog-light state, independently of the front field. |
| `telemetry.hazardLightsState` | Integer; code | Hazard-light state at the recorded time. It is not inferred from the two turn indicators. |
| `telemetry.windshieldWipersState` | Integer; code | Front-windscreen wiper state from the applicable window property. Codes may distinguish more than simple on/off. |
| `telemetry.nightMode` | Boolean; binary sensor | True when the vehicle's night-mode sensor reports low cabin light. It is not determined from the clock or sunrise. |
| `telemetry.vehicleOutsideTemperatureC` | Number; °C | Outside temperature read from the vehicle. This can differ from external weather data in `weather.temperatureC`. |

The low-light meaning of night mode is defined by Android's [NIGHT_MODE property](https://developer.android.com/reference/android/car/VehiclePropertyIds#NIGHT_MODE).

### Gears and EV driving modes

| Field | Value / unit | Meaning and interpretation |
| --- | --- | --- |
| `telemetry.currentGear` | Integer; code | Actual gear reported by the vehicle, distinct from the selected transmission position. Use VehicleGear/OEM semantics, not the code's numeric size. |
| `telemetry.gearSelection` | Integer; code | Gear-selection value used by the logger; selected gear is preferred, with current gear used as a fallback when selected gear is absent and current gear is not Unknown. It is not necessarily a sequential gear number. |
| `telemetry.regenerativeBrakingLevel` | Integer; code/level | Vehicle's regenerative-braking setting. It is not regeneration power or energy; interpretation and supported levels depend on the property/vehicle. |
| `telemetry.evStoppingMode` | Integer; code | EV stopping behavior setting, such as the vehicle's creep/roll/hold mode. Use the source enum before labeling a particular integer. |

### Wheel counters

| Field | Value / unit | Meaning and interpretation |
| --- | --- | --- |
| `telemetry.wheelTickResetCount` | Integer; counter | Reset/discontinuity marker for the wheel tick series. Do not compare counts across a change in this value. |
| `telemetry.wheelTickLeftFront` | Integer; ticks | Cumulative front-left wheel ticks. Compare changes within one reset interval, not the absolute value as kilometres. |
| `telemetry.wheelTickRightFront` | Integer; ticks | Cumulative front-right wheel ticks; forward/reverse movement can increase/decrease the count. |
| `telemetry.wheelTickRightRear` | Integer; ticks | Cumulative rear-right wheel ticks. It occupies the third wheel position in the source array. |
| `telemetry.wheelTickLeftRear` | Integer; ticks | Cumulative rear-left wheel ticks. It occupies the fourth wheel position in the source array. |

The logger exports counts and the reset marker, not the per-wheel micrometres-per-tick configuration needed to turn them into a calibrated distance. See Android's [WHEEL_TICK definition](https://developer.android.com/reference/android/car/VehiclePropertyIds#WHEEL_TICK). These unitless counters have raw history, rather than imported hourly measurement statistics. Very large integer counters can exceed browser chart precision; consult the original export when exact large-integer comparison is required.

### Seat occupancy

| Field | Value / unit | Meaning and interpretation |
| --- | --- | --- |
| `telemetry.seatOccupancyFrontLeft` | Integer; code | Occupancy classification for the front-left seat. It is not a passenger count or inferred seat-belt state. |
| `telemetry.seatOccupancyFrontRight` | Integer; code | Occupancy classification for the front-right seat, where available. |
| `telemetry.seatOccupancyRearLeft` | Integer; code | Occupancy classification for the rear-left seat. Null means no exported reading, not an empty seat. |
| `telemetry.seatOccupancyRearRight` | Integer; code | Occupancy classification for the rear-right seat. No rear-centre field is defined in this contract. |

### Engine readings

| Field | Value / unit | Meaning and interpretation |
| --- | --- | --- |
| `telemetry.engineRpm` | Number; rpm | Engine rotational speed. It may remain absent on a battery-electric vehicle. Zero can be a real stopped-engine reading. |
| `telemetry.engineCoolantTemperatureC` | Number; °C | Engine coolant temperature when reported. It is distinct from battery temperature. |
| `telemetry.engineOilTemperatureC` | Number; °C | Engine oil temperature. It need not equal coolant temperature. |
| `telemetry.engineOilLevel` | Integer; code | Oil-level category from the vehicle property, not a volume in litres or a percentage. |
| `telemetry.engineOilPressureKpa` | Number; kPa | Engine oil-pressure reading exported by the logger. Interpret with engine operating conditions; a missing value is not a pressure of zero. |

### Driver-assistance systems

All state fields in this section are **raw categorical codes**. A system's status can distinguish unavailable, disabled, enabled, active or warning conditions depending on its enum. Never equate an arbitrary positive integer with an intervention.

| Field | Value / unit | Meaning and interpretation |
| --- | --- | --- |
| `telemetry.forwardCollisionWarningState` | Integer; code | Forward collision-warning status at the sample. Decode to distinguish warning from ordinary availability. |
| `telemetry.automaticEmergencyBrakingState` | Integer; code | Automatic emergency-braking status. A recorded system state does not by itself establish that braking occurred. |
| `telemetry.laneDepartureWarningState` | Integer; code | Lane-departure warning status. Distinguish a warning from enabled/available states. |
| `telemetry.laneKeepAssistState` | Integer; code | Lane-keeping assist status. It is separate from lane-departure warning and lane-centering status. |
| `telemetry.laneCenteringAssistState` | Integer; code | Lane-centering assist status. Interpret through the applicable source enum. |
| `telemetry.blindSpotWarningLeftState` | Integer; code | Left-side blind-spot warning status, from the corresponding vehicle area. Null does not establish that the blind spot is clear. |
| `telemetry.blindSpotWarningRightState` | Integer; code | Right-side blind-spot warning status, independently of the left field. |
| `telemetry.cruiseControlState` | Integer; code | Cruise-control status, which can distinguish availability/activation states. It is not the target speed. |
| `telemetry.cruiseControlTargetSpeedKph` | Number; km/h | Cruise-control set/target speed. A stored target does not mean cruise control was active at the sample. |
| `telemetry.adaptiveCruiseLeadDistanceM` | Number; m | Reported measured distance to the adaptive-cruise lead vehicle. It is a physical distance, not a selected time-gap setting; the logger converts the source millimetres to metres. |

## Raw status and enum codes

The integration preserves dynamic enum integers and displays categorical graphs for them. A number can represent a mode, a state, a flag or a special status; it is not an ordinary magnitude. The code tables below apply to the standard Android definitions when the vehicle follows them. Unknown/new codes are retained rather than translated speculatively.

For other fields, use the corresponding property in the [Android VehiclePropertyIds reference](https://developer.android.com/reference/android/car/VehiclePropertyIds) and its linked enum, then confirm any OEM extensions for your vehicle. The integration's `value_encoding` attribute identifies many raw enums; its absence on a particular field does not turn that field into a physical measure.

### Standard gear values

| Code | Standard meaning |
| --- | --- |
| 0 | Unknown gear code |
| 1 | Neutral |
| 2 | Reverse |
| 4 | Park |
| 8 | Drive |
| 16, 32, 64, 128 | First, second, third, fourth gear |
| 256, 512, 1024, 2048, 4096 | Fifth, sixth, seventh, eighth, ninth gear |

`4` is Park, not fourth gear. Android notes that Park and Drive describe gear selection for automatic transmissions, rather than ordinary actual gear positions. See [VehicleGear](https://developer.android.com/reference/android/car/VehicleGear).

### Standard EV charge-state values

| Code | Standard meaning |
| --- | --- |
| 0 | Vehicle reports unknown charging state |
| 1 | Charging |
| 2 | Fully charged |
| 3 | Not charging |
| 4 | Charging error |

These definitions come from [EvChargeState](https://developer.android.com/reference/android/car/hardware/property/EvChargeState). A code of 0 is retained as a recorded enum, whereas a null is a missing reading. Interpret the vehicle's fully-charged status alongside its configured charging target.

## Weather and route fields

### Weather

Weather records are external observations recorded by the logger, rather than vehicle temperature sensors. The current logger uses nearby/cached Open-Meteo weather data. Observation timestamps can differ from vehicle-sample times; an observation reused during a trip can predate that trip.

| Field | Value / unit | Meaning and interpretation |
| --- | --- | --- |
| `weather.temperatureC` | Number; °C | External weather temperature associated with the observation location/time. Compare separately from `telemetry.vehicleOutsideTemperatureC`. |
| `weather.windKph` | Number; km/h | Weather-provider wind-speed value. It is not vehicle airspeed or travel speed. |
| `weather.precipitationMm` | Number; mm | Precipitation for the provider's observation interval. It is not accumulated rainfall over the entire trip; do not sum reused observations as independent rainfall totals. |
| `weather.capturedAt` | Unix ms; metadata | Timestamp of the weather observation. Use this to identify cached/reused conditions. It is not necessarily the time the app fetched the record. |
| `weather.latitude` | Number; geographic degrees | Observation/request location's latitude, where exported. It is distinct from the moving route's latitude. |
| `weather.longitude` | Number; geographic degrees | Observation/request location's longitude, where exported. |

The original `weatherSamples` array and optional trip-level `weather` summary are both retained. The integration selects the latest weather sample for current entities, falling back to the trip-level weather object if no sample array exists. If only that object exists, history uses its `capturedAt` where available, otherwise trip end/start as a fallback timestamp.

### Route

| Field | Value / unit | Meaning and interpretation |
| --- | --- | --- |
| `route.recordedAt` | Unix ms; metadata | Original recording time of a route point. Align coordinates through this time, not array order alone. |
| `route.latitude` | Number; geographic degrees | Vehicle position latitude; normally -90 to 90, positive north. |
| `route.longitude` | Number; geographic degrees | Vehicle position longitude; normally -180 to 180, positive east. |

Latitude/longitude have stable measured entities and raw trip-history fields. The integration does not assign them physical measurement units for imported Recorder statistics. Use the trip dashboard/route records for the original coordinates. The position tracker uses the most recently timestamped route point, falling back to the latest trip's ending coordinates when route points are absent.

## Trip measurements and complete trip records

`trip.*` keys identify values returned in historical summaries. They are not separate last-trip sensor entities on the car device. Use `list_trips`, `get_trip` or `get_history` with a trip field for reporting. `get_trip` returns the original field names without the `trip.` prefix.

| Field | Value / unit | Meaning and interpretation |
| --- | --- | --- |
| `trip.tripId` | Text | Stable exported trip identifier. Use it for selection and joining records; it is more reliable than a local database row number. |
| `trip.localId` | Integer | Logger's local row identifier. It is scoped to that logger database and is not a globally unique trip ID. |
| `trip.startedAt` | Unix ms | Trip start time recorded by the app. |
| `trip.endedAt` | Unix ms or null | Trip ending time. A missing end cannot supply a computed duration. |
| `trip.storageUnitSystem` | Text | Storage unit convention; this importer expects `metric`. Display preferences do not change it. |
| `trip.distanceKm` | Number; km | Saved total trip distance, chosen by the logger from available odometer/GPS/speed-derived distance. It is not an odometer value. |
| `trip.energyKwh` | Number; kWh | Net energy used over the trip; positive consumption, negative net energy gain. Regeneration offsets consumption. It is not lifetime usage. |
| `trip.energySource` | Text | Provenance of trip energy: direct vehicle readings, derived battery-energy changes, mixed sources or unknown; see the source-string table. |
| `trip.averageSpeedKph` | Number; km/h | Average speed saved by the logger. Its current calculation is the mean of collected speed samples, rather than necessarily `distance / duration`. |
| `trip.maxSpeedKph` | Number; km/h | Highest speed observed by the logger during the trip. Sample frequency limits which peaks can be captured. |
| `trip.maxAccelerationG` | Number; g | Largest positive longitudinal acceleration saved for the trip. A summary 0 can be the logger's initialized maximum; inspect raw samples to confirm measurement availability. |
| `trip.maxBrakingG` | Number; g | Largest braking magnitude, saved as a nonnegative number from negative longitudinal acceleration. It is not a signed braking sample. |
| `trip.maxLateralG` | Number; g | Largest absolute lateral acceleration. Direction is discarded in this maximum. |
| `trip.startLat` | Number; geographic degrees or null | Saved trip-start latitude, usually from the first route point. |
| `trip.startLon` | Number; geographic degrees or null | Saved trip-start longitude. |
| `trip.endLat` | Number; geographic degrees or null | Saved trip-end latitude. |
| `trip.endLon` | Number; geographic degrees or null | Saved trip-end longitude. |
| `trip.routeKey` | Text or null | Logger's route reference/key. It is not a Home Assistant map URL. |
| `trip.durationSeconds` | Number; s; derived | `(endedAt - startedAt) / 1000` when both timestamps are valid. Null otherwise. Includes time within the saved trip bounds, including stops. |
| `trip.efficiencyKwhPer100Km` | Number; kWh/100 km; derived | `energyKwh / distanceKm × 100` for positive distance. Lower positive values mean less net energy per distance; a negative value means net energy gain. Null for zero/invalid distance. |
| `trip.telemetryCount` | Integer; derived | Number of telemetry records in the original trip array, including records containing null fields. It is not the count of valid readings for one sensor. |
| `trip.routePointCount` | Integer; derived | Number of original route points. It can differ from telemetry count. |
| `trip.weatherSampleCount` | Integer; derived | Number of entries in `weatherSamples`. It does not count an optional standalone `weather` summary as another array sample. |

The last five fields are computed by the importer in summary/history results. They are not added to the original JSON returned by `get_trip`.

Complete original trip JSON additionally contains:

| Original key | Contents |
| --- | --- |
| `telemetry` | Array of all original timestamped telemetry objects, including all null fields and future exported keys. |
| `route` | Array of original latitude/longitude/time records. |
| `weatherSamples` | Array of weather observations with their own capture times. |
| `weather` | Optional trip-level weather summary or null. It is not another independent weather sample. |

For the current logger, a trip follows Park → leave Park → meaningful driving → confirmed return to Park. Brief manoeuvres may not qualify. Home Assistant imports the app's saved trips; it does not detect new trips itself. A source correction or deletion is applied when a complete replacement Drive generation is accepted.

## Home Assistant entity attributes

Open an entity under **Developer tools → States** to inspect its current state and attributes. These attributes describe the current imported snapshot; they are not arrays containing every historic reading.

| Attribute | Meaning and interpretation |
| --- | --- |
| `export_field` | Exact integration/source key, such as `telemetry.speedKph`. Some utility entities use synthetic keys: `position`, `dataset.stale`, `refresh`. |
| `history_field` | Key to use with `get_history` for a measured field. For the position/utility entities the synthetic key is not an imported sample series; use `route.latitude`, `route.longitude` or the relevant measured field instead. |
| `history_view` | Relative sidebar URL `/aaos-history`. Opens the integration's history interface. |
| `historical_statistic_id` | Numeric measurement's native statistic/entity ID for History/Statistics graph use. Null when no eligible measured statistic applies. Having an ID does not guarantee non-null source readings exist. |
| `external_historical_statistic_id` | Compatible external `aaos_drive:` statistic ID for eligible numeric series. Null for enums, booleans, timestamps and fields without recognized units. Trip-summary external statistics are discoverable separately without device entities. |
| `recorded_at_unix_ms` | Original telemetry time, weather capture time or route-point time, depending on the entity. Position overrides it with its selected point's time. Utility/diagnostic entities use the export generation time, not the last Drive-check time. |
| `generation_id` | Identifier of the accepted Drive export generation. Several polls can use the same generation; it is not a trip timestamp. |
| `trip_id` | Exported ID of the latest trip for telemetry/weather/route entities. The position and utility entities currently leave this attribute null. Historical sample responses carry each sample's actual trip ID. |
| `data_source` | Text identifying the source as `AAOS Logging Google Drive snapshot`. Values represent recorded exports, not a live car connection. |
| `power_source` | On telemetry entities, the latest telemetry sample's `powerSource`. It describes that sample's power provenance, even when inspecting another telemetry sensor. |
| `raw_value` | Added when the displayed entity value is converted, structured or truncated: preserves its original form. It is not attached to every ordinary scalar reading. |
| `value_encoding` | Added to many enum fields to state that they contain a raw AAOS property code with no inferred translation. See the enum interpretation section. |
| `location_source` | Position-tracker attribute identifying its location as `last synced trip`. It is not live GPS. |

Home Assistant also supplies standard attributes where applicable:

| Standard attribute | Interpretation |
| --- | --- |
| `friendly_name` | Current entity display name; it can be changed by the user. |
| `icon` | Entity icon where one is explicitly assigned, such as the cloud-refresh icon on the refresh button. It has no measurement meaning. |
| `unit_of_measurement` | Displayed sensor unit from the integration's mapping. Native statistics and raw-source units can differ for explicit conversions, such as ms to s. |
| `device_class` | Home Assistant interpretation, such as speed, battery, temperature or pressure. It does not create a value that the car failed to export. |
| `state_class` | `measurement` for eligible numeric measurements; absent for raw enums/booleans and unitless non-statistical fields. |
| `source_type` | Tracker reports GPS as its location source type. This does not make the position live. |
| `latitude`, `longitude` | Tracker's most recently selected valid position coordinates. |
| `gps_accuracy` | Tracker accuracy radius in metres. This integration exports no measured GPS accuracy, so Home Assistant's default is 0; do not interpret that as a guaranteed error-free position. |
| `tracking_type` | Position-based tracking, rather than a network connection status. |
| `in_zones` | Home Assistant zone IDs containing the last logged coordinates. Zone membership describes that recorded location, not the car's live whereabouts. |

Home Assistant derives the tracker's state as `home`, `not_home` or a zone name from the last logged coordinates. Its standard tracker attributes follow the [Home Assistant tracker implementation](https://raw.githubusercontent.com/home-assistant/core/2026.9.4/homeassistant/components/device_tracker/entity.py); available attributes can vary with the Home Assistant version.

Registry settings such as the entity ID, unique ID, hidden/enabled status and device association are separate from sample values. Changing visibility does not change stored history.

## Device details and diagnostic entities

| Item | Meaning |
| --- | --- |
| Device name | Configured car name from the catalog, falling back to the integration entry's name. |
| Manufacturer | Catalog vehicle make, falling back to AAOS Logging when missing. |
| Model | Catalog vehicle model, when exported. |
| Firmware/software display | `Drive V3 / trip schema <version>`. This identifies the data format, not the car's actual firmware version. |
| Device identity | Integration identity combines `vehicleId` and `datasetId`. It is not an inferred VIN. |
| Last logged position | Device tracker using the newest route point in the latest trip, or its ending coordinates if no route points exist. Missing/invalid coordinates make the tracker unavailable. |
| Logged telemetry stale | Diagnostic binary sensor: true if the latest telemetry recording time is missing or older than the configured stale threshold. A successful poll alone does not make it fresh. |
| Refresh Drive data | Button requesting a fresh read/import of already synced Drive data. Its state is Home Assistant's last button-press time, not a car recording time. It does not control the car or start an upload. |

## Vehicle metadata and specifications

These fields are available through `get_catalog` under `catalog.vehicle`. Metadata observed at each accepted export is also retained in history. They do not create static-specification device sensors. Prefixes below describe the vehicle object; historical flattened keys start with `vehicle.`.

### Vehicle identity and provenance

| Path | Meaning and interpretation |
| --- | --- |
| `vehicle.configuredName` | Car name configured in the logger. |
| `vehicle.source` | Describes vehicle metadata's source, currently Android Automotive OS VehiclePropertyIds. |
| `vehicle.identity.make` | Vehicle manufacturer/make if readable. |
| `vehicle.identity.model` | Vehicle model if readable. |
| `vehicle.identity.trim` | Model trim/variant if readable. |
| `vehicle.identity.modelYear` | Vehicle model year, not the export year. |
| `vehicle.readableStaticProperties` | Names of static properties successfully read by the logger. This is not a list of all working dynamic telemetry sensors. |

### Capacities, connectors, locations and display preferences

| Path under `vehicle.specifications` | Meaning and interpretation |
| --- | --- |
| `nominalEvBatteryCapacityWh` | Nominal/new battery capacity in Wh. It is not measured remaining battery energy or necessarily current usable capacity. |
| `nominalEvBatteryCapacityKwh` | Same nominal capacity divided by 1,000, in kWh. Do not add it to the Wh value. |
| `fuelCapacityMilliliters` | Nominal fuel capacity in mL, when reported. |
| `fuelCapacityLiters` | Same capacity divided by 1,000, in litres. It is not remaining fuel. |
| `fuelTypes` | List of supported fuel-type enum objects, not current fuel amount. |
| `evConnectorTypes` | List of supported charging-connector enum objects, not a connector's present connection state. |
| `evPortLocation` | Single charging-port location enum, where exposed. |
| `evPortLocations` | List of charging-port locations when multiple locations are exported. |
| `fuelDoorLocation` | Fuel-door location enum. |
| `driverSeat` | Seat/location enum describing the driver position. Use it rather than assuming front-left is the driver. |
| `vehicleSizeClasses` | Vehicle size-class enum list. It is a classification, not measured exterior dimensions. |
| `distanceDisplayUnit` | Vehicle's chosen distance-display unit enum. Exported trip distance still uses km. |
| `fuelVolumeDisplayUnit` | Chosen fuel-volume display unit enum; does not change stored capacity units. |
| `tirePressureDisplayUnit` | Chosen tyre-pressure display unit enum; exported readings still use kPa. |
| `evBatteryDisplayUnit` | Chosen EV battery display unit enum; does not alter stored Wh/% readings. |

Static enum objects contain `code` (original integer) and `name` (a name resolved by the logger, or null). Lists contain one such object per value. In flattened history, a non-null single object may appear as separate `.code` and `.name` fields, whereas a list remains a structured value. Preserve unknown codes and use a provided name when available; an empty list means no entries were exported, not that a capability is conclusively absent.

### Exterior dimensions

All values under `vehicle.specifications.exteriorDimensionsMm` are in **millimetres**. Null means the dimension was not available.

| Field | Meaning |
| --- | --- |
| `height` | Overall vehicle height. |
| `length` | Overall vehicle length. |
| `width` | Vehicle width excluding the separate including-mirrors measurement. |
| `widthIncludingMirrors` | Width including mirrors. |
| `wheelBase` | Distance between front and rear axle positions. |
| `frontTrackWidth` | Left-to-right front wheel track width. |
| `rearTrackWidth` | Left-to-right rear wheel track width. |
| `curbToCurbTurningDiameter` | Curb-to-curb turning-circle diameter, not turning radius. |

## Catalog, period and export metadata

`get_catalog` returns `{manifest, catalog}`. Metadata snapshots describe committed exports observed since installation; their timestamp is when that export was generated, not a reconstructed lifetime history of static metadata.

### Catalog fields

| Key under `catalog` | Meaning |
| --- | --- |
| `format` | Catalog document type, normally `aaos-triplog-generation-catalog`. |
| `formatVersion` | Drive catalog protocol version, currently 3. |
| `tripSchemaVersion` | Schema used by detailed trip records, currently 17. |
| `datasetId` | Identity of the logger dataset. |
| `vehicleId` | Vehicle identity used to associate this dataset with the car. |
| `historyRelationVersion` | Version of the logger's history/dataset relationship metadata, when present. |
| `mergedDatasetIds` | Dataset IDs recorded as part of merged/recovered history, when present. Does not change the current dataset identity. |
| `carName` | Configured car name for this export. |
| `vehicle` | Vehicle identity/specification object described above. |
| `timeZone` | Export's named time zone for calendar periods. |
| `generatedAt` | Export/catalog generation time in Unix ms. |
| `months` | List of calendar-month summaries and references to their detailed index/archive. |

### Month summaries and week/month indexes

Catalog `months[]` entries and index documents use these summary fields:

| Field | Unit / interpretation |
| --- | --- |
| `month` | Calendar label `YYYY-MM`, for a month entry/index. It is not an entity name. |
| `week` | ISO week label `YYYY-Www`, for a week index; ISO week-year can differ from calendar year near New Year. |
| `tripCount` | Number of saved trips assigned to the period. |
| `distanceKm` | Sum of those trips' saved distances. |
| `energyKwh` | Sum of net trip energies; not gross consumption without regeneration. |
| `drivingTimeMs` | Sum of saved trip end-minus-start times, in milliseconds. Divide by 1,000 for seconds; it includes in-trip stops. |
| `firstTripAt` | Earliest included trip's start, Unix ms or null for an empty period. |
| `lastTripAt` | Latest included trip's end/start fallback, Unix ms or null. |
| `artifact` | Catalog month entry's referenced month index or archive descriptor. |
| `days` | Index array of referenced day archives. |
| `weeks` | Month-index array of referenced week indexes. |
| `format`, `formatVersion`, `tripSchemaVersion`, `timeZone`, `generatedAt` | Index type/version and export metadata, with the same interpretation as the catalog equivalents. |

Monthly source buckets are based on trip start time in the export's time zone. A period's `drivingTimeMs` is saved elapsed trip time, rather than exclusively moving time. Historical flattened month fields use keys such as `month.YYYY-MM.distanceKm`; indexes use the source logical key within an `index.*` path. Use `get_history_fields` to discover their exact paths. These metadata paths are not month-specific device entities.

Read an index using its `logicalKey`, such as `week:YYYY-Www` or `month:YYYY-MM`, from the manifest. Only week/month index artifacts can be fetched through `get_index`; an older month's detailed data may be represented by a month archive instead. Detailed trips in that archive remain available through trip/history actions.

### Commit manifest

The manifest commits one consistent set of artifacts. These source keys are available under `manifest`; scalar commit values are also observed as `dataset.*` history metadata.

| Key | Meaning and interpretation |
| --- | --- |
| `format` | Commit type, `aaos-triplog-drive-generation`. |
| `formatVersion` | Commit protocol version, currently 3. |
| `datasetId`, `vehicleId` | Dataset/vehicle identity. The importer checks they remain consistent with the configured entry. |
| `generationId` | Identity of this committed export. |
| `generationSequence` | Increasing generation number used to select the latest commit. Not a trip count. |
| `previousGenerationId` | Referenced preceding generation ID or null. |
| `generatedAt` | Generation creation time, Unix ms. |
| `tripSchemaVersion` | Detailed trip schema version. |
| `timeZone` | Source calendar-period time zone. |
| `totalTripCount` | Number of detailed trips represented by the committed generation. The importer verifies this count. |
| `latestTripEndTimestamp` | Most recent trip end time, Unix ms or null when unavailable. |
| `snapshotSha256` | Logger's fingerprint of the overall source snapshot. It is different from each file's checksum. |
| `artifacts` | List of the committed artifact descriptors below. The complete list is returned through `get_catalog`; it is not duplicated as a scalar dataset history field. |

### Artifact descriptors

| Descriptor key | Meaning |
| --- | --- |
| `logicalKey` | Identifier used to select a manifest artifact, such as `catalog`, `day:YYYY-MM-DD`, `week:YYYY-Www`, `month:YYYY-MM` or `archive:YYYY-MM`. Shortened references in catalogs/indexes can omit this key. |
| `logicalType` | `catalog`, `day_archive`, `month_archive`, `week_index` or `month_index`. |
| `period` | Associated day/month/week label, or null for artifacts not scoped to a period. |
| `relativePath` | Artifact path relative to the Sync folder, normally starting `V3/Artifacts/`. |
| `mimeType` | Expected content type: JSON for metadata/indexes, ZIP for detailed archives. |
| `size` | Expected compressed/file byte size. It is not sample count. |
| `sha256` | Expected SHA-256 file digest used for content integrity. |
| `tripCount` | Number of trips described/contained by that artifact, according to its type. Do not sum counts across catalogs, indexes and detailed archives together; references overlap. |

## Actions and history results

All actions are under the `aaos_drive` domain and select one configured vehicle using `config_entry_id`. This is Home Assistant's integration-entry ID, not the logger's `vehicleId`, `datasetId` or a Drive folder ID. Select the entry through the Actions UI rather than guessing it.

| Action | Inputs besides `config_entry_id` | Result |
| --- | --- | --- |
| `get_history_fields` | None | Complete field inventory, history bounds, record/trip counts, accepted generation and statistics-pending flag. Includes metadata fields beyond those shown in the sensor-only trip dashboard. |
| `get_history` | Required `field`; optional `trip_id`, `start`, `end`, `limit`, `cursor` | Original timestamped values for that field. Empty/omitted trip selects all matching trips. Time bounds are inclusive Unix ms. Default limit 2,000; maximum 10,000 per response. |
| `get_trip` | Optional `trip_id`; blank selects latest | `generation_id` and complete original `trip` JSON, including the sample arrays. |
| `list_trips` | Optional `period`: `YYYY-MM` or `YYYY-MM-DD` | `generation_id` and trip summaries. A supplied period filters trip starts using the export's time zone. Blank returns all imported trips. |
| `get_catalog` | None | Complete current `manifest` and `catalog`. |
| `get_index` | Required `logical_key` | `generation_id` and complete requested week/month `index`. |

Full-history actions (`get_history`, `get_history_fields`, `get_trip`, `list_trips`) read local validated history and can work while Drive is temporarily unavailable. Catalog/index actions require a successful current refresh. None of these actions writes to Google Drive.

### History field inventory

`get_history_fields` returns:

| Key | Meaning |
| --- | --- |
| `generation_id` | Current complete imported generation. |
| `start`, `end` | Earliest/latest timestamps across visible stored records, including metadata snapshots; Unix ms or null when no records exist. |
| `trip_count` | Number of active imported trips. |
| `record_count` | Number of stored sample/summary/metadata records in the visible history, not the number of scalar readings. |
| `fields` | Array of field descriptions below. |
| `statistics_pending` | Whether committed history is waiting for a statistics reconciliation checkpoint. False does not guarantee every field has data or recently recorded hours are already eligible for native import. |

Each field description contains `field` (exact key), `name` (readable label), `unit` (raw-history display unit), `timestamp_value` (whether its value is a timestamp), `statistic_unit` (eligible aggregate unit or null), `statistic_factor` (conversion applied to statistics) and `categorical` (boolean/enum classification). Raw `drivingTimeMs` values remain milliseconds while their statistic unit is seconds with factor 0.001.

The sidebar's authenticated field response additionally includes a per-field `statistic_id` and `external_statistic_id`, plus `drive_available` and any `statistics_error`. Its field selector is restricted to measured telemetry/weather/route fields. Actions expose the fuller inventory.

### Timestamped history response

| Key | Meaning |
| --- | --- |
| `generation_id` | Generation for this query/page. |
| `field` | Requested field key. |
| `trip_id` | Requested trip filter, or null for an all-trip query. |
| `points` | Array of records containing the original value and source identifiers. |
| `next_cursor` | Continuation object, or null when all matching records have been returned. |

The response also includes the field-description keys explained above: `name`, `unit`, `timestamp_value`, `statistic_unit`, `statistic_factor` and `categorical`. Each point contains `time` (Unix ms), `value` (original JSON value, including null), `trip_id` (source trip or null for metadata) and `sample_index` (array position). The record category is identified by the requested field's prefix. Repeated timestamps are separate records; use field, trip and sample index to distinguish them.

Follow `next_cursor` with the same field, trip and bounds to retrieve all pages. Cursors belong to that query and accepted generation; restart if a new generation invalidates them. Do not interpret the first page as the entire trip.

The dashboard's trip selector uses a compact trip index with `trip_id`, `started_at`, `ended_at`, `sample_start`, `sample_end`, `distance_km`, `energy_kwh`, `duration_seconds`, `telemetry_count`, `route_count` and `weather_count`. Start/end/sample bounds are Unix ms. Sample bounds can extend beyond the trip when cached observations have older timestamps; the selected-trip chart uses the trip's exact start/end bounds. Trip choices are separate from the field's sample records.

### CSV export

The selected primary-field export has columns `recorded_at_utc`, `recorded_at_unix_ms`, `field`, `value_json`, `unit`, `trip_id` and `sample_index`. It fetches all matching pages even when only some are loaded in the graph. For boolean values, `false` remains false; a null remains null. Each configured secondary chart has its own history, but the CSV button exports the currently selected primary field.

## Examples of interpreting values

| Example | Interpretation |
| --- | --- |
| Battery energy 27,336 Wh | 27.336 kWh remaining in the traction battery at that sample. It is not 27.336 kWh consumed by the trip. |
| Power -12 kW | Battery energy is flowing inward at that instant in the logger's convention. Check the source string and trip context; it can be regeneration or charging. |
| Trip distance 20 km and net energy 3 kWh | Derived trip efficiency is `3 / 20 × 100 = 15 kWh/100 km`. |
| Brake-pad wear 30% | About 30% accumulated wear according to the source property, not 30% pad remaining. |
| Gear-selection code 4 | Standard Android Park code, if the source follows VehicleGear. |
| A sensor is unknown today but has earlier samples | The latest reading is missing. Earlier readings are retained and the entity remains visible because it has history. |
| Accelerator null throughout a trip | No accelerator readings were provided. Drawing a line at 0% would invent data. |
| Latest speed 0 km/h with a varying earlier chart | The last recorded sample is stopped; it does not describe the speed throughout the trip. |
| Stale diagnostic on after a successful refresh | The last car recording is old, even though Home Assistant successfully checked Drive. |

The source contract can gain new keys in later exports. The importer retains original scalar fields and full trip records rather than silently dropping them. Discover additional paths through `get_history_fields` and the original `get_trip`/`get_catalog` results; this reference describes the fields defined for the versions stated at the top.
