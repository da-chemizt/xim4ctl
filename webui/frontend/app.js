"use strict";
// ---------------------------------------------------------------- API + state
const API = {
  async get(u){ const r=await fetch(u,{cache:"no-store"}); if(!r.ok) throw await err(r); return r.json(); },
  async post(u,b){ const r=await fetch(u,{method:"POST",headers:J,body:b?JSON.stringify(b):null}); if(!r.ok) throw await err(r); return r.json(); },
  async put(u,b){ const r=await fetch(u,{method:"PUT",headers:J,body:JSON.stringify(b)}); if(!r.ok) throw await err(r); return r.json(); },
};
const J = {"Content-Type":"application/json"};
async function err(r){ let m=r.status; try{ m=(await r.json()).detail||m; }catch(_){} return new Error(m); }

let ENUMS = null;         // /api/enums
let MANIFEST = {covers:{}, icons:{}, buttonIcons:{}};  // /assets/manifest.json
let CONFIGS = [];         // library list
let ACTIVE = null;        // active slot index on device
let cur = null;           // full parsed config being edited
let curSlot = null;       // slot index being edited
let fmIndex = 0;          // selected fire-mode

const BEACON_CSS = {red:"#dc2626",green:"#16a34a",blue:"#2563eb",yellow:"#eab308",
  magenta:"#db2777",cyan:"#06b6d4",white:"#e5e7eb",darkgreen:"#166534",purple:"#7c3aed",
  orange:"#ea580c",red2:"#b91c1c",bluishpurple:"#6d28d9",kiwi:"#84cc16",eggyolk:"#f59e0b",
  lightblue:"#38bdf8"};

const $ = id => document.getElementById(id);
function status(msg, cls=""){ const s=$("statusMsg"); s.innerHTML=msg; s.className="status "+cls; }

// ---------------------------------------------------------------- bootstrap
async function boot(){
  try { ENUMS = await API.get("/api/enums"); }
  catch(e){ status("Failed to load enums: "+e.message,"err"); return; }
  try { MANIFEST = await API.get("/assets/manifest.json"); } catch(_){}
  buildStatic();
  await refreshStatus();
  await loadLibrary();
  connectWS();
  wireEvents();
  setActivity(true);   // live activity panel shown by default
  setInterval(refreshStatus, 4000);   // keep conn state / reconnect button live
  const m=/^#edit\/(\d+)(?:\/(\w+))?$/.exec(location.hash);
  if(m){ await openEditor(+m[1]);
    if(m[2]){ const t=document.querySelector(`#settingTabs button[data-tab="${m[2]}"]`); if(t) t.click(); }
    if(new URLSearchParams(location.search).get("activity")) $("activityToggle").click(); }
}

async function refreshStatus(){
  try{
    const s = await API.get("/api/status");
    ACTIVE = s.active;
    const q = new URLSearchParams(location.search).get("active");  // preview override
    if(q!==null) ACTIVE = +q;
    if(ACTIVE!==_activeCfgFor){          // cache the active config for feed resolution
      _activeCfgFor = ACTIVE;
      if(ACTIVE!=null){ try{ ACTIVECFG = normalize(await API.get(`/api/config/${ACTIVE}`)); }catch(_){ ACTIVECFG=null; } }
      else ACTIVECFG=null;
    }
    const on = s.device && s.device.connected;
    $("connDot").className = "conn-dot "+(on?"on":"off");
    $("connText").textContent = on ? ("device "+(s.device.firmware||"connected")) : "device idle";
    $("reconnectBtn").hidden = on;   // offer manual wedge-buster only when idle
    $("activeChip").textContent = "active: "+(ACTIVE==null?"—":slotName(ACTIVE));
    $("activeChip").className = "chip"+(ACTIVE!=null?" on":"");
  }catch(_){}
}
function slotName(i){ const c=CONFIGS.find(c=>c.index===i); return c?c.title:("#"+i); }

