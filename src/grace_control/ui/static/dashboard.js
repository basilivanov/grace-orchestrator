
const STY={ready:{bg:'var(--ready)',label:'Ready'},running:{bg:'var(--running)',label:'Running'},accepted:{bg:'var(--accepted)',label:'Accepted'},merged:{bg:'var(--merged)',label:'Merged'},rejected:{bg:'var(--rejected)',label:'Rejected'},failed:{bg:'var(--failed)',label:'Failed'},cancelled:{bg:'var(--cancelled)',label:'Cancelled'}};
let data={features:[],workers:[],stats:{}},selFid=null,selPid=null,actTab='ov',lastPktState={},ws,mobile=window.innerWidth<700;

function $(id){return document.getElementById(id)}
async function load(){
  const r=await fetch('/api/dashboard');data=await r.json();
  updateStats();renderFeatures();
  if(selFid){renderWaves(selFid);updateMobileCrumb(2)}
  if(selPid){renderInspector(selPid);updateMobileCrumb(3)}
}
function updateStats(){
  const s=data.stats;
  $('s-ready').querySelector('.val').textContent=s.ready||0;
  $('s-running').querySelector('.val').textContent=s.running||0;
  $('s-merged').querySelector('.val').textContent=s.merged||0;
  $('s-failed').querySelector('.val').textContent=(s.failed||0)+(s.rejected||0);
  $('s-workers').querySelector('.val').textContent=s.workers||0;
  $('tick').textContent=new Date().toLocaleTimeString();
}

function renderFeatures(){
  $('pl').innerHTML=data.features.length
    ?data.features.map(f=>{
      const st={};let bad=0;
      (f.waves||[]).forEach(w=>w.packets.forEach(p=>{st[p.state]=(st[p.state]||0)+1;if(p.state==='failed'||p.state==='rejected')bad++}));
      const wcnt=f.waves.length,pcnt=(f.waves||[]).reduce((a,w)=>a+w.packets.length,0);
      return `<div class="fcard${f.id===selFid?' sel':''}" onclick="selFeature('${f.id}')">
        <div class=ftitle>${f.title}</div>
        <div class=fmeta>${wcnt} waves · ${pcnt} packets</div>
        <div class=fstats>${Object.entries(st).map(([k,v])=>{
          const s=STY[k]||{bg:'var(--gr)'};
          return`<span class=fstat style="background:${s.bg}20;color:${s.bg};border:1px solid ${s.bg}40">${s.label}: ${v}</span>`
        }).join('')}</div>
        ${bad>0?`<span class=needs-attn>Needs attention: ${bad} failed</span>`:''}
      </div>`;
    }).join('')
    :'<div class=empt>No features. Run: grace architect plan feature.yaml</div>';
}

