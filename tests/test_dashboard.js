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
    more: {}, csv: {}, reload:{}, coverage:{}, syncinfo:{}, drivefolder:{}, sourcecount:{}, search:{value:""}, older:{}, tripinfo:{},
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
  assert.equal(calls.length, 6);
  assert.ok(calls.every(query => query.trip_id === "trip-a"));
  assert.equal(target.moreAvailable, false);
  // All pages load automatically. A later edit cannot trigger more pages for the old selection.
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
  const complete=card();
  complete.info={drive_available:true,fields:[{field:"telemetry.speedKph"}]};
  let pageCalls=0;
  complete.call=async(type,query)=>{
    pageCalls++;
    const page=query.cursor?.page||1;
    return {field:query.field,generation_id:"full",points:Array.from({length:page===3?5:2000},(_,i)=>({time:Date.UTC(2026,9,page===3?12:page===2?8:4)+i,value:i})),next_cursor:page<3?{page:page+1}:null};
  };
  await complete.loadPoints();
  assert.equal(pageCalls,3);
  assert.equal(complete.samples.length,4005);
  assert.equal(new Date(complete.samples.at(-1).time).getUTCDate(),12);
  assert.equal(complete.moreAvailable,false);
  const changing=card();
  changing.info=complete.info;changing.samples=[{value:"previous-complete-selection"}];
  changing.call=async(type,query)=>({field:query.field,generation_id:query.cursor?"g2":"g1",points:[{value:1}],next_cursor:query.cursor?null:{page:2}});
  await changing.loadPoints();
  assert.equal(changing.samples[0].value,"previous-complete-selection");
  assert.match(changing.message,/History changed/);
  const hybrid=card();
  hybrid.trips=[{trip_id:"hybrid",started_at:1,ended_at:60001,telemetry_count:5,route_count:2,
    vehicle_type:"HYBRID",energy_kwh:-0.01,fuel_usage:{movingFuelLiters:0.004,movingConsumptionLitersPer100Km:6,
    coveragePercent:50,engineRunningSeconds:2,engineObservedSeconds:4,engineOffMovingSeconds:2,includesStationaryFuel:false}}];
  hybrid.$("trip").value="hybrid";hybrid.tripSummary();
  assert.match(hybrid.$("tripinfo").textContent,/battery net energy only/);
  assert.match(hybrid.$("tripinfo").textContent,/Moving fuel estimate:/);
  assert.match(hybrid.$("tripinfo").textContent,/0.004 L/);
  assert.match(hybrid.$("tripinfo").textContent,/coverage: 50%/);
  assert.match(hybrid.$("tripinfo").textContent,/includes coasting/);
  hybrid.trips[0].vehicle_type="FUEL";hybrid.trips[0].energy_kwh=null;hybrid.trips[0].fuel_usage=null;
  hybrid.tripSummary();
  assert.match(hybrid.$("tripinfo").textContent,/Moving fuel estimate: Unknown L/);
  assert.doesNotMatch(hybrid.$("tripinfo").textContent,/kWh/);
  const recovered=card();
  recovered.trips=[{trip_id:"recovered",started_at:1,ended_at:60001,telemetry_count:61,route_count:2,
    vehicle_type:"ELECTRIC",energy_kwh:0.6,energy_quality:"recovered"}];
  recovered.$("trip").value="recovered";recovered.tripSummary();
  assert.match(recovered.$("tripinfo").textContent,/0.6 kWh/);
  assert.match(recovered.$("tripinfo").textContent,/Estimated from battery energy/);
  recovered.trips[0].energy_kwh=null;recovered.trips[0].energy_quality="unavailable";
  recovered.tripSummary();
  assert.match(recovered.$("tripinfo").textContent,/consumption unavailable/);
  assert.doesNotMatch(recovered.$("tripinfo").textContent,/0 kWh/);
  // Visible chart notes distinguish estimates, unavailable readings and genuine zeros.
  context.document.createElementNS=()=>({setAttribute(){}});
  const svg={clientWidth:600,replaceChildren(){},setAttribute(){},append(){}};
  const note={};recovered.loadedQuery={start:1,end:60001};
  recovered.chart([{time:1,value:null,quality:"unavailable",trip_id:"a"},
    {time:60001,value:-36,quality:"estimated",trip_id:"a"}],{field:"telemetry.powerKw"},svg,note);
  assert.match(note.textContent,/smoothed over 10–60 seconds/);
  assert.match(note.textContent,/Regeneration remains negative/);
  recovered.chart([{time:1,value:null,quality:"unavailable",trip_id:"a"}],{field:"telemetry.powerKw"},svg,note);
  assert.match(note.textContent,/unavailable, not zero/);
  let csvBlob;
  context.Blob=Blob;
  context.URL={createObjectURL(blob){csvBlob=blob;return "blob:test";},revokeObjectURL(){}};
  context.setTimeout=()=>{};
  context.document.createElement=()=>({click(){}});
  recovered.samples=[{time:1,value:36}];
  recovered.call=async()=>({field:"telemetry.powerKw",unit:"kW",generation_id:"g1",points:[
    {time:1,value:36,trip_id:"a",sample_index:10,quality:"estimated",source:"derived_battery_energy",reported_value:0,reported_source:"vehicle_sensor"}],next_cursor:null});
  recovered.loadedQuery={field:"telemetry.powerKw"};
  await recovered.exportCSV();
  const csv=await csvBlob.text();
  assert.match(csv,/quality,source,reported_value_json,reported_source/);
  assert.match(csv,/"estimated","derived_battery_energy","0","vehicle_sensor"/);
  changing.call=async(type,query)=>({field:query.field,generation_id:"same-id",generation_revision:query.cursor?"new-dataset":"old-dataset",points:[{value:1}],next_cursor:query.cursor?null:{page:2}});
  await changing.loadPoints();
  assert.equal(changing.samples[0].value,"previous-complete-selection");
  assert.match(changing.message,/History changed/);
  console.log("Dashboard checks passed: complete automatic pagination through the final date, mixed-generation rejection, Drive refresh, preserved ranges and timer cleanup.");
}
run().catch(error => {console.error(error);process.exitCode = 1;});