// -- artwork helpers --
const _norm = s => (s||"").toLowerCase().replace(/[^a-z0-9]+/g,"");
function coverFor(name){
  const c = MANIFEST.covers || {};
  if(c[name]) return "/assets/"+c[name];
  const n=_norm(name);
  for(const k in c){ if(_norm(k)===n) return "/assets/"+c[k]; }
  return null;
}
function glyphFor(platformIndex, slot){
  const m = (MANIFEST.buttonIcons||{})[platformIndex] || (MANIFEST.buttonIcons||{})["0"];
  return m && m[slot] ? "/assets/"+m[slot] : null;
}

// ---------------------------------------------------------------- library view
async function loadLibrary(){
  CONFIGS = await API.get("/api/configs");
  renderLibrary();
}
function renderLibrary(){
  const g=$("libGrid"); g.innerHTML="";
  $("libEmpty").hidden = CONFIGS.length>0;
  for(const c of CONFIGS){
    const col = BEACON_CSS[c.beacon] || "var(--muted)";
    const cover = coverFor(c.title);
    const plat = (MANIFEST.platforms||{})[c.platformIndex] || {name:c.platform, color:"var(--border)"};
    const card=document.createElement("div");
    card.className="lib-card"+(c.index===ACTIVE?" active":"")+(cover?" has-cover":"");
    if(cover) card.style.setProperty("--cover", `url("${cover}")`);
    card.style.setProperty("--plat", plat.color || "var(--border)");
    const platTag = plat.icon
      ? `<img class="plat-tag" src="/assets/${plat.icon}" alt="${esc(plat.name)}" title="${esc(plat.name)}">`
      : `<span class="plat-tag plat-tag-text">${esc(c.platform)}</span>`;
    card.innerHTML=`
      ${platTag}
      <span class="accent-strip" style="background:${col}"></span>
      <div class="name">${esc(c.title)}</div>
      <div class="meta">
        <span class="swatch" style="background:${col}" title="${esc(c.beacon)}"></span>
        ${c.index===ACTIVE?'<span class="badge active-badge">active</span>':''}
      </div>
      <div class="card-actions">
        <button class="btn-secondary act-edit" type="button">Edit</button>
        <button class="btn-primary act-switch" type="button">Make active</button>
      </div>`;
    card.querySelector(".act-edit").onclick=e=>{e.stopPropagation();openEditor(c.index);};
    card.querySelector(".act-switch").onclick=e=>{e.stopPropagation();makeActive(c.index);};
    card.onclick=()=>openEditor(c.index);
    g.appendChild(card);
  }
}
async function makeActive(i){
  status(`<span class="spinner"></span>Switching to ${slotName(i)}…`);
  try{ await API.post(`/api/switch/${i}`); ACTIVE=i; renderLibrary(); await refreshStatus();
       status("Now active: "+slotName(i),"ok"); }
  catch(e){ status("Switch failed: "+e.message,"err"); }
}

