let state={view:'dashboard',filter:'all',detailMode:false,expFeat:{},expWave:{},tab:{},tabData:{},fileView:{},paused:false,refCount:15,data:null};
const $=s=>document.querySelector(s);
const SC={running:'run',merged:'done',done:'done',failed:'fail',rejected:'fail',blocked:'block',blocked_recoverable:'block',blocked_final:'block',ready:'queue',draft:'queue',queued:'queue',accepted:'done',cancelled:'queue'};
const SL={running:'Running',merged:'Merged',done:'Done',failed:'Failed',rejected:'Rejected',blocked:'Blocked',ready:'Ready',draft:'Draft',queued:'Queued',accepted:'Accepted',cancelled:'Cancelled'};
const TABS=['spec','events','sessions','runs','logs','artifacts','evidence'];
const TLAB={spec:'Spec',events:'Events',sessions:'Sessions',runs:'Runs',logs:'Logs',artifacts:'Artifacts',evidence:'Evidence'};
const fmtDur=ms=>{if(ms==null)return'—';if(ms<0)ms=0;if(ms<1000)return ms+'ms';if(ms<60000)return(ms/1000).toFixed(0)+'s';const m=Math.floor(ms/60000),s=Math.floor((ms%60000)/1000);return m+'m'+(s?' '+s+'s':'')};
const fmtTime=iso=>{if(!iso)return'—';try{return new Date(iso).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}catch{return'—'}};
const fmtDate=iso=>{if(!iso)return'—';try{const d=new Date(iso);return d.toLocaleDateString('en-GB',{month:'short',day:'numeric'})+' '+fmtTime(iso)}catch{return'—'}};
const esc=s=>{if(!s)return'';const d=document.createElement('div');d.appendChild(document.createTextNode(String(s)));return d.innerHTML};
const icons={done:'✓',running:'⟳',failed:'✗',skipped:'—',pending:'○'};

function toast(msg,type='info'){const c=$('#toast-cont')||(()=>{const d=document.createElement('div');d.id='toast-cont';d.className='toast';document.body.appendChild(d);return d;})();const e=document.createElement('div');e.className='toast-item '+type;e.textContent=msg;c.appendChild(e);setTimeout(()=>{e.style.opacity='0';e.style.transition='opacity .3s';setTimeout(()=>e.remove(),300)},2500);}

function switchView(v){
  state.view=v;$('#topnav').querySelectorAll('a').forEach(a=>a.classList.toggle('on',a.textContent.trim().toLowerCase().includes(v)));
  if(v==='dashboard'){$('#bizbar').innerHTML='';loadData();if(window.logInt){clearInterval(window.logInt);window.logInt=null;}}
  else if(v==='archive'){$('#bizbar').innerHTML='';loadArchived();if(window.logInt){clearInterval(window.logInt);window.logInt=null;}}
  else if(v==='logs'){$('#bizbar').innerHTML='';initLogViewer();}
  else if(v==='new'){$('#bizbar').innerHTML='';$('#board').innerHTML=`<div style="padding:16px;display:flex;flex-direction:column;gap:10px;max-width:700px"><textarea id="biz-input" style="width:100%;min-height:180px;padding:10px;background:var(--bg1);border:1px solid var(--bd);border-radius:6px;color:var(--t1);font-size:13px;font-family:inherit;resize:vertical;outline:none" placeholder="Describe your business feature in detail..."></textarea><div style="display:flex;gap:8px;align-items:center"><button id="biz-btn" onclick="submitBiz()" style="padding:8px 20px;border-radius:6px;border:none;background:var(--blue);color:#fff;font-size:13px;font-weight:600;cursor:pointer">Submit Feature</button><span id="biz-status" style="font-size:11px;color:var(--t3)"></span></div></div>`;if(window.logInt){clearInterval(window.logInt);window.logInt=null;}}
}
function toggleDetail(){state.detailMode=!state.detailMode;renderDashboard();}

