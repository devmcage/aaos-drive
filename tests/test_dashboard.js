/* Exercise chart queries/paging without requiring a Home Assistant installation. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const classes = new Map();
const timers = new Set();
function select(value="") {
  return {value,options:[],replaceChildren(){this.options=[];this.value="";},append(option){
    this.options.push(option);if(this.options.length===1)this.value=option.value;
  }};
}
const context = vm.createContext({
  HTMLElement: class {}, window: {customCards: []},
  customElements: {get: key => classes.get(key), define: (key, cls) => classes.set(key, cls)},
  document: {createElement: () => ({value:"",textContent:""})},
  setInterval: fn => {timers.add(fn);return fn;}, clearInterval: fn => timers.delete(fn),
  Date, Map, Set, Object, Promise, JSON, console,
});
vm.runInContext(fs.readFileSync("custom_components/aaos_drive/www/history.js", "utf8"), context);
const Card = classes.get("aaos-history-card");
function card() {
  const target = Object.create(Card.prototype);
  const controls = {
    vehicle: select("car"), field: select("telemetry.speedKph"), trip: select(),
    from: {value: "2026-10-04T13:14"}, through: {value: "2026-10-04T13:23"},
    more: {}, csv: {}, reload:{}, coverage:{}, syncinfo:{}, search:{value:""}, older:{}, tripinfo:{},
  };
  target.$ = key => controls[key];
  target.status = text => target.message=text;
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

  // Refresh must check Drive before reloading the imported fields.
  const fresh = card(), order = [];
  fresh.call = async type => {order.push(type);};
  fresh.loadFields = async preserve => {order.push("fields");assert.equal(preserve,true);};
  await fresh.refreshDrive();
  assert.deepEqual(order,["aaos_drive/history/refresh","fields"]);
  assert.equal(fresh.$("reload").disabled,false);
  fresh.call = async () => {throw new Error("Drive refresh failed");};
  await fresh.refreshDrive();
  assert.equal(fresh.message,"Drive refresh failed"); // Local history still reloaded after failure.

  const live = card();
  let generation="g1", end=1791112976456, statusCalls=0, fieldCalls=0;
  live.call = async (type,query) => {
    if(type==="aaos_drive/history/status"){
      statusCalls++;return {generation_id:generation,drive_available:true,latest_trip_at:end};
    }
    if(type==="aaos_drive/history/fields"){
      fieldCalls++;return {generation_id:generation,drive_available:true,start:1791112467123,end,
        trip_count:1,record_count:2,fields:[{field:"telemetry.speedKph",name:"Speed",unit:"km/h"}]};
    }
    if(type==="aaos_drive/history/trips")return {generation_id:generation,trip_count:1,trips:[],next_cursor:null};
    return {field:query.field,generation_id:generation,points:[{value:1}],next_cursor:null};
  };
  await live.loadFields();
  const originalEnd=live.$("through").value;
  await live.checkForUpdates();
  assert.equal(fieldCalls,1); // Unchanged generation only fetches lightweight local status.
  generation="g2";end+=86400000;
  await live.checkForUpdates();
  assert.equal(fieldCalls,2);
  assert.notEqual(live.$("through").value,originalEnd); // Default full-history bounds follow new data.
  assert.equal(live.data.generation_id,"g2");
  live.$("from").value="2026-10-04T13:15";live.$("through").value="2026-10-04T13:18";
  await live.loadPoints();
  generation="g3";end+=86400000;
  await live.checkForUpdates();
  assert.equal(live.$("from").value,"2026-10-04T13:15");
  assert.equal(live.$("through").value,"2026-10-04T13:18"); // User ranges survive automatic refresh.
  assert.equal(live.loadingFields,false);
  assert.equal(live.loadingPoints,false);
  live.startPolling();live.startPolling();
  assert.equal(timers.size,1);
  live.disconnectedCallback();assert.equal(timers.size,0);
  assert.equal(statusCalls,3);
  console.log("Dashboard checks passed: trip queries, shared pagination, Drive refresh, automatic history updates, preserved ranges and timer cleanup.");
}
run().catch(error => {console.error(error);process.exitCode = 1;});