// ---------------------------------------------------------------- editor
async function openEditor(slot){
  status(`<span class="spinner"></span>Loading config…`);
  try{ cur = normalize(await API.get(`/api/config/${slot}`)); }
  catch(e){ status("Load failed: "+e.message,"err"); return; }
  curSlot = slot; fmIndex = 0;
  $("libraryView").hidden = true; $("editorView").hidden = false;
  $("edTitle").textContent = cur.name || "Edit Config";
  const cov = coverFor(cur.name);
  const banner = $("edCover");
  if(cov){ banner.style.backgroundImage=`url("${cov}")`; banner.hidden=false; }
  else banner.hidden=true;
  $("cfgSlot").textContent = slot;
  fillSelect($("cfgPlatform"), ENUMS.platform, cur.platformIndex);
  fillSelect($("cfgBeacon"), ENUMS.beacon, cur.beaconIndex);
  $("cfgName").value = cur.name;
  updateBeaconSwatch();
  renderPtt();
  renderFiremodeTabs();
  renderSetting();
  status("");
}
function normalize(cfg){
  for(const s of cfg.settings){
    const p={},sec={};
    for(const b of ENUMS.buttons){ p[b]=s.primary[b]??null; sec[b]=s.secondary[b]??null; }
    s.primary=p; s.secondary=sec;
    for(const k of ENUMS.stickKeys){ if(!(k in s.keyboardSticks)) s.keyboardSticks[k]=null; }
  }
  return cfg;
}
function fillSelect(sel, mapObj, cur){
  sel.innerHTML="";
  for(const [k,v] of Object.entries(mapObj)){
    const o=document.createElement("option"); o.value=k; o.textContent=v;
    if(+k===+cur) o.selected=true; sel.appendChild(o);
  }
}
function renderFiremodeTabs(){
  const wrap=$("firemodeTabs"); wrap.innerHTML="";
  cur.settings.forEach(s=>{
    const b=document.createElement("button"); b.type="button";
    const nm=s.name||`Mode ${s.index+1}`;
    b.textContent=nm; b.className=(s.index===fmIndex?"active ":"")+(s.present?"":"empty");
    b.title=s.present?nm:"(empty fire-mode)";
    b.onclick=()=>{ fmIndex=s.index; renderFiremodeTabs(); renderSetting(); };
    wrap.appendChild(b);
  });
}
function S(){ return cur.settings[fmIndex]; }

function renderSetting(){
  const s=S();
  $("sSensitivity").value=s.sensitivity;
  $("sYxRatio").value=s.yxRatio;
  $("sBoost").value=s.boost;
  $("sUseTranslator").value=s.useTranslator;
  $("sInvert").checked=!!s.invert;
  $("sDeadzone").value=s.deadzone;
  $("sSwapSticks").checked=!!s.swapSticks;
  $("sLeftStick").checked=!!s.leftStick;
  $("sActivateMode").value=s.activateMode;
  $("sTurnAssistMode").value=s.turnAssistMode;
  renderPickers();
  renderStickGrids();
  renderButtonMap();
  drawCurve();
  renderCurveInputs();
}

// -- live activity feed (input -> output glyph + function) --
function outLabel(cfg, slot){ return ((MANIFEST.buttonLabels||{})[cfg.platformIndex]||{})[slot] || slot; }
// conventional shooter defaults — fallback when a game has no real label in the DB
const DEFAULT_ACTIONS = {RT:"Fire", LT:"Aim", RB:"Grenade", LB:"Melee", RS:"Melee", LS:"Sprint",
  A:"Jump", B:"Crouch", X:"Reload", Y:"Swap", Start:"Menu", Back:"Map", Guide:"Home"};
// real per-game action label from the .ximmr (keyed by gameUID = directory owner id),
// with per-platform overrides; falls back to the generic default.
function actionFor(cfg, slot){
  const al=(MANIFEST.actionLabels||{})[cfg.gameUID];
  if(al){
    const ov=al.byPlatform && al.byPlatform[cfg.platformIndex];
    if(ov && ov[slot]) return ov[slot];
    if(al[slot]) return al[slot];
  }
  return DEFAULT_ACTIONS[slot];
}

// which config do we resolve the live input against — the one being edited, else the active one
let ACTIVECFG=null, _activeCfgFor=undefined;
function feedCfg(){ return (!$("editorView").hidden && cur) ? cur : ACTIVECFG; }
function resolveOutput(inputName){
  const cfg=feedCfg(); if(!cfg||!inputName) return null;
  for(const s of cfg.settings){
    for(const b of ENUMS.buttons){
      if(s.primary[b]===inputName||s.secondary[b]===inputName)
        return {slot:b, label:outLabel(cfg,b), glyph:glyphFor(cfg.platformIndex,b), action:actionFor(cfg,b)};
    }
    for(const k in (s.keyboardSticks||{})) if(s.keyboardSticks[k]===inputName)
      return {slot:k, label:k, glyph:null, action:null};
  }
  return {slot:null, label:"unmapped", glyph:null, action:null};
}