function renderDashboard(){
  const fs=(state.data?.features||[]).filter(f=>!f.is_archived);
  if(!fs.length){$('#board').innerHTML='<div class="empty">No features</div>';return;}
  let html='';
  fs.forEach(f=>{
    const expF=state.expFeat[f.id];let waveHtml='';
    if(expF){(f.waves||[]).forEach(w=>{
      const expW=state.expWave[w.id];let pktHtml='';
      if(expW){(w.packets||[]).forEach(p=>{pktHtml+=renderPktCard(p);});}
      const pkts=w.packets||[],done=pkts.filter(p=>p.state==='merged'||p.state==='accepted').length,fail=pkts.filter(p=>['failed','rejected'].includes(p.state)).length,run=pkts.filter(p=>p.state==='running').length,total=pkts.length;
      const sL=w.status||'NOT_STARTED',sC=sL==='COMPLETED'?'var(--green)':sL==='IN_PROGRESS'?'var(--blue)':'var(--t3)';
      waveHtml+=`<div class="wave-card"><div class="wave-h" onclick="togWave('${w.id}')"><span class="arrow ${expW?'open':''}">›</span><div class="wave-info"><div>${esc(w.title||w.id)}</div><div class="wave-sub"><span style="color:${sC};font-weight:700">${sL}</span><span>${total} packets</span>${done?`<span style="color:var(--green)">${done} done</span>`:''}${fail?`<span style="color:var(--red)">${fail} failed</span>`:''}${run?`<span style="color:var(--blue)">${run} running</span>`:''}</div></div><span class="wave-meta">${w.id}</span></div>${expW?pktHtml:''}</div>`;});}
    const fAttn=f.attention_count||0,fCr=f.created_at?fmtDate(f.created_at):'',fSt=f.status||'NOT_STARTED',fSc=fSt==='COMPLETED'?'var(--green)':fSt==='IN_PROGRESS'||fSt==='ACTIVE'?'var(--blue)':'var(--t3)';
    html+=`<div class="feat-card"><div class="feat-h" onclick="togFeat('${f.id}')"><span class="arrow ${expF?'open':''}">›</span><div class="feat-info"><div class="feat-title">${esc(f.title||f.id)}</div><div class="feat-sub"><span style="color:${fSc};font-weight:700">${fSt}</span><span>${f.wave_count||0} waves</span><span>${f.total_packets||0} packets</span>${fAttn?`<span style="color:var(--red)">${fAttn} attention</span>`:''}${fCr?`<span style="color:var(--t3)">created ${fCr}</span>`:''}<span style="color:var(--t3);font-family:var(--mono)">${esc(f.id)}</span></div></div><div class="feat-actions"><button class="feat-act danger" onclick="event.stopPropagation();archiveFeat('${f.id}')" title="Archive">✕</button></div></div>${expF?`<div class="feat-body">${waveHtml}</div>`:''}</div>`;
  });
  $('#board').innerHTML=html;
}

function togFeat(id){state.expFeat[id]=!state.expFeat[id];renderDashboard();}
function togWave(id){state.expWave[id]=!state.expWave[id];renderDashboard();}

function renderPktCard(p){
  const sc=SC[p.state]||'queue',sel=state.sel===p.id,pipe=p.pipeline?.stages||[],cur=pipe.find(s=>s.status==='running')||pipe.find(s=>s.status==='failed');
  const dur=p.duration_seconds?fmtDur(p.duration_seconds*1000):'—',stime=p.started_at?fmtTime(p.started_at):'';
  const detHtml=sel?renderPktDetail(p):'';
  const sub=[p.state,cur?`at ${cur.key}`:'',p.attempt_count>1?`attempt ${p.attempt_count}/${p.max_attempts}`:''].filter(Boolean).join(' · ');
  const extra=state.detailMode?`<div style="font-size:8px;color:var(--t3);font-family:var(--mono);margin-top:1px">${p.id} · ${p.slug||''}</div>`:'';
  return`<div class="pkt-card ${sel?'sel':''}"><div class="pkt-h" onclick="selPkt('${p.id}')"><div class="pkt-strip s-${sc}"></div><div class="pkt-info"><div class="pkt-top"><span class="pkt-id">${p.id}</span><span class="pkt-name">${esc(p.title)}</span><span class="badge b-${sc}">${SL[p.state]||p.state}</span></div><div class="pkt-sub">${sub}</div>${extra}</div><div class="pkt-mets">${stime?`<div class="pkt-met"><span class="pkt-met-l">Start</span><span class="pkt-met-v">${stime}</span></div>`:''}<div class="pkt-met"><span class="pkt-met-l">Dur</span><span class="pkt-met-v">${dur}</span></div></div></div><div class="pkt-detail">${detHtml}</div></div>`;
}

function selPkt(id){
  if(state.sel===id){state.sel=null;delete state.tabData[id];renderDashboard();return;}
  state.sel=id;delete state.tabData[id];delete state.tab[id];renderDashboard();
  loadDetail(id).then(d=>{if(d&&state.sel===id)mergeDetail(id,d);});
  const cached=loadDetailCached(id);if(cached)mergeDetail(id,cached);
}

function renderPktDetail(p){
  let hier='';const items=[];
  if(p.feature)items.push(['F',p.feature.title||p.feature.id]);
  if(p.wave)items.push(['W',p.wave.title||p.wave.id]);items.push(['P',p.title||p.id]);
  if(items.length>1){hier='<div style="display:flex;gap:4px;align-items:center;padding:6px 10px 0;font-size:9px;flex-wrap:wrap">';items.forEach((h,i)=>{if(i>0)hier+='<span style="color:var(--t3)">›</span>';hier+=`<span style="color:${i===items.length-1?'var(--blue)':'var(--t2)'};font-weight:${i===items.length-1?'700':'500'}"><span style="color:var(--t3);font-weight:400;margin-right:2px">${h[0]}:</span>${esc(h[1])}</span>`;});hier+='</div>';}
  const pipe=p.pipeline?.stages||[];let pb='';
  if(pipe.length){pb='<div class="pblocks">'+pipe.map(s=>{
    const cls=s.status==='done'?'done':s.status==='running'?'running':s.status==='failed'?'failed':s.status==='skipped'?'skipped':'pending';
    const lbl=s.label?esc(s.label.split(' ').slice(0,2).join(' ')):s.key;
    // Compute live elapsed time for running stages
    let dur;
    if(s.status==='running'&&s.started_at){const diff=Date.now()-new Date(s.started_at).getTime();dur=fmtDur(Math.max(diff,0));}
    else dur=fmtDur(Math.max(s.duration_ms||0,0));
    const st=s.started_at?fmtTime(s.started_at):'',et=s.finished_at?fmtTime(s.finished_at):'',tab=s.target_tab||'spec';
    return`<div class="pblock ${cls}" onclick="event.stopPropagation();stab('${p.id}','${tab}')" title="${esc(s.label)}"><span class="pbl-i ${cls}">${icons[cls]||'○'}</span><span class="pbl-l">${lbl}</span>${st?`<span class="pbl-st ${cls}">${st}</span>`:''}${et?`<span class="pbl-et ${cls}">${et}</span>`:''}<span class="pbl-t ${cls}">${dur}</span></div>`;}).join('')+'</div>';}
  const t=state.tab[p.id]||'spec',tabsH=TABS.map(x=>`<div class="dtab ${t===x?'on':''}" onclick="stab('${p.id}','${x}')">${TLAB[x]||x}</div>`).join('');
  return hier+pb+`<div class="dtabs">${tabsH}</div><div class="dcont" id="dcont-${p.id}">${renderTabContent(p,t)}</div>`;
}

