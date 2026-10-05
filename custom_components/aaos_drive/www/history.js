/* Local, dependency-free history panel and optional dashboard card. */
const STYLE = `
:host{display:block;color:var(--primary-text-color,#17212c);font:14px var(--ha-font-family-body,Roboto,system-ui,sans-serif);background:var(--primary-background-color,#f6f8fa);height:100%;overflow:auto}
main{max-width:1200px;margin:auto;padding:24px}h1{font-size:24px;font-weight:400;margin:0 0 6px}p{color:var(--secondary-text-color,#536575)}
.brand-header{display:flex;align-items:center;gap:16px}.brand-icon{width:56px;height:56px;border-radius:14px;flex:none;object-fit:contain}.brand-header p{margin:0;line-height:1.5}
.controls{display:flex;flex-wrap:wrap;gap:12px;margin:22px 0;align-items:end}label{display:flex;flex-direction:column;gap:6px;font-size:12px;min-width:150px}
select,input,button{font:inherit;padding:10px;border:1px solid var(--divider-color,#c9d4dc);border-radius:8px;background:var(--card-background-color,#fff);color:inherit;max-width:100%;box-sizing:border-box}
button{cursor:pointer}button:disabled{opacity:.5;cursor:default}.field{flex:1;min-width:250px}.message{min-height:20px;white-space:pre-wrap}
.chart{background:var(--card-background-color,#fff);border:1px solid var(--divider-color,#d7e0e6);border-radius:12px;padding:16px;margin:12px 0}
svg{width:100%;height:310px;display:block}.axis{fill:var(--secondary-text-color,#536575);font-size:12px}.grid{stroke:var(--divider-color,#dce4e9);stroke-width:1}
.line{fill:none;stroke:var(--primary-color,#168a92);stroke-width:2}.dot{fill:var(--primary-color,#168a92)}
.table{overflow:auto;max-height:420px;background:var(--card-background-color,#fff)}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:9px;text-align:left;border-bottom:1px solid var(--divider-color,#e0e6eb)}th{position:sticky;top:0;background:var(--card-background-color,#fff)}td.value{max-width:460px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.footer{display:flex;gap:12px;margin-top:14px;align-items:center}@media(max-width:650px){main{padding:16px}label{width:100%}.field{min-width:0}.controls{gap:10px}}`;
const stringValue = value => value === null ? "Unknown" : typeof value === "object" ? JSON.stringify(value) : String(value);
const localInput = ms => {const d = new Date(ms); return new Date(ms - d.getTimezoneOffset()*60000).toISOString().slice(0,16);};
const csvValue = value => {
  let text = value === null ? "" : typeof value === "object" ? JSON.stringify(value) : String(value);
  // Keep source values literal when opened in spreadsheet software.
  if (/^[=+@]/.test(text) || /^-\D/.test(text)) text = "'" + text;
  return '"' + text.replaceAll('"', '""') + '"';
};