// the backend runs the 0x3c poller and pushes "activity" events over the WebSocket
function startLiveFeed(){ API.post("/api/feed",{on:true}).catch(()=>{}); }
function stopLiveFeed(){ API.post("/api/feed",{on:false}).catch(()=>{}); }
function setActivity(open){
  $("activityPanel").hidden=!open;
  document.body.classList.toggle("activity-open",open);
  open?startLiveFeed():stopLiveFeed();
}
function pushActivity(inputName){
  const feed=$("activityFeed"); if(!feed) return;
  const empty=feed.querySelector(".act-empty"); if(empty) empty.remove();
  const o=resolveOutput(inputName);   // null when we have no config context yet
  const el=document.createElement("div"); el.className="act-evt";
  let out;
  if(!o) out=`<span class="act-out act-none">(no active config)</span>`;
  else out=(o.glyph?`<img class="act-glyph" src="${o.glyph}" alt="">`:"")
    +`<span class="act-out">${esc(o.label||"")}</span>`
    +(o.action?`<span class="act-fn">(${esc(o.action)})</span>`:"");
  el.innerHTML=`<span class="act-in">${esc(inputName)}</span><span class="act-arrow">→</span>`+out;
  feed.appendChild(el);
  while(feed.children.length>150) feed.removeChild(feed.firstChild);
  feed.scrollTop=feed.scrollHeight;
}

// -- config-level & activation pickers --
function renderPtt(){ pickerInto($("editorView").querySelector('[data-picker="pttKey"]'), cur, "pushToTalkKey"); }
function renderPickers(){
  pickerInto(document.querySelector('[data-picker="activateKey"]'), S(), "activateKey");
  pickerInto(document.querySelector('[data-picker="turnAssistKey"]'), S(), "turnAssistKey");
}

// -- keyboard stick grids --
const STICK_LABELS={leftUp:"Up",leftLeft:"Left",leftRight:"Right",leftDown:"Down",leftWalk:"Walk",
  rightUp:"Up",rightLeft:"Left",rightRight:"Right",rightDown:"Down"};
function renderStickGrids(){
  const s=S();
  const L=["leftUp","leftLeft","leftRight","leftDown","leftWalk"];
  const R=["rightUp","rightLeft","rightRight","rightDown"];
  fillStick($("leftStickGrid"),s,L); fillStick($("rightStickGrid"),s,R);
}
function fillStick(grid,s,keys){
  grid.innerHTML="";
  for(const k of keys){
    const lab=document.createElement("label"); lab.textContent=STICK_LABELS[k];
    const holder=document.createElement("div"); holder.className="inp-picker";
    lab.appendChild(holder); grid.appendChild(lab);
    pickerInto(holder, s.keyboardSticks, k);
  }
}

// -- button map --
function renderButtonMap(){
  const s=S(); const wrap=$("buttonMap"); wrap.innerHTML="";
  for(const b of ENUMS.buttons){
    const row=document.createElement("div"); row.className="btn-map-row";
    const nm=document.createElement("div"); nm.className="bname";
    const g=glyphFor(cur.platformIndex, b);
    if(g){ const im=document.createElement("img"); im.className="btn-glyph"; im.src=g; im.alt=b; nm.appendChild(im); }
    const lbl=((MANIFEST.buttonLabels||{})[cur.platformIndex]||{})[b] || b;
    const span=document.createElement("span"); span.textContent=lbl;
    if(lbl!==b) span.title=b;   // keep canonical slot name on hover
    nm.appendChild(span);
    const p=document.createElement("div"); p.className="inp-picker";
    const sec=document.createElement("div"); sec.className="inp-picker";
    row.append(nm,p,sec); wrap.appendChild(row);
    pickerInto(p, s.primary, b);
    pickerInto(sec, s.secondary, b);
  }
}

