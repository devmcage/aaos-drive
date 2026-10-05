/* Exercise chart queries/paging without requiring a Home Assistant installation. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const classes = new Map();
const context = vm.createContext({
  HTMLElement: class {}, window: {customCards: []},
  customElements: {get: key => classes.get(key), define: (key, cls) => classes.set(key, cls)},
  Date, Map, Set, Object, Promise, console,
});
vm.runInContext(fs.readFileSync("custom_components/aaos_drive/www/history.js", "utf8"), context);
const Card = classes.get("aaos-history-card");
function card() {
  const target = Object.create(Card.prototype);
  const controls = {
    vehicle: {value: "car"}, field: {value: "telemetry.speedKph"}, trip: {value: ""},
    from: {value: "2026-10-04T13:14"}, through: {value: "2026-10-04T13:23"},
    more: {}, csv: {},
  };
  target.$ = key => controls[key];
  target.status = () => {};
  target.render = () => {};
  target.request = 0;
  target.samples = [];
  return target;
}
async function run() {
  const target = card();
  const all = target.query();
  assert.equal(all.trip_id, undefined); // All-trip queries must work before selecting a trip.
  target.$("trip").value = "trip-a";
  target.tripSelection = {trip_id: "trip-a", from: target.$("from").value,
    through: target.$("through").value, start: 1791112467123, end: 1791112976456};
  assert.equal(target.query().start, target.tripSelection.start);
  assert.equal(target.query().end, target.tripSelection.end);
  target.$("from").value = "2026-10-04T13:15";
  assert.equal(target.query().start, new Date("2026-10-04T13:15").getTime());

  target.config = {fields: ["telemetry.speedKph", "telemetry.powerKw", "telemetry.batteryPercent"]};
  target.info = {drive_available: true, fields: target.config.fields.map(field => ({field}))};
  const calls = [];
  target.call = async (type, query) => {
    calls.push(query);
    return {field: query.field, generation_id: "g1", points: [{value: query.cursor ? 2 : 1}],
      next_cursor: query.cursor ? null : {page: 2}};
  };
  await target.loadPoints();
  assert.equal(calls.length, 3);
  assert.ok(calls.every(query => query.trip_id === "trip-a"));
  assert.equal(target.moreAvailable, true);
  // Editing controls must not change the query while paging an existing selection.
  target.$("trip").value = "trip-b";
  await target.loadPoints(true);
  assert.equal(calls.length, 6);
  assert.ok(calls.every(query => query.trip_id === "trip-a"));
  assert.ok(Object.values(target.series).every(series => series.points.length === 2));
  assert.equal(target.moreAvailable, false);
  console.log("Dashboard checks passed: initial range, exact trip bounds, edited bounds, and shared chart pagination.");
}
run().catch(error => {console.error(error);process.exitCode = 1;});