class AAOSHistory extends HTMLElement {
  constructor(){super();this.attachShadow({mode:"open"});this.samples=[];this.request=0;}
  set hass(value){this._hass=value;if(this.isConnected && !this.initialized)this.initialize();}
  get hass(){return this._hass;}
  setConfig(config){this.config=config;if(this.initialized)this.loadVehicles();}
  getCardSize(){return 10;}
  connectedCallback(){if(!this.built)this.build();if(this._hass&&!this.initialized)this.initialize();}
  disconnectedCallback(){this.request++;}
  build(){
    this.built=true;
    this.shadowRoot.innerHTML=`<style>${STYLE}</style><main>
      <header class="brand-header"><img class="brand-icon" src="/aaos_drive/icon.png?v=0.4.2" width="56" height="56" alt="AAOS Logging"><div><h1>AAOS trip dashboard</h1><p>Choose a trip or date range to chart each recorded car sensor at its original timestamp.</p></div></header>
      <div class="controls"><label>Vehicle<select id="vehicle"></select></label>
      <label>Trip<select id="trip"><option value="">All trips in the period</option></select></label><button id="older" hidden>Load older trips</button>
      <label class="field">Find a sensor or measurement<input id="search" type="search" placeholder="Speed, battery, brakes, weather…"><select id="field"></select></label>
      <label>From<input id="from" type="datetime-local"></label><label>Through<input id="through" type="datetime-local"></label>
      <button id="show">Show history</button><button id="reload">Reload data</button></div>
      <p id="coverage"></p><p id="tripinfo"></p><div id="message" class="message" role="status" aria-live="polite"></div>
      <div class="chart"><strong id="title"></strong><svg viewBox="0 0 1000 310" role="img" aria-label="Recorded measurements over time"></svg><p id="chartnote"></p></div>
      <div id="graphs"></div>
      <div class="table"><table><thead><tr><th>Recorded time</th><th>Value</th><th>Trip</th><th>Sample</th></tr></thead><tbody></tbody></table></div>
      <div class="footer"><button id="more" disabled>Load more samples</button><button id="csv" disabled>Export full selected history (CSV)</button><span id="count"></span></div>
    </main>`;
    this.$("vehicle").onchange=()=>this.loadFields();
    this.$("search").oninput=()=>this.filterFields();
    this.$("trip").onchange=()=>this.chooseTrip();
    this.$("older").onclick=()=>this.loadTrips(true).catch(e=>this.status(e.message));
    this.$("show").onclick=async()=>{try{await this.loadTrips();await this.loadPoints();}catch(e){this.status(e.message||"Could not load this selection.");}};
    this.$("field").onchange=()=>this.loadPoints();
    this.$("reload").onclick=()=>this.loadFields();
    this.$("more").onclick=()=>this.loadPoints(true);
    this.$("csv").onclick=()=>this.exportCSV();
  }
  $(id){return this.shadowRoot.getElementById(id);}
  status(text){this.$("message").textContent=text;}
  async initialize(){this.initialized=true;await this.loadVehicles();}
  async call(type,extra={}){return this._hass.callWS({type,...extra});}
  async loadVehicles(){
    try{
      const vehicles=await this.call("aaos_drive/history/vehicles");
      this.$("vehicle").replaceChildren();
      for(const v of vehicles){const o=document.createElement("option");o.value=v.id;o.textContent=v.name;this.$("vehicle").append(o);}
      if(this.config?.config_entry_id)this.$("vehicle").value=this.config.config_entry_id;
      if(vehicles.length)await this.loadFields();else this.status("No loaded AAOS vehicle yet. Add the integration and allow its first full history import to finish.");
    }catch(e){this.status(e.message||"Could not load vehicles. This history view requires a Home Assistant administrator account.");}
  }
  async loadFields(){
    const serial=++this.request;
    this.status("Loading imported history…");
    try{
      const info=await this.call("aaos_drive/history/fields",{config_entry_id:this.$("vehicle").value});
      if(serial!==this.request)return;
      this.info=info;
      this.$("coverage").textContent=`${info.trip_count} trips · ${info.record_count.toLocaleString()} sample records · ${info.start===null?"No recorded history":new Date(info.start).toLocaleString()+" — "+new Date(info.end).toLocaleString()}`;
      this.$("from").value=info.start===null?"":localInput(info.start);
      // Include the final minute in the default date selection.
      this.$("through").value=info.end===null?"":localInput(info.end+60000);
      this.periodRange={from:this.$("from").value,through:this.$("through").value};
      await this.loadTrips(false, serial);
      if(serial!==this.request)return;
      if(this.config?.trip_id){
        while(serial===this.request&&this.tripCursor&&!this.trips.some(t=>t.trip_id===this.config.trip_id))await this.loadTrips(true,serial);
        if(serial!==this.request)return;
        if(this.trips.some(t=>t.trip_id===this.config.trip_id))this.$("trip").value=this.config.trip_id;
        this.tripBounds();
      }
      this.filterFields(this.config?.field||this.config?.fields?.[0]||"telemetry.speedKph");
      await this.loadPoints();
    }catch(e){if(serial===this.request)this.status(e.message||"Could not load the imported fields.");}
  }
  async loadTrips(append=false, serial){
    if(serial===undefined)serial=this.request;
    const selected=this.$("trip").value;
    const query=append?this.tripQuery:{config_entry_id:this.$("vehicle").value,limit:200};
    if(!append){
      if(this.$("from").value)query.start=new Date(this.$("from").value).getTime();
      if(this.$("through").value)query.end=new Date(this.$("through").value).getTime();
    }
    this.$("older").disabled=true;
    try{
      const page=await this.call("aaos_drive/history/trips",{...query,...(append?{cursor:this.tripCursor}:{})});
      if(serial!==this.request)return;
      this.tripQuery=query;this.tripCursor=page.next_cursor;
      this.trips=append?(this.trips||[]).concat(page.trips):page.trips;
      this.$("trip").replaceChildren();
      const all=document.createElement("option");all.value="";all.textContent=`All trips in the period (${page.trip_count})`;this.$("trip").append(all);
      for(const t of this.trips){
        const o=document.createElement("option");o.value=t.trip_id;
        o.textContent=new Date(t.started_at).toLocaleString()+(t.distance_km===null?"":` · ${t.distance_km.toLocaleString(undefined,{maximumFractionDigits:1})} km`);
        this.$("trip").append(o);
      }
      if(this.trips.some(t=>t.trip_id===selected))this.$("trip").value=selected;
      this.$("older").hidden=!this.tripCursor;this.tripSummary();
    }catch(e){if(serial===this.request){this.status(e.message||"Could not load recorded trips.");throw e;}}
    finally{if(serial===this.request)this.$("older").disabled=false;}
  }
  tripBounds(){
    const trip=this.trips?.find(t=>t.trip_id===this.$("trip").value);
    if(trip){
      this.$("from").value=localInput(trip.started_at);this.$("through").value=localInput(trip.ended_at+60000);
      this.tripSelection={trip_id:trip.trip_id,from:this.$("from").value,through:this.$("through").value,start:trip.started_at,end:trip.ended_at};
    }
  }
  async chooseTrip(){
    try{
      if(this.$("trip").value)this.tripBounds();
      else{this.$("from").value=this.periodRange.from;this.$("through").value=this.periodRange.through;await this.loadTrips();}
      this.tripSummary();await this.loadPoints();
    }catch(e){this.status(e.message||"Could not load the selected trip.");}
  }
  tripSummary(){
    const t=this.trips?.find(t=>t.trip_id===this.$("trip").value);
    this.$("tripinfo").textContent=t?`${new Date(t.started_at).toLocaleString()} — ${new Date(t.ended_at).toLocaleTimeString()} · ${t.telemetry_count.toLocaleString()} telemetry samples · ${t.route_count.toLocaleString()} route points${t.energy_kwh===null?"":` · ${t.energy_kwh.toLocaleString(undefined,{maximumFractionDigits:2})} kWh`}`:"Separate trips keep their own recorded samples; the chart does not connect them.";
  }
  filterFields(preferred){
    const selected=preferred||this.$("field").value;
    const query=this.$("search").value.toLowerCase();
    this.$("field").replaceChildren();
    for(const f of this.info?.fields||[]){
      if(!(f.name+" "+f.field).toLowerCase().includes(query))continue;
      const o=document.createElement("option");o.value=f.field;o.textContent=f.name+(f.unit?` (${f.unit})`:"");o.title=f.field;this.$("field").append(o);
    }
    if([...this.$("field").options].some(o=>o.value===selected))this.$("field").value=selected;
  }
  query(){
    const result={config_entry_id:this.$("vehicle").value,field:this.$("field").value,limit:2000};
    if(this.$("trip").value)result.trip_id=this.$("trip").value;
    if(this.$("from").value)result.start=new Date(this.$("from").value).getTime();
    if(this.$("through").value)result.end=new Date(this.$("through").value).getTime();
    // A selected trip starts/ends at its exact source milliseconds, even though
    // the date controls display minutes. User-edited ranges use their chosen bounds.
    if(this.tripSelection&&result.trip_id===this.tripSelection.trip_id&&this.$("from").value===this.tripSelection.from&&this.$("through").value===this.tripSelection.through){
      result.start=this.tripSelection.start;result.end=this.tripSelection.end;
    }
    return result;
  }
  async loadPoints(append=false){
    if(append&&!this.moreAvailable)return;
    const query=append?this.loadedQuery:this.query();
    if(!append&&!query.trip_id)this.periodRange={from:this.$("from").value,through:this.$("through").value};
    if(!query.field){this.status("No matching field. Clear the search or choose a different vehicle.");return;}
    const serial=++this.request;
    this.status("Loading recorded samples…");this.$("more").disabled=true;this.$("csv").disabled=true;
    try{
      const fields=append?this.loadedFields:[...new Set([query.field,...(this.config?.fields||[])])].filter(f=>this.info.fields.some(info=>info.field===f));
      const pages=await Promise.all(fields.map(async field=>{
        const previous=append?this.series[field]:null;
        if(append&&!previous.next_cursor)return previous;
        const page=await this.call("aaos_drive/history/points",{...query,field,...(append?{cursor:previous.next_cursor}:{})});
        if(append)page.points=previous.points.concat(page.points);
        return page;
      }));
      if(serial!==this.request)return;
      if(new Set(pages.map(page=>page.generation_id)).size>1)throw new Error("History changed while loading charts. Reload data and try again.");
      this.loadedFields=fields;this.series=Object.fromEntries(pages.map(page=>[page.field,page]));
      const data=this.series[query.field];
      this.loadedQuery={...query};this.data=data;this.cursor=data.next_cursor;
      this.samples=data.points;this.moreAvailable=pages.some(page=>page.next_cursor);
      this.render();
      this.status(this.info.drive_available===false?"Drive is currently unavailable. Showing the last complete local history.":this.info.statistics_error||"");
    }catch(e){if(serial===this.request)this.status(e.message||"History changed or could not be read. Reload fields and try again.");}
    finally{if(serial===this.request){this.$("more").disabled=!this.moreAvailable;this.$("csv").disabled=!this.samples.length;}}
  }
  render(){
    const data=this.data, rows=this.samples;
    this.$("title").textContent=data.name+(data.unit?` (${data.unit})`:"");
    this.$("count").textContent=`${rows.length.toLocaleString()} samples loaded${this.cursor?" · More available":" · All matching samples loaded"}`;
    const body=this.shadowRoot.querySelector("tbody");body.replaceChildren();
    // Keep the table responsive. The chart and CSV include every loaded point.
    for(const p of rows.slice(-500)){
      const tr=document.createElement("tr");
      const value=data.timestamp_value&&typeof p.value==="number"?new Date(p.value).toLocaleString():stringValue(p.value);
      const trip=this.trips?.find(t=>t.trip_id===p.trip_id);
      for(const [i,text] of [new Date(p.time).toLocaleString(),value,trip?new Date(trip.started_at).toLocaleString():p.trip_id||"",String(p.sample_index)].entries()){
        const td=document.createElement("td");td.textContent=text;if(i===1){td.className="value";td.title=value;}tr.append(td);
      }body.append(tr);
    }
    this.chart(rows,data);
    this.$("graphs").replaceChildren();
    for(const field of this.loadedFields.filter(f=>f!==data.field)){
      const page=this.series[field],box=document.createElement("div");box.className="chart";
      const title=document.createElement("strong");title.textContent=page.name+(page.unit?` (${page.unit})`:"");
      const svg=document.createElementNS("http://www.w3.org/2000/svg","svg");svg.setAttribute("role","img");svg.setAttribute("aria-label",page.name+" over recorded time");
      const note=document.createElement("p");box.append(title,svg,note);this.$("graphs").append(box);
      this.chart(page.points,page,svg,note);
    }
  }
  chart(rows,data,svg=this.shadowRoot.querySelector("svg"),note=this.$("chartnote")){
    svg.replaceChildren();
    const width=Math.max(320,svg.clientWidth||1000),right=width-20;
    svg.setAttribute("viewBox",`0 0 ${width} 310`);
    const valid=rows.filter(p=>p.value!==null);
    const numeric=!data.categorical&&!data.timestamp_value&&valid.every(p=>typeof p.value==="number");
    const categories=numeric?[]:[...new Set(valid.map(p=>stringValue(p.value)))];
    const categoryIndex=new Map(categories.map((v,i)=>[v,i]));
    const number=p=>numeric?p.value:categoryIndex.get(stringValue(p.value));
    const add=(tag,attrs,text)=>{const e=document.createElementNS("http://www.w3.org/2000/svg",tag);for(const [k,v]of Object.entries(attrs))e.setAttribute(k,String(v));if(text!==undefined)e.textContent=text;svg.append(e);return e;};
    if(!valid.length){add("text",{x:70,y:145,class:"axis"},"No non-null values in this selection");note.textContent="Unknown samples remain in the table and CSV.";return;}
    let low=Infinity,high=-Infinity;
    for(const p of valid){const n=number(p);low=Math.min(low,n);high=Math.max(high,n);}
    if(low===high){low-=numeric?1:.5;high+=numeric?1:.5;}
    const first=this.loadedQuery.start??rows[0].time,last=this.loadedQuery.end??rows.at(-1).time,span=Math.max(1,last-first);
    const x=p=>80+(p.time-first)/span*(right-80),y=p=>255-(number(p)-low)/(high-low)*220;
    for(let i=0;i<5;i++){
      const v=low+(high-low)*i/4,yy=255-i*55;
      add("line",{x1:80,x2:right,y1:yy,y2:yy,class:"grid"});
      add("text",{x:75,y:yy+4,"text-anchor":"end",class:"axis"},numeric?v.toLocaleString(undefined,{maximumFractionDigits:2}):(categories[Math.round(v)]||"").slice(0,10));
    }
    let path="",previous=null;
    // Null samples and trip boundaries break the trace; no invented points between trips.
    for(const p of rows){
      if(p.value===null){previous=null;continue;}
      const xx=x(p),yy=y(p);
      const same=previous&&previous.trip_id===p.trip_id&&p.trip_id!==null;
      if(!same)path+=` M ${xx} ${yy}`;
      else path+=numeric?` L ${xx} ${yy}`:` H ${xx} V ${yy}`;
      if(!same||!numeric)add("circle",{cx:xx,cy:yy,r:2.5,class:"dot"});
      previous=p;
    }
    add("path",{d:path,class:"line"});
    const dateLabel=ms=>span>=86400000?new Date(ms).toLocaleDateString():new Date(ms).toLocaleTimeString();
    add("text",{x:80,y:290,class:"axis"},dateLabel(first));
    add("text",{x:right,y:290,class:"axis","text-anchor":"end"},dateLabel(last));
    note.textContent=(numeric?"Original samples; gaps and separate trips remain separate.":"Recorded states and codes; Unknown remains unknown.")+` ${rows.length.toLocaleString()} samples${this.series[data.field].next_cursor?" · Load more to extend this chart":""}.`;
  }
  async exportCSV(){
    const query={...this.loadedQuery},serial=++this.request;
    this.$("csv").disabled=true;this.$("more").disabled=true;
    const lines=["recorded_at_utc,recorded_at_unix_ms,field,value_json,unit,trip_id,sample_index"];
    let cursor, generation=null;
    try{
      do{
        const page=await this.call("aaos_drive/history/points",{...query,limit:10000,...(cursor?{cursor}:{})});
        if(serial!==this.request)return;
        if(generation!==null&&generation!==page.generation_id)throw new Error("History changed during export. Try again.");
        generation=page.generation_id;
        for(const p of page.points)lines.push([new Date(p.time).toISOString(),p.time,page.field,JSON.stringify(p.value),page.unit||"",p.trip_id||"",p.sample_index].map(csvValue).join(","));
        cursor=page.next_cursor;this.status(`Preparing CSV: ${(lines.length-1).toLocaleString()} samples…`);
      }while(cursor);
      const url=URL.createObjectURL(new Blob([lines.join("\r\n")],{type:"text/csv;charset=utf-8"}));
      const link=document.createElement("a");link.href=url;link.download="aaos-"+query.field.replace(/[^a-z0-9_-]/gi,"_")+".csv";link.click();setTimeout(()=>URL.revokeObjectURL(url),10000);
      this.status(`Exported ${(lines.length-1).toLocaleString()} samples.`);
    }catch(e){this.status(e.message||"CSV export failed.");}
    finally{if(serial===this.request){this.$("csv").disabled=false;this.$("more").disabled=!this.moreAvailable;}}
  }
}
if(!customElements.get("aaos-history-panel"))customElements.define("aaos-history-panel",class extends AAOSHistory{});
if(!customElements.get("aaos-history-card"))customElements.define("aaos-history-card",class extends AAOSHistory{});
window.customCards=window.customCards||[];
if(!window.customCards.some(c=>c.type==="aaos-history-card"))window.customCards.push({type:"aaos-history-card",name:"AAOS trip dashboard",description:"Recorded car sensors by trip and date range."});