// ---------------------------------------------------------------- input picker
function pickerInto(holder, obj, key){
  holder.innerHTML="";
  holder.className="inp-picker picker-holder";
  const val=obj[key];
  const btn=document.createElement("button");
  btn.type="button"; btn.className="inp-btn"+(val?"":" unmapped");
  btn.innerHTML=`<span class="kbd">${val?esc(val):"—"}</span><span class="caret">▾</span>`;
  btn.onclick=()=>openPicker(btn, obj, key);
  const listen=document.createElement("button");
  listen.type="button"; listen.className="listen-btn";
  listen.title="Listen — press an input on the device to assign it";
  listen.textContent="◉";
  listen.onclick=()=>captureInput(holder, obj, key);
  holder.append(btn, listen);
}
async function captureInput(holder, obj, key){
  holder.classList.add("listening");
  status(`<span class="spinner"></span>Listening — press an input on the device…`, "warn");
  try{
    const r = await API.post("/api/capture", {timeout: 6});
    if(r.name){ obj[key]=r.name; markDirty(); status("Captured: "+r.name, "ok"); }
    else status("Nothing pressed — click listen and press an input on the device", "warn");
  }catch(e){ status("Capture failed: "+e.message, "err"); }
  pickerInto(holder, obj, key);
}
function openPicker(anchor, obj, key){
  const pop=$("pickerPop");
  pop.innerHTML="";
  const search=document.createElement("input");
  search.className="pp-search"; search.type="text"; search.placeholder="search…";
  pop.appendChild(search);
  const body=document.createElement("div"); pop.appendChild(body);
  const groups=[["—",[null]],["Controller",ENUMS.controller||[]],["Mouse",ENUMS.mouse],["Wheel",ENUMS.wheel],["Keyboard",ENUMS.keyboard]];
  function draw(filter){
    body.innerHTML="";
    for(const [g,items] of groups){
      const fil=items.filter(it=> it===null ? true : it.toLowerCase().includes(filter));
      if(!fil.length) continue;
      const h=document.createElement("div"); h.className="pp-group"; h.textContent=g; body.appendChild(h);
      const box=document.createElement("div"); box.className="pp-items";
      for(const it of fil){
        const el=document.createElement("div"); el.className="pp-item"+(obj[key]===it||(it===null&&!obj[key])?" sel":"");
        el.textContent=it===null?"Unmapped":it;
        el.onclick=()=>{ obj[key]=it; closePicker(); refreshOne(anchor,obj,key); markDirty(); };
        box.appendChild(el);
      }
      body.appendChild(box);
    }
  }
  draw("");
  search.oninput=()=>draw(search.value.toLowerCase());
  // position
  const r=anchor.getBoundingClientRect();
  pop.hidden=false;
  pop.style.top=(window.scrollY+r.bottom+4)+"px";
  pop.style.left=(window.scrollX+Math.min(r.left, window.innerWidth-340))+"px";
  setTimeout(()=>search.focus(),0);
  setTimeout(()=>document.addEventListener("mousedown",outside),0);
  function outside(e){ if(!pop.contains(e.target)){ closePicker(); } }
  pop._outside=outside;
}
function closePicker(){ const pop=$("pickerPop"); pop.hidden=true; if(pop._outside){document.removeEventListener("mousedown",pop._outside);pop._outside=null;} }
function refreshOne(anchor,obj,key){ pickerInto(anchor.parentElement,obj,key); }