function renderTabContent(p,tab){
  if(tab==='spec')return renderSpecTab(p);if(tab==='events')return renderEventsTab(p);
  if(tab==='sessions')return renderSessionsTab(p);if(tab==='runs')return renderRunsTab(p);
  if(tab==='logs')return renderLogsTab(p);if(tab==='artifacts')return renderArtifactsTab(p);
  if(tab==='evidence')return renderEvidenceTab(p);return'<div class="empty">Unknown tab</div>';
}
function renderSpecTab(p){
  const pk=p.packet||{},sm=p.state_machine||{},steps=sm.steps||[];
  const rows=[['ID',p.id],['Title',p.title],['State',p.state],['Profile',pk.acceptance_profile||p.acceptance_profile||'—'],['Attempts',`${p.attempt_count||0} / ${p.max_attempts||0}`],['Created',fmtDate(p.created_at)],['Updated',fmtDate(p.updated_at)]];
  let html='<div class="spec-grid">'+rows.map(r=>`<span class="sk">${r[0]}</span><span class="sv">${r[1]}</span>`).join('')+'</div>';
  if(steps.length){html+='<div style="margin-top:8px;font-size:10px;font-weight:700;color:var(--t3);margin-bottom:4px">State Machine</div><div style="display:flex;gap:5px;flex-wrap:wrap">'+steps.map(s=>{const c=s.state==='done'?'var(--green)':s.state==='running'?'var(--blue)':'var(--t3)';return`<div style="background:var(--bg1);border:1px solid var(--bd);border-radius:4px;padding:4px 7px;min-width:70px"><div style="font-size:9px;font-weight:700;color:${c};text-transform:uppercase">${esc(s.label)}</div><div style="font-size:8px;color:var(--t3)">${fmtTime(s.time)}</div>${s.meta?`<div style="font-size:8px;color:var(--t2)">${esc(s.meta)}</div>`:''}</div>`;}).join('')+'</div>';}
  return html;
}
function renderEventsTab(p){
  const ev=state.tabData[p.id]?.events;if(ev===null)return'<div class="empty">No events</div>';
  if(ev===undefined){loadTabData(p.id,'events');return'<div class="loading">Loading events</div>';}
  const events=ev.events||[];if(!events.length)return'<div class="empty">No events</div>';
  return'<table class="etbl"><thead><tr><th>Time</th><th>Event</th><th>Detail</th></tr></thead><tbody>'+events.map(e=>{const p=e.payload||{},extra=p.from?`${p.from}→${p.to}`:e.reason||'';return`<tr><td class="ev-t">${fmtTime(e.timestamp)}</td><td class="ev-e">${esc(e.event_type)}</td><td class="ev-d">${esc(extra)}</td></tr>`;}).join('')+'</tbody></table>';
}
function renderSessionsTab(p){
  const ss=state.tabData[p.id]?.sessions;if(ss===null)return'<div class="empty">No sessions</div>';
  if(ss===undefined){loadTabData(p.id,'sessions');return'<div class="loading">Loading sessions</div>';}
  const list=ss.sessions||ss||[];if(!list.length)return'<div class="empty">No sessions</div>';
  return'<div class="slist">'+list.map(s=>{const sid=s.id||s.session_id||'—',st=s.status||'—',md=s.model||s.agent||'—',ti=s.tokens_in||s.tokensUsed||0,to=s.tokens_out||0;return`<div class="sitem"><span class="sid">${esc(sid)}</span><span class="sst sst-${st}">${st}</span><span class="smd">${esc(md)}</span><span class="stk">${ti}→${to}</span></div>`;}).join('')+'</div>';
}
function renderRunsTab(p){
  const rs=p.runs_summary||[];if(!rs.length)return'<div class="empty">No runs</div>';
  return'<table class="etbl"><thead><tr><th>Run</th><th>Status</th><th>Executor</th><th>Model</th><th>Duration</th></tr></thead><tbody>'+rs.map(r=>`<tr style="cursor:pointer" onclick="runExpand('${p.id}',${r.run_number},'${esc(r.run_id.replace(p.id+'-',''))}')"><td class="ev-t" style="font-family:var(--mono);color:var(--purple);font-weight:600">#${r.run_number}</td><td><span class="badge b-${SC[r.status]||'queue'}">${r.status||'?'}</span></td><td class="ev-d">${r.executor_id||'—'}</td><td class="ev-d" style="font-size:9px;font-family:var(--mono)">${r.model||'—'}</td><td class="ev-t">${fmtDur(r.duration_ms)}</td></tr>`+runDetailRow(p,r)).join('')+'</tbody></table>';
}
function runDetailRow(p,r){
  const key=p.id+'.r'+r.run_number;if(state.tabData[key]===undefined)return'';
  const data=state.tabData[key];if(!data)return'<tr><td colspan="5"><div class="empty">No data</div></td></tr>';
  const rj=data.result_json||{},leg=rj.legacy_result||{},prompt=data.prompt||rj.prompt||leg.prompt||'';
  const stderr=(state.liveLogs?.[key]?.stderr)??(leg.stderr||'');
  const stdout=(state.liveLogs?.[key]?.stdout)??(leg.stdout||'');
  const cmd=data.command_preview||rj.command_preview||[];
  const acc=rj.acceptance_report||{};const stages=acc.stages||[];
  const exitCodes=[];stages.forEach(s=>(s.commands||[]).forEach(c=>{if(c.exit_code!==undefined)exitCodes.push(c.exit_code);}));
  const finalExit=leg.exit_code!==undefined?leg.exit_code:(exitCodes.length?Math.max(...exitCodes):null);
  const isLive=r.is_running||false;
  let h='<td colspan="5"><div style="padding:4px;display:flex;flex-direction:column;gap:3px">';
  if(isLive)h+=`<div style="display:flex;gap:4px;align-items:center;margin-bottom:2px"><span style="color:var(--red);font-size:8px">🔴</span><span style="color:var(--red);font-size:9px;font-weight:700">LIVE</span><span style="font-size:9px;color:var(--t3)">Agent is running — logs update every 2s</span></div>`;
  if(finalExit!==null)h+=`<div style="font-size:11px;color:var(--t3);margin-bottom:4px">Exit code: <span style="color:${finalExit===0?'var(--green)':'var(--red)'};font-weight:700;font-size:13px">${finalExit}${finalExit===0?' ✓':' ✗'}</span></div>`;
  if(cmd.length){const c=Array.isArray(cmd)?cmd.join(' '):String(cmd);h+=`<div style="font-size:11px;color:var(--t3);margin-bottom:4px">Command: <span style="color:var(--green);font-family:var(--mono);font-size:11px">${esc(c)}</span></div>`;}
  if(prompt)h+=`<details><summary style="font-size:11px;color:var(--blue);cursor:pointer;margin-bottom:2px">Prompt (${prompt.length} chars)</summary><div style="background:var(--bg1);border:1px solid var(--bd);border-radius:4px;padding:6px;margin-top:2px;font-family:var(--mono);font-size:11px;color:var(--t2);white-space:pre-wrap;max-height:250px;overflow-y:auto">${esc(prompt)}</div></details>`;
  if(stderr)h+=`<details${isLive?' open':''}><summary style="font-size:11px;color:var(--red);cursor:pointer;margin-bottom:2px">${isLive?'🔴 ':'Stderr'}Stderr${isLive?` <span style="font-weight:400;font-size:9px">(${stderr.split('\\n').length||0} lines)</span>`:''}</summary><div class="logs" style="max-height:350px;background:var(--bg0);border-color:var(--red)">${esc(stderr.slice(-5000))}</div></details>`;
  if(stdout)h+=`<details${isLive?' open':''}><summary style="font-size:11px;color:var(--green);cursor:pointer;margin-bottom:2px">${isLive?'🔴 ':'Stdout'}Stdout${isLive?` <span style="font-weight:400;font-size:9px">(${stdout.split('\\n').length||0} lines)</span>`:''}</summary><div class="logs" style="max-height:350px;background:var(--bg0);border-color:var(--green)">${esc(stdout.slice(-5000))}</div></details>`;
  if(!h.includes('details'))h+='<div class="empty" style="padding:10px">No data</div>';h+='</div></td>';return'<tr>'+h+'</tr>';
}
async function runExpand(id,num,suffix){
  const key=id+'.r'+num;
  if(state.tabData[key]){delete state.tabData[key];stopLiveLog(key);const p=getPkt(id);if(p)updateCont(id);return;}
  state.tabData[key]=undefined;const p=getPkt(id);if(p)updateCont(id);
  try{const r=await fetch(apiUrl(`/api/admin/packet/${id}/runs/${suffix}`));state.tabData[key]=await r.json();
    // If run is running, start live log polling
    const runData=state.tabData[key];
    if(runData&&runData.run&&runData.run.is_running){
      if(!state.liveLogs)state.liveLogs={};
      if(!state.liveTimers)state.liveTimers={};
      state.liveLogs[key]=state.liveLogs[key]||{stderr:'',stdout:''};
      if(state.liveTimers[key])clearInterval(state.liveTimers[key]);
      state.liveTimers[key]=setInterval(async()=>{
        try{
          const pkt=getPkt(id);if(!pkt)return;
          const rs=await fetch(apiUrl(`/api/admin/packet/${id}/runs/${suffix}/logs?stream=stderr&tail=200`));
          const rd=await rs.json();if(state.liveLogs)state.liveLogs[key]={stderr:(rd.lines||[]).join('\\n'),stdout:state.liveLogs[key]?.stdout||''};
          const os=await fetch(apiUrl(`/api/admin/packet/${id}/runs/${suffix}/logs?stream=stdout&tail=200`));
          const od=await os.json();if(state.liveLogs)state.liveLogs[key]={stderr:state.liveLogs[key]?.stderr||'',stdout:(od.lines||[]).join('\\n')};
          const p2=getPkt(id);if(p2)updateCont(id);
  }catch(e){if(state.view==='logs')$('#board').innerHTML=`<div style="padding:20px;text-align:center;color:var(--t3);font-size:11px">Failed to load logs: ${esc(e.message||'unknown')}</div>`;}
      },2000);
    }
  }catch{state.tabData[key]=null;}if(p)updateCont(id);
}
function stopLiveLog(key){
  if(state.liveTimers&&state.liveTimers[key]){clearInterval(state.liveTimers[key]);delete state.liveTimers[key];}
}
function renderLogsTab(p){
  const ld=state.tabData[p.id]?.logs;if(ld===null)return'<div class="empty">No logs</div>';
  if(ld===undefined){loadTabData(p.id,'logs');return'<div class="loading">Loading logs</div>';}
  const lines=ld.lines||[];if(!lines.length)return'<div class="empty">No logs</div>';
  return'<div class="logs">'+lines.map(l=>{if(typeof l==='string')return`<div class="ll"><span class="lm">${esc(l)}</span></div>`;return`<div class="ll"><span class="lt">${l.timestamp||''}</span><span class="lv ${l.level||''}">${l.level||''}</span><span class="lm">${esc(l.message||l.text||'')}</span></div>`;}).join('')+'</div>';
}
function renderArtifactsTab(p){
  const ad=state.tabData[p.id]?.artifacts;if(ad===null)return'<div class="empty">No artifacts</div>';
  if(ad===undefined){loadTabData(p.id,'artifacts');return'<div class="loading">Loading artifacts</div>';}
  const tree=ad.tree||[],evPath=ad.evidence_path||'';
  if(!tree.length)return'<div class="empty">No artifacts</div>';
  function rt(nodes,depth){
    let h='';nodes.forEach(n=>{const pad='padding-left:'+(depth*16)+'px';if(n.type==='dir'){h+=`<div class="af" style="${pad}"><span style="color:var(--yellow)">▸</span><span class="an">${esc(n.name)}/</span></div>`;if(n.children)h+=rt(n.children,depth+1);}else{const sel=state.filePath===n.name;h+=`<div class="af" style="${pad}" onclick="openFile('${p.id}','${esc(n.name)}')" title="Click to view"><span style="color:${sel?'var(--green)':'var(--t3)'}">·</span><span class="${sel?'sel':''}">${esc(n.name)}</span><span class="as">${fmtSize(n.size)}</span></div>`;}});return h;}
  let viewer='';const fv=state.fileView&&state.fileView[state.sel];
  if(fv&&fv.data!==undefined){
    const ext=fv.path.split('.').pop().toLowerCase();let content='';
    if(ext==='json')content=renderJsonTree(fv.data);
    else if(ext==='patch')content=`<div class="fvc" style="color:var(--green)">${esc(fv.data)}</div>`;
    else if(['png','jpg','jpeg','gif','svg','webp'].includes(ext))content=`<div class="fvc"><img src="data:image/${ext==='svg'?'svg+xml':ext}" style="max-width:100%;max-height:300px"></div>`;
    else content=`<div class="fvc">${esc(fv.data)}</div>`;
    viewer=`<div class="fviewer"><div class="fvh"><button class="fvb" onclick="closeFile()">✕</button><span style="font-weight:600">${esc(fv.path)}</span><span style="color:var(--t3);font-size:8px">${fmtSize(fv.data&&fv.data.length?fv.data.length:0)}</span></div>${content}</div>`;
  }
  return`<div class="atree">${rt(tree,0)}</div>${viewer}`;
}
function openFile(id,name){
  if(!state.fileView)state.fileView={};state.fileView[id]={path:name,data:undefined};
  const p=getPkt(id);if(p)updateCont(id);const suffix=getLastRunSuffix(p);if(!suffix)return;
  fetch(apiUrl(`/api/admin/packet/${id}/runs/${suffix}/artifacts/file?path=${encodeURIComponent(name)}`)).then(r=>r.text()).then(t=>{let data;try{data=JSON.parse(t);}catch{data=t;}state.fileView[id]={path:name,data};if(p)updateCont(id);}).catch(()=>{state.fileView[id]={path:name,data:'Error loading file'};if(p)updateCont(id);});
}
function closeFile(){delete state.fileView[state.sel];const p=getPkt(state.sel);if(p)updateCont(state.sel);}
function renderJsonTree(data,depth){
  if(depth===undefined)depth=0;
  if(data===null)return'<span class="jt-n">null</span>';if(typeof data==='boolean')return`<span class="jt-b">${data}</span>`;
  if(typeof data==='number')return`<span class="jt-n">${data}</span>`;if(typeof data==='string')return`<span class="jt-s">"${esc(data)}"</span>`;
  if(Array.isArray(data)){if(!data.length)return'<span class="jt-b">[]</span>';let h=`<span class="jt-toggle" onclick="this.parentElement.classList.toggle('jt-collapsed')">▼</span>[<span class="jt-children"><br>`;data.forEach((v,i)=>{h+='  '.repeat(depth+1)+renderJsonTree(v,depth+1)+(i<data.length-1?',':'')+'<br>';});h+='  '.repeat(depth)+']</span>';return`<span style="cursor:default">${h}</span>`;}
  if(typeof data==='object'){const keys=Object.keys(data);if(!keys.length)return'<span class="jt-b">{}</span>';let h=`<span class="jt-toggle" onclick="this.parentElement.classList.toggle('jt-collapsed')">▼</span>{<span class="jt-children"><br>`;keys.forEach((k,i)=>{h+='  '.repeat(depth+1)+`<span class="jt-k">"${esc(k)}"</span>: ${renderJsonTree(data[k],depth+1)}`+(i<keys.length-1?',':'')+'<br>';});h+='  '.repeat(depth)+'}</span>';return`<span style="cursor:default">${h}</span>`;}
  return esc(String(data));
}
function renderEvidenceTab(p){
  const ed=state.tabData[p.id]?.evidence;if(ed===null)return'<div class="empty">No evidence</div>';
  if(ed===undefined){loadTabData(p.id,'evidence');return'<div class="loading">Loading evidence</div>';}
  const stages=ed.stages||[];let html='';
  if(ed.verdict)html+=`<div style="font-size:11px;margin-bottom:6px"><span style="color:var(--t3);font-weight:600">Verdict:</span> <span style="color:${['pass','passed','accepted','accept','done','ok'].includes((ed.verdict||'').toLowerCase())?'var(--green)':'var(--red)'}">${esc(ed.verdict)}</span></div>`;
  if(ed.summary)html+=`<div style="font-size:10px;color:var(--t2);margin-bottom:6px">${esc(ed.summary)}</div>`;
  if(stages.length)html+='<div class="scards">'+stages.map(s=>{const cls=s.status==='passed'?'done':s.status==='failed'?'failed':'pending',icon=s.status==='passed'?'✓':s.status==='failed'?'✗':'—';let r='';if(s.summary)r+=`<div class="sc-r"><span class="sc-rk">Summary</span><span class="sc-rv">${esc(s.summary).slice(0,60)}</span></div>`;if(s.blocking_issues?.length)r+=`<div class="sc-r"><span class="sc-rk">Blocking</span><span class="sc-rv err">${s.blocking_issues.length}</span></div>`;return`<div class="sc ${cls}"><div class="sc-h"><span class="sc-n ${cls}">${esc(s.name||'?')}</span><span class="sc-si">${icon}</span></div><div class="sc-rs">${r}</div></div>`;}).join('')+'</div>';
  if(!html)html='<div class="empty">No evidence data</div>';return html;
}
function fmtSize(b){if(!b)return'';if(b<1024)return b+'B';if(b<1048576)return(b/1024).toFixed(0)+'KB';return(b/1048576).toFixed(1)+'MB';}