function selFeature(fid){
  selFid=fid;selPid=null;
  if(mobile){navStack=['features'];updateMobileCrumb(2)}
  renderFeatures();renderWaves(fid);
  $('pc').classList.add('active');$('pr').innerHTML='';
  if(mobile){$('pl').classList.remove('active');$('pc').classList.add('active');$('pr').classList.remove('active')}
}
function renderWaves(fid){
  const f=data.features.find(x=>x.id===fid);
  if(!f){$('pc').innerHTML='<div class=empt>Feature not found</div>';return}
  const pcnt=(f.waves||[]).reduce((a,w)=>a+w.packets.length,0);
  let h=`<div class=ctr-hdr><div class=fname>${f.title}</div><div class=fid>${f.id}</div><div class=fsum>${f.waves.length} waves · ${pcnt} packets</div></div>`;
  f.waves.forEach(w=>{
    h+=`<div class=wcard><div class=whead><span class=wname>Wave ${w.order}: ${w.title}</span><span style=font-size:11px;color:var(--gr)>${w.packets.length} pkt</span></div>`;
    w.packets.forEach(p=>{
      const s=STY[p.state]||{bg:'var(--gr)',label:p.state};
      h+=`<div class="pcard${p.id===selPid?' sel':''}" onclick="selPacket('${p.id}')">
        <span class=pdot style=background:${s.bg}></span>
        <div class=pinfo><div class=ptitle>${p.title||p.id.slice(-30)}</div><div class=pmeta>${p.id}</div></div>
        <span class=pbadge style="background:${s.bg}20;color:${s.bg};border:1px solid ${s.bg}40">${s.label} ${p.attempt_count}/${p.max_attempts}</span>
      </div>`;
    });
    h+='</div>';
  });
  $('pc').innerHTML=h;
}
function selPacket(pid){
  selPid=pid;
  if(mobile){navStack=['features','waves'];updateMobileCrumb(3)}
  renderWaves(selFid);renderInspector(pid);
  if(mobile){$('pc').classList.remove('active');$('pr').classList.add('active')}
}
function renderOverview(d,s){
  const lr=d.runs&&d.runs.length?d.runs[d.runs.length-1]:null;
  const next=d.state==='ready'?'Worker claim':d.state==='running'?'Agent executing':d.state==='accepted'?'Auto-merge':d.state==='failed'?'Manual retry':d.state==='rejected'?'Auto-retry':'Complete';
  return `<div style=font-size:12px;line-height:2>
    <b>Status:</b> <span style=color:${s.bg}>${s.label}</span><br>
    ${lr?`<b>Last run:</b> ${lr.status}${lr.duration_ms?` · ${(lr.duration_ms/1000).toFixed(1)}s`:''}<br>`:''}
    ${lr&&lr.evidence_path?`<b>Evidence:</b> <span style=font-family:var(--mono);font-size:10px>${lr.evidence_path}</span><br>`:''}
    <b>Runs:</b> ${d.runs?d.runs.length:0} &nbsp; <b>Next:</b> ${next}
  </div>`;
}
function renderRuns(d){
  if(!d.runs||!d.runs.length)return'<div class=empt>No runs</div>';
  return d.runs.map(r=>`<div class=run-card onclick="loadRunArts('${d.id}','${r.id}')">
    <b>Run ${r.run_number}</b> <span style=color:${STY[r.status]?.bg||'var(--gr)'}>${r.status}</span>
    ${r.duration_ms?` · ${(r.duration_ms/1000).toFixed(1)}s`:''}
    ${r.evidence_path?`<br><span style=font-size:10px;color:var(--gr)>${r.evidence_path}</span>`:''}
  </div>`).join('');
}
async function renderInspector(pid){
  let h='<div class=insp>';
  try{
    const r=await fetch(`/api/packets/${pid}`);const d=(await r.json()).data;
    // Skip re-render if nothing changed (prevents tab reset)
    if(lastPktState[pid]&&lastPktState[pid].state===d.state&&lastPktState[pid].att===d.attempt_count){
      restoreTab();return
    }
    lastPktState[pid]={state:d.state,att:d.attempt_count};
    const s=STY[d.state]||{bg:'var(--gr)',label:d.state};
    h+=`<h3>${d.title||'Packet'}</h3>
    <span class=state-badge style="background:${s.bg}20;color:${s.bg};border:1px solid ${s.bg}40">${s.label}</span>
    <div class=meta>
      <b>Attempt:</b> ${d.attempt_count}/${d.max_attempts} &nbsp; <b>Profile:</b> ${d.acceptance_profile}<br>
      <b>Feature:</b> <span style=font-family:var(--mono);font-size:10px>${d.feature_id}</span> <button class=copy-btn onclick="navigator.clipboard.writeText('${d.feature_id}')">copy</button><br>
      <b>Wave:</b> <span style=font-family:var(--mono);font-size:10px>${d.wave_id}</span>
    </div>`;

    // Timeline
    const phases=['ready','claimed','running','evidence','accepted','merged'];
    const idx=phases.indexOf(d.state);
    const activeIdx=idx>=0?idx:(d.state==='rejected'||d.state==='cancelled'?4:d.state==='failed'?3:0);
    h+='<div class=tl>';
    phases.forEach((ph,i)=>{
      let cls='next';
      if(i<activeIdx&&d.state!=='failed'&&d.state!=='rejected'&&d.state!=='cancelled')cls='done';
      if(i===activeIdx&&d.state!=='failed'&&d.state!=='rejected'&&d.state!=='cancelled')cls='now';
      if((d.state==='failed'||d.state==='rejected'||d.state==='cancelled')&&i===activeIdx)cls='fail';
      h+=`<div class="tl-step ${cls}"><span class=tl-dot></span><span class=tl-label>${ph}</span></div>`;
    });
    h+='</div>';

    // Tabs + content
    h+=`<div class=tabs>${[['ov','Overview'],['runs','Runs'],['events','Events'],['arts','Artifacts']].map(([n,l])=>`<button class="tab${actTab===n?' act':''}" onclick="swTab(event,'${n}','${pid}')">${l}</button>`).join('')}</div>`;
    h+=`<div class="tc" id=tc-ov>${renderOverview(d)}</div>`;
    h+=`<div class="tc hidden" id=tc-runs>${renderRuns(d)}</div>`;
    h+=`<div class="tc hidden" id=tc-events><div class=empt>Loading...</div></div>`;
    h+=`<div class="tc hidden" id=tc-arts><div class=empt>Select a run to view artifacts</div></div>`;
  }catch(e){h+='<div class=empt>Error loading packet</div>'}
  h+='</div>';$('pr').innerHTML=h;
  // Show active tab after DOM is populated
  const atc=document.getElementById('tc-'+actTab);
  if(atc)atc.classList.remove('hidden');
  restoreTab();
}
async function swTab(e,name,pid){
  actTab=name;
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('act'));
  e.target.classList.add('act');
  document.querySelectorAll('.tc').forEach(t=>t.classList.add('hidden'));
  const el=document.getElementById('tc-'+name);if(el)el.classList.remove('hidden');
  if(name==='events'&&pid)await loadEvents(pid);
  if(name==='arts'&&pid){const d=(await(await fetch(`/api/packets/${pid}`)).json()).data;if(d.runs&&d.runs.length)loadRunArts(pid,d.runs[d.runs.length-1].id);else el.innerHTML='<div class=empt>No runs</div>'}
}
async function loadEvents(pid){
  const el=$('tc-events');el.innerHTML='Loading...';
  const r=await fetch(`/api/events?entity_type=packet&entity_id=${pid}`);
  const evs=(await r.json()).data;
  el.innerHTML=evs.length?`<div class=ev-list>${evs.map(e=>`<div class=ev-item><span class=ev-time>${new Date(e.timestamp).toLocaleTimeString()}</span><span class=ev-type>${e.event_type}</span><div><span class=ev-detail>${JSON.stringify(e.payload||{}).slice(0,120)}</span><br><span class=ev-raw>${e.trace_id||''}</span></div></div>`).join('')}</div>`:'<div class=empt>No events yet</div>';
}
async function loadRunArts(pid,runId){
  const el=$('tc-arts');el.style.display='block';
  try{
    const r=await fetch(`/api/packets/${pid}/runs/${runId}/artifacts`);
    const files=(await r.json()).data;
    if(!files.length){el.innerHTML='<div class=empt>No artifacts</div>';return}
    el.innerHTML=`<div>${files.map(f=>`<div class=art-item onclick="viewArt('${pid}','${runId}','${f.name}')">${f.type==='image'?'🖼':f.type==='log'?'📄':'📋'} ${f.name} <span style=color:var(--gr);font-size:10px>${(f.size/1024).toFixed(1)}KB</span></div>`).join('')}</div>`;
  }catch(e){el.innerHTML='<div class=empt>Error</div>'}
}
async function viewArt(pid,runId,path){
  const r=await fetch(`/api/packets/${pid}/runs/${runId}/artifacts/file?path=${encodeURIComponent(path)}&tail=200`);
  const c=await r.text();
  $('tc-arts').innerHTML=`<div style="font-size:11px;color:var(--gr);margin-bottom:8px">📄 ${path} · ${c.split('\\n').length} lines <a href="#" onclick="swTab({target:document.querySelector('.tab:nth-child(4)')},'arts','${pid}');loadRunArts('${pid}','${runId}')" style=color:var(--accent)>← back</a></div><div class=log-box>${c.replace(/&/g,'&amp;').replace(/</g,'&lt;')}</div><button class=copy-btn-lg onclick="navigator.clipboard.writeText(this.previousSibling.textContent)">Copy</button>`;
}
function restoreTab(){
  if(actTab==='events'&&selPid)loadEvents(selPid);
  if(actTab==='arts'&&selPid){
    fetch(`/api/packets/${selPid}`).then(r=>r.json()).then(d=>{
      const runs=d.data.runs||[];
      if(runs.length)loadRunArts(selPid,runs[runs.length-1].id);
      else document.getElementById('tc-arts').innerHTML='<div class=empt>No runs</div>';
    });
  }
}
let navStack=[];
function navBack(){
  if(navStack.length<=1){navStack=[];selFid=null;selPid=null;resetMobile();return}
  navStack.pop();
  if(navStack.length===1){selFid=null;selPid=null;resetMobile()}
  else if(navStack.length===2){selPid=null;$('pc').classList.add('active');$('pr').classList.remove('active');$('pr').innerHTML='';updateMobileCrumb(2)}
}
function resetMobile(){
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  $('pl').classList.add('active');$('pc').innerHTML='';$('pr').innerHTML='';updateMobileCrumb(1);
}
function updateMobileCrumb(lvl){
  if(!mobile)return;
  if(!selFid){$('crumb').textContent='Features';return}
  const f=data.features.find(x=>x.id===selFid);
  if(!selPid){$('crumb').textContent=`Features / ${f?.title||'...'}`;return}
  const fp=f?.waves?.flatMap(w=>w.packets).find(p=>p.id===selPid);
  $('crumb').textContent=`${f?.title||'...'} / ${fp?.title||'...'}`;
}
function toggleLegend(){$('leg').classList.toggle('open');$('ov').classList.toggle('open')}
function connectWS(){
  ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws`);
  ws.onopen=()=>{$('ws-stat').innerHTML='<span class=ws-dot style=background:var(--g)></span>Live'};
  ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.type==='state_change')load()};
  ws.onclose=()=>{setTimeout(connectWS,2000);$('ws-stat').innerHTML='<span class=ws-dot style=background:var(--r)></span>Offline'};
}
load();connectWS();setInterval(load,5000);
window.addEventListener('resize',()=>{mobile=window.innerWidth<700});