// ---------------------------------------------------------------- ballistic curve
function drawCurve(){
  const c=$("curveCanvas"); const s=S();
  const w=c.clientWidth||600, h=160; c.width=w; c.height=h;
  const ctx=c.getContext("2d");
  const css=n=>getComputedStyle(document.body).getPropertyValue(n);
  ctx.clearRect(0,0,w,h);
  const pad=8, maxY=Math.max(4,...s.curve);
  ctx.strokeStyle=css("--border"); ctx.lineWidth=1;
  for(let i=0;i<=4;i++){ const y=pad+(h-2*pad)*i/4; ctx.beginPath();ctx.moveTo(pad,y);ctx.lineTo(w-pad,y);ctx.stroke(); }
  ctx.strokeStyle=css("--accent")||"#3b82f6"; ctx.lineWidth=2; ctx.beginPath();
  s.curve.forEach((v,i)=>{ const x=pad+(w-2*pad)*i/19, y=h-pad-(h-2*pad)*(v/maxY);
    i?ctx.lineTo(x,y):ctx.moveTo(x,y); });
  ctx.stroke();
  ctx.fillStyle=css("--accent")||"#3b82f6";
  s.curve.forEach((v,i)=>{ const x=pad+(w-2*pad)*i/19, y=h-pad-(h-2*pad)*(v/maxY);
    ctx.beginPath();ctx.arc(x,y,2.5,0,7);ctx.fill(); });
  $("curveMeta").textContent=`peak ${maxY.toFixed(1)}`;
}
function renderCurveInputs(){
  const wrap=$("curveInputs"); const s=S(); wrap.innerHTML="";
  s.curve.forEach((v,i)=>{
    const inp=document.createElement("input");
    inp.type="number"; inp.step="0.5"; inp.min="0"; inp.max="127.5"; inp.value=v; inp.title="point "+(i+1);
    inp.oninput=()=>{ s.curve[i]=parseFloat(inp.value)||0; drawCurve(); markDirty(); };
    wrap.appendChild(inp);
  });
}

// ---------------------------------------------------------------- edit wiring
function markDirty(){ status("Unsaved changes","warn"); }
// theme toggle — data-theme is pre-set by the inline <head> script (saved choice / OS pref)
function initTheme(){
  const root=document.documentElement, btn=$("themeBtn");
  const paint=()=>{ const dark=root.getAttribute("data-theme")==="dark";
    $("themeSun").style.display=dark?"":"none"; $("themeMoon").style.display=dark?"none":"";
    btn.title=dark?"Switch to light mode":"Switch to dark mode"; };
  paint();
  btn.onclick=()=>{
    const dark=root.getAttribute("data-theme")!=="dark";
    root.setAttribute("data-theme", dark?"dark":"light");
    localStorage.setItem("xim_theme", dark?"dark":"light");
    paint();
    if(!$("editorView").hidden && cur) drawCurve();   // canvas colors come from CSS vars
  };
}

async function doRecover(){
  const b=$("reconnectBtn");
  b.disabled=true; status(`<span class="spinner"></span>Reconnecting — clearing wedged link…`,"warn");
  try{
    const r=await API.post("/api/recover");
    if(r.connected){ status("Reconnected ✓","ok"); }
    else status("Reconnect failed — wake the XIM and retry: "+(r.error||""),"err");
  }catch(e){ status("Reconnect failed: "+e.message,"err"); }
  b.disabled=false; await refreshStatus();
}

function wireEvents(){
  initTheme();
  $("reconnectBtn").onclick=doRecover;
  $("newBtn").onclick=newConfig;
  $("syncBtn").onclick=syncDevice;
  $("backBtn").onclick=()=>{ $("editorView").hidden=true; $("libraryView").hidden=false; loadLibrary(); };
  $("activityToggle").onclick=()=>setActivity($("activityPanel").hidden);
  $("activityClose").onclick=()=>setActivity(false);
  $("makeActiveBtn").onclick=()=>makeActive(curSlot);
  $("saveLibBtn").onclick=()=>saveConfig(false);
  $("writeBtn").onclick=()=>saveConfig(true);

  // config-level bindings
  $("cfgName").oninput=()=>{ cur.name=$("cfgName").value; $("edTitle").textContent=cur.name; markDirty(); };
  $("cfgPlatform").onchange=()=>{ cur.platformIndex=+$("cfgPlatform").value; markDirty(); };
  $("cfgBeacon").onchange=()=>{ cur.beaconIndex=+$("cfgBeacon").value; updateBeaconSwatch(); markDirty(); };
  // setting-level numeric/checkbox bindings
  bind("sSensitivity","sensitivity",parseFloat);
  bind("sYxRatio","yxRatio",parseFloat);
  bind("sBoost","boost",v=>parseInt(v||0));
  bind("sDeadzone","deadzone",v=>parseInt(v||0));
  bind("sUseTranslator","useTranslator",v=>+v,"onchange");
  bind("sActivateMode","activateMode",v=>+v,"onchange");
  bind("sTurnAssistMode","turnAssistMode",v=>+v,"onchange");
  bindChk("sInvert","invert");
  bindChk("sSwapSticks","swapSticks");
  bindChk("sLeftStick","leftStick");
  // setting tabs
  document.querySelectorAll("#settingTabs button").forEach(b=>{
    b.onclick=()=>{
      document.querySelectorAll("#settingTabs button").forEach(x=>x.classList.remove("active"));
      b.classList.add("active");
      document.querySelectorAll(".tabpanel").forEach(p=>p.classList.toggle("active",p.dataset.panel===b.dataset.tab));
      if(b.dataset.tab==="mouse") drawCurve();
    };
  });
}
function bind(id,key,conv,ev="oninput"){ $(id)[ev]=()=>{ S()[key]=conv($(id).value); markDirty(); }; }
function bindChk(id,key){ $(id).onchange=()=>{ S()[key]=$(id).checked?1:0; markDirty(); }; }
function updateBeaconSwatch(){ const nm=ENUMS.beacon[cur.beaconIndex]; $("beaconSwatch").style.background=BEACON_CSS[nm]||"var(--muted)"; }