function getLastRunSuffix(p){const rs=p.runs_summary||[];if(!rs.length)return null;return rs[rs.length-1].run_id.replace(p.id+'-','');}
function getPkt(id){if(!state.data)return null;for(const f of state.data.features||[]){for(const w of f.waves||[]){for(const p of w.packets||[]){if(p.id===id)return p;}}}return null;}
async function loadTabData(id,tab){
  if(!state.tabData[id])state.tabData[id]={};state.tabData[id][tab]=undefined;
  try{const p=getPkt(id);let data=null;
    if(tab==='events'){const r=await fetch(apiUrl(`/api/admin/packet/${id}/timeline?limit=200`));data=await r.json();}
    else if(tab==='sessions'){const r=await fetch(apiUrl(`/api/admin/packet/${id}/sessions`));data=await r.json();}
    else if(tab==='logs'){const s=getLastRunSuffix(p);if(!s||!p){state.tabData[id][tab]=null;updateCont(id);return;}const r=await fetch(apiUrl(`/api/admin/packet/${id}/runs/${s}/logs?tail=200`));data=await r.json();}
    else if(tab==='evidence'){const s=getLastRunSuffix(p);if(!s||!p){state.tabData[id][tab]=null;updateCont(id);return;}const r=await fetch(apiUrl(`/api/admin/packet/${id}/runs/${s}/evidence`));data=await r.json();}
    else if(tab==='artifacts'){const s=getLastRunSuffix(p);if(!s||!p){state.tabData[id][tab]=null;updateCont(id);return;}const r=await fetch(apiUrl(`/api/admin/packet/${id}/runs/${s}/artifacts`));data=await r.json();}
    state.tabData[id][tab]=data;
  }catch(e){state.tabData[id][tab]=null;}updateCont(id);
}
function updateCont(id){
  const dcont=document.getElementById('dcont-'+id);if(!dcont)return;
  const p=getPkt(id);if(!p)return;
  const t=state.tab[p.id]||'spec';dcont.innerHTML=renderTabContent(p,t);
  const dt=dcont.parentElement?.querySelector('.dtabs');if(dt)dt.querySelectorAll('.dtab').forEach(el=>el.classList.toggle('on',el.textContent.trim()===TLAB[t]));
}
function mergeDetail(id,detail){
  const p=getPkt(id);if(!p)return;
  if(detail.pipeline)p.pipeline=detail.pipeline;if(detail.state_machine)p.state_machine=detail.state_machine;
  if(detail.runs_summary)p.runs_summary=detail.runs_summary;if(detail.sessions_summary)p.sessions=detail.sessions_summary.sessions||[];
  if(detail.packet)Object.assign(p,detail.packet);
  const dcont=document.getElementById('dcont-'+id);if(dcont){const t=state.tab[id]||'spec';dcont.innerHTML=renderTabContent(p,t);}
}
function stab(id,t){state.tab[id]=t;updateCont(id);}

async function archiveFeat(id){
  if(state.view==='archive'){try{await fetch(apiUrl(`/api/admin/feature/${id}/unarchive`),{method:'POST'});toast('Feature restored','ok');loadArchived();}catch(e){toast('Restore failed','err');}return;}
  try{await fetch(apiUrl(`/api/admin/feature/${id}/archive`),{method:'POST'});toast('Feature archived','ok');if(state.view==='dashboard')loadData();}catch(e){toast('Archive failed','err');}
}
function loadArchived(){
  fetch(apiUrl('/api/admin/features?include_archived=true')).then(r=>r.json()).then(d=>{
    const fs=(d.features||[]).filter(f=>f.is_archived);if(!fs.length){$('#board').innerHTML='<div class="empty">No archived features</div>';return;}
    $('#board').innerHTML=fs.map(f=>`<div class="feat-card"><div class="feat-h"><div class="feat-info"><div class="feat-title" style="opacity:.6">${esc(f.title||f.id)}</div><div class="feat-sub">${esc(f.id)} · ${f.total_packets||0} packets</div></div><div class="feat-actions"><button class="feat-act" onclick="event.stopPropagation();archiveFeat('${f.id}')" title="Restore">↩</button></div></div></div>`).join('');
  }).catch(()=>{$('#board').innerHTML='<div class="empty">Failed to load archive</div>';});
}