async function saveConfig(toDevice){
  const payload=serialize();
  status(`<span class="spinner"></span>${toDevice?"Writing to device":"Saving"}…`);
  try{
    if(toDevice){ await API.put(`/api/config/${curSlot}`, payload); ACTIVE=curSlot; }
    else { await API.put(`/api/config/${curSlot}/library`, payload); }
    status(toDevice?"Written to device ✓":"Saved to library ✓","ok");
    await refreshStatus();
  }catch(e){ status((toDevice?"Write":"Save")+" failed: "+e.message,"err"); }
}
function serialize(){
  // send the full current config; codec patches every mapped offset (round-trip safe)
  return {
    title: cur.name, name: cur.name, gameUID: cur.gameUID,
    beaconIndex: cur.beaconIndex, platformIndex: cur.platformIndex,
    pushToTalkKey: cur.pushToTalkKey,
    settings: cur.settings.map(s=>({
      index:s.index, name:s.name, activateKey:s.activateKey, activateMode:s.activateMode,
      sensitivity:s.sensitivity, yxRatio:s.yxRatio, boost:s.boost, invert:s.invert,
      curve:s.curve, leftStick:s.leftStick, useTranslator:s.useTranslator,
      turnAssistMode:s.turnAssistMode, turnAssistKey:s.turnAssistKey,
      deadzone:s.deadzone, swapSticks:s.swapSticks,
      keyboardSticks:s.keyboardSticks, primary:s.primary, secondary:s.secondary,
    })),
  };
}

async function syncDevice(){
  status(`<span class="spinner"></span>Syncing from device — this reads every config (paced)…`,"warn");
  try{ await API.post("/api/sync"); status("Sync started — watch the log.","ok"); }
  catch(e){ status("Sync failed: "+e.message,"err"); }
}
function newConfig(){
  status("New-config: clone an existing config from the library and edit it (device has no spare slots).","warn");
}

// ---------------------------------------------------------------- websocket
function connectWS(){
  let ws;
  try{ ws=new WebSocket((location.protocol==="https:"?"wss":"ws")+"://"+location.host+"/ws"); }
  catch(_){ return; }
  ws.onmessage=(e)=>{
    const m=JSON.parse(e.data);
    if(m.type==="log"){ $("logMini").textContent=m.msg;
      if(/synced \d+\//.test(m.msg)) loadLibrary(); }
    if(m.type==="status"){ refreshStatus(); }
    if(m.type==="activity"){ pushActivity(m.input); }
  };
  ws.onclose=()=>setTimeout(connectWS,3000);
}

// ---------------------------------------------------------------- util
function esc(s){ return (s==null?"":String(s)).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }
function buildStatic(){ updateBeaconSwatchSafe(); }
function updateBeaconSwatchSafe(){ /* filled once editor opens */ }

boot();