async function submitBiz(){
  const ta=$('#biz-input'),btn=$('#biz-btn'),status=$('#biz-status'),text=ta?.value?.trim();
  if(!text||text.length<10){if(status)status.textContent='Please write at least 10 characters';return;}
  btn.disabled=true;btn.textContent='Submitting...';if(status)status.textContent='Sending to architect (may take 30-60s)...';
  let dots=0;const dotInt=setInterval(()=>{dots=(dots+1)%4;if(status&&!status.textContent.includes('submitted')&&!status.textContent.includes('Error'))status.textContent='Architect is thinking'+'.'.repeat(dots)+' '.repeat(3-dots);},2000);
  try{
    const r=await fetch(apiUrl('/api/architect/plan'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({feature_spec:{title:text.slice(0,80),description:text,origin:'business',background:true}})});
    clearInterval(dotInt);
    if(!r.ok){const e=await r.json();if(status)status.textContent='Error: '+(e.detail||e.message||r.status);btn.disabled=false;btn.textContent='Submit Feature';toast('Architect error','err');return;}
    const result=await r.json();
    ta.value='';btn.disabled=false;btn.textContent='Submit Feature';
    const isPlanning=result.status==='planning'||result.immediate;
    if(status)status.textContent=isPlanning?'Feature created! Architect planning in background.':'Feature submitted!';
    toast(isPlanning?'Feature created! Architect is planning waves/packets.':'Feature submitted!','ok');
    setTimeout(()=>switchView('dashboard'),1000);
  }catch(e){
    clearInterval(dotInt);
    if(status)status.textContent='Request failed: '+e.message;toast('Request failed','err');
    btn.disabled=false;btn.textContent='Submit Feature';
  }
}

const _qp=new URLSearchParams(location.search),_xtp=_qp.get('XTransformPort');
function apiUrl(p){if(_xtp){const s=p.includes('?')?'&':'?';return p+s+'XTransformPort='+_xtp;}return p;}
const detailCache={};
async function loadDetail(id){try{const r=await fetch(apiUrl(`/api/admin/packet/${id}/detail`));const d=await r.json();d._ts=Date.now();detailCache[id]=d;return d;}catch{return null;}}
function loadDetailCached(id){const d=detailCache[id];if(d&&Date.now()-d._ts<15000)return d;return null;}

let refTimer=null;
function startRefTimer(){
  if(refTimer)clearInterval(refTimer);
  state.refCount=5;updateRefIndicator();
  refTimer=setInterval(()=>{if(state.paused)return;state.refCount--;updateRefIndicator();if(state.refCount<=0){state.refCount=5;if(state.view==='dashboard')loadData();}},1000);
}
function togglePause(){state.paused=!state.paused;updateRefIndicator();}
function updateRefIndicator(){
  const el=$('#ref-ind');
  if(el){el.textContent=state.paused?'⏸ paused':'↻ '+state.refCount+'s';el.className='ref-indicator'+(state.paused?' paused':'');}
}
document.addEventListener('DOMContentLoaded',()=>{
  const be=$('.bar-end');if(be){const d=document.createElement('span');d.id='ref-ind';d.className='ref-indicator';d.onclick=togglePause;be.prepend(d);}
  const nav=$('#topnav');if(nav){const t=document.createElement('button');t.className='toggle-btn';t.textContent='Detail';t.onclick=toggleDetail;t.title='Toggle detailed packet info';nav.after(t);}
  startRefTimer();
});

async function loadData(){
  try{
    // Preserve ALL state for selected packet across refresh
    const savedSel=state.sel;
    const savedTabData=state.tabData;
    const savedTab=state.tab;
    const savedFileView=state.fileView;
    const saved={};
    if(savedSel&&state.data){for(const f of state.data.features||[]){for(const w of f.waves||[]){for(const p of w.packets||[]){if(p.id===savedSel){saved.state_machine=p.state_machine;saved.runs_summary=p.runs_summary;saved.packet=p.packet;}}}}}
    const r=await fetch(apiUrl('/api/admin/features'));state.data=await r.json();
    state.sel=savedSel;
    state.tabData=savedTabData;
    state.tab=savedTab;
    state.fileView=savedFileView;
    for(const f of state.data.features||[]){state.expFeat[f.id]=true;for(const w of f.waves||[]){state.expWave[w.id]=true;}}
    if(saved.state_machine&&state.sel){for(const f of state.data.features||[]){for(const w of f.waves||[]){for(const p of w.packets||[]){if(p.id===state.sel){p.state_machine=saved.state_machine;p.runs_summary=saved.runs_summary;if(saved.packet)Object.assign(p,saved.packet);}}}}}
    renderDashboard();
  }catch(e){$('#board').innerHTML='<div class="empty">Failed to load. Retrying...</div>';setTimeout(loadData,5000);}
}

// ── Log viewer ──
let logState={lines:[],source:'',paused:false};
function initLogViewer(){
  logState={lines:[],source:'',paused:false};
  $('#board').innerHTML='<div class="loading">Loading server logs...</div>';
  fetchLogs();
  if(window.logInt)clearInterval(window.logInt);
  window.logInt=setInterval(fetchLogs,2000);
}
function toggleLogPause(){logState.paused=!logState.paused;if(!logState.paused)fetchLogs();}
async function fetchLogs(){
  if(logState.paused||state.view!=='logs')return;
  try{
    const r=await fetch(apiUrl('/api/admin/system/logs?tail=200'));
    const d=await r.json();
    logState.lines=d.lines||[];
    logState.source=d.source||'';
    renderLogs();
  }catch(e){/* ignore */}
}
function renderLogs(){
  const lines=logState.lines;
  let html=`<div style="display:flex;gap:6px;align-items:center;padding:6px 10px;flex-shrink:0;border-bottom:1px solid var(--bd);background:var(--bg1)">
    <span style="font-size:10px;font-weight:600;color:var(--t2)">Server Logs</span>
    <span style="font-size:8px;color:var(--t3);font-family:var(--mono)">${logState.source}</span>
    <span style="font-size:8px;color:var(--t3)">${lines.length} lines</span>
    <span style="flex:1"></span>
    <button class="chip ${logState.paused?'on':''}" onclick="toggleLogPause()" style="font-size:9px;padding:2px 8px">${logState.paused?'⏵ Resume':'⏸ Pause'}</button>
    <button class="chip" onclick="fetchLogs()" style="font-size:9px;padding:2px 8px">↻</button>
  </div>`;
  html+=`<div style="flex:1;overflow-y:auto;padding:4px 8px;font-family:var(--mono);font-size:9px;line-height:1.6;background:var(--bg0)">`;
  lines.forEach(l=>{
    // Skip self-polling noise
    if(l.includes('GET /api/admin/system/logs')||l.includes('GET /api/admin/features')||l.includes('favicon.ico')||l.includes('GET /static/'))return;
    let cls='';
    if(l.startsWith('{')){try{const j=JSON.parse(l);cls=j.level==='ERROR'?'color:var(--red)':j.level==='WARN'?'color:var(--yellow)':'color:var(--t2)';l=j.msg||l;}catch{}}
    else if(l.includes('ERROR')||l.includes('error'))cls='color:var(--red)';
    else if(l.includes('WARNING')||l.includes('warn'))cls='color:var(--yellow)';
    html+=`<div style="${cls};white-space:pre-wrap;word-break:break-all">${esc(l.slice(0,2000))}</div>`;
  });
  html+='</div>';
  $('#board').innerHTML=html;
}

loadData();

// Live timer for running pipeline stages — ticks every second
setInterval(()=>{
  document.querySelectorAll('.pblock.running').forEach(el=>{
    const stEl=el.querySelector('.pbl-st');
    const durEl=el.querySelector('.pbl-t');
    if(stEl&&durEl&&stEl.textContent){
      const d=new Date(stEl.textContent);
      if(!isNaN(d.getTime()))durEl.textContent=fmtDur(Math.max(Date.now()-d.getTime(),0));
    }
  });
},1000);
