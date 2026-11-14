/* Syllabus Auditor SPA: dependency-free, same-origin and CSP-friendly. */
'use strict';
const S={user:null,route:'dashboard',inst:0,detail:null,selectedFinding:null,files:[],poll:null,activeJob:null,dataset:[],q:'',catalogSubject:'',catalogSearch:''};
const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const attr=v=>esc(v);
const I={dashboard:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',scan:'<path d="M8 3H5a2 2 0 0 0-2 2v3M16 3h3a2 2 0 0 1 2 2v3M21 16v3a2 2 0 0 1-2 2h-3M3 16v3a2 2 0 0 0 2 2h3"/><path d="m9 12 2 2 4-4"/>',files:'<path d="M14 2H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h6"/>',book:'<path d="M3 19.5V4a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v15.5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2A2 2 0 0 0 5 22h14"/>',shield:'<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/>',history:'<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l4 2"/>',settings:'<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.07-2 2-.07-.06a1.7 1.7 0 0 0-1.9-.33l-.1.04V21h-4v-2.4a1.7 1.7 0 0 0-1.9-.04l-.1.04-1.7 1.7-2.8-2.8 1.7-1.7A1.7 1.7 0 0 0 6.5 14H4v-4h2.4A1.7 1.7 0 0 0 6 8.1L4.3 6.4 7.1 3.6l1.7 1.7A1.7 1.7 0 0 0 10.5 5V2.7h4V5A1.7 1.7 0 0 0 16.4 5l1.7-1.7 2.8 2.8-1.7 1.7a1.7 1.7 0 0 0-.4 2.2H21v4h-1.6Z"/>',upload:'<path d="M12 16V3m-5 5 5-5 5 5"/><path d="M4 17v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',chart:'<path d="M3 3v18h18M7 17v-4M12 17V7M17 17v-8"/>',globe:'<circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a17 17 0 0 1 0 20M12 2a17 17 0 0 0 0 20"/>',plus:'<path d="M12 5v14M5 12h14"/>',search:'<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',check:'<path d="m5 12 4 4L19 6"/>',close:'<path d="M18 6 6 18M6 6l12 12"/>',download:'<path d="M12 3v12m-5-5 5 5 5-5M4 17v4h16v-4"/>',refresh:'<path d="M3 12a9 9 0 0 1 15-6.7L21 8M21 3v5h-5M21 12a9 9 0 0 1-15 6.7L3 16M3 21v-5h5"/>',right:'<path d="m9 18 6-6-6-6"/>',brain:'<path d="M12 18V5a3 3 0 0 0-6 0 4 4 0 0 0-2 7 4 4 0 0 0 2 7 3 3 0 0 0 6-1ZM12 18V5a3 3 0 0 1 6 0 4 4 0 0 1 2 7 4 4 0 0 1-2 7 3 3 0 0 1-6-1Z"/>',lock:'<rect x="4" y="11" width="16" height="11" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',user:'<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',alert:'<path d="m12 2 10 18H2L12 2Z"/><path d="M12 9v4m0 4h.01"/>',eye:'<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>'};
const icon=(name,cls='')=>`<svg class="icon ${cls}" viewBox="0 0 24 24" aria-hidden="true">${I[name]||I.files}</svg>`;
const pill=st=>`<span class="pill ${esc(st)}">${esc(String(st||'unknown').replaceAll('_',' '))}</span>`;
const compliance=a=>a.status!=='complete'?a.status:a.failed?'failed':a.review?'review':a.warnings?'warning':'passed';
const aButton=(label,act,extra='',cls='small')=>`<button class="btn ${cls}" data-act="${act}" ${extra}>${label}</button>`;
const prettyDate=s=>s?new Date(s).toLocaleString():'-';
const isAdmin=()=>S.user?.role==='admin';
async function api(url,opt={}){
 const method=opt.method||'GET', headers={...(opt.headers||{})};
 if(S.user && !['GET','HEAD'].includes(method))headers['X-CSRF-Token']=S.user.csrf;
 if(opt.body && !(opt.body instanceof FormData) && typeof opt.body==='object'){headers['Content-Type']='application/json';opt.body=JSON.stringify(opt.body)}
 const resp=await fetch(url,{credentials:'same-origin',...opt,method,headers});
 if(!resp.ok){let msg='Request failed';try{const j=await resp.json();msg=typeof j.detail==='string'?j.detail:JSON.stringify(j.detail)}catch{}
  if(resp.status===401 && S.user){S.user=null;loginUI()}
  throw Error(msg)}
 if(resp.status===204)return null;
 return resp.headers.get('content-type')?.includes('application/json')?resp.json():resp.blob();
}
function notify(message,type=''){const elt=document.createElement('div');elt.className='toast '+type;elt.textContent=message;$('toast').appendChild(elt);setTimeout(()=>elt.remove(),4500)}
function modal(html){$('modalContent').innerHTML=html;$('modal').showModal()}
function closeModal(){$('modal').close()}
function modalHead(title){return `<div class="modal-title"><h2 id="modalTitle">${esc(title)}</h2>${aButton(icon('close'),'modal-close','','ghost small')}</div>`}
function input(name,label,value='',type='text',hint='',required=false){return `<div class="field"><label for="f-${esc(name)}">${esc(label)}</label><input id="f-${esc(name)}" name="${esc(name)}" type="${type}" value="${attr(value)}" ${required?'required':''}/>${hint?`<span class="hint">${esc(hint)}</span>`:''}</div>`}
function textarea(name,label,value='',hint='',required=false){return `<div class="field"><label for="f-${esc(name)}">${esc(label)}</label><textarea id="f-${esc(name)}" name="${esc(name)}" ${required?'required':''}>${esc(value)}</textarea>${hint?`<span class="hint">${esc(hint)}</span>`:''}</div>`}
function selectField(name,label,options,value=''){return `<div class="field"><label for="f-${esc(name)}">${esc(label)}</label><select id="f-${esc(name)}" name="${esc(name)}">${options.map(o=>`<option value="${attr(o[0])}" ${String(o[0])===String(value)?'selected':''}>${esc(o[1])}</option>`).join('')}</select></div>`}
function checkField(name,label,value=false){return `<label class="checkbox-row"><input type="checkbox" name="${esc(name)}" ${value?'checked':''}><div><strong>${esc(label)}</strong></div></label>`}
function formDataObj(form){const data=Object.fromEntries(new FormData(form));for(const c of form.querySelectorAll('input[type=checkbox]'))data[c.name]=c.checked;return data}
function formFooter(label='Save changes'){return `<div class="form-footer">${aButton('Cancel','modal-close','','small')}<button class="btn primary" type="submit">${esc(label)}</button></div>`}
function sectionIntro(title,desc,buttons=''){return `<div class="page-intro"><div><h1>${esc(title)}</h1><p>${esc(desc)}</p></div><div class="actions">${buttons}</div></div>`}
const empty=(message,button='')=>`<div class="empty">${icon('files')}<strong>${esc(message)}</strong>${button}</div>`;
const table=(headers,rows)=>`<div class="table-scroll"><table><thead><tr>${headers.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.join('')||`<tr><td colspan="${headers.length}"><span class="muted">No records yet</span></td></tr>`}</tbody></table></div>`;
const stat=(label,number,ic,note)=>`<div class="panel stat"><div class="stat-label">${esc(label)}</div><div class="stat-number">${number}</div><div class="stat-icon">${icon(ic)}</div><div class="stat-note">${esc(note)}</div></div>`;
function loginUI(setup=false){
 $('app').innerHTML=`<main class="auth-screen"><div class="auth-card"><div class="auth-icon">${icon('shield')}</div><h1>${setup?'Set up Syllabus Auditor':'Welcome back'}</h1><p>${setup?'Create the first administrator account. Your one-time setup token appears in the server startup logs and data/bootstrap-token.txt.':'Sign in to securely review and verify course syllabi.'}</p><form id="${setup?'setup-form':'login-form'}" class="stack">${setup?input('token','First-run setup token','','password','From the server console or Docker logs',true):''}${input('username','Username','','text','',true)}${input('password',setup?'Administrator password':'Password','','password',setup?'12 characters minimum':'',true)}<button class="btn primary" type="submit">${setup?'Create administrator':'Sign in'}</button></form><div class="auth-caption">Private document validation · Self-hosted AI · No external AI APIs</div></div></main>`;
}
const navItems=[['dashboard','Overview','dashboard'],['check','Check Syllabi','scan'],['audits','Audit Results','files'],['templates','Templates','book'],['policies','Required Policies','shield'],['catalog','Course Catalog','book'],['sources','Source Monitor','globe'],['history','History & Reports','history'],['settings','Settings','settings']];
function shell(){
 const path=S.route.split('/')[0]; const instOptions=`<option value="0">All institutions</option>`+(S.institutions||[]).map(i=>`<option value="${i.id}" ${Number(S.inst)===i.id?'selected':''}>${esc(i.name)}</option>`).join('');
 $('app').innerHTML=`<div class="shell"><aside class="sidebar"><div class="brand"><span class="brand-mark">${icon('shield')}</span><div><div class="brand-name">Syllabus Auditor</div><div class="brand-sub">COMPLIANCE WORKSPACE</div></div></div><div class="side-section">Workspace</div>${navItems.slice(0,3).map(([r,label,ic])=>`<button class="nav-item ${path===r?'active':''}" data-route="${r}">${icon(ic)}<span class="nav-text">${label}</span></button>`).join('')}<div class="side-section">Manage</div>${navItems.slice(3,7).map(([r,label,ic])=>`<button class="nav-item ${path===r?'active':''}" data-route="${r}">${icon(ic)}<span class="nav-text">${label}</span></button>`).join('')}<div class="side-section">System</div>${navItems.slice(7).map(([r,label,ic])=>`<button class="nav-item ${path===r?'active':''}" data-route="${r}">${icon(ic)}<span class="nav-text">${label}</span></button>`).join('')}<div class="side-footer"><div>Signed in as <strong>${esc(S.user.username)}</strong><div>${esc(S.user.role)}</div></div><button data-act="logout">Sign out</button></div></aside><div class="workspace"><div class="topbar"><div class="breadcrumbs">WORKSPACE / ${esc(navItems.find(x=>x[0]===path)?.[1]||'Audit detail')}</div><div class="topbar-right"><select id="institution-switch" class="select-inst" aria-label="Choose institution">${instOptions}</select><div class="avatar" title="${esc(S.user.username)}">${esc(S.user.username[0].toUpperCase())}</div></div></div><main id="content" class="content"><div class="loading-screen" style="height:260px"><div class="spinner"></div>Loading...</div></main></div></div>`;
}
function needInstitution(){return S.inst || S.institutions?.[0]?.id || 0}
function noInst(){return sectionIntro('Institution required','Create an institution to configure templates, catalog records and policies.')+empty('No institution configured',isAdmin()?aButton('Add institution','inst-add','','primary'):'Ask your administrator to add one')}
function aiBanner(ai){return ai?.available?'':`<div class="status-banner warn">${icon('alert')}<div><strong>Embedded AI unavailable:</strong> ${esc(ai?.description||'Runtime not detected')}. Rule-based checks still run. The offline GGUF model and embedded runtime are required for AI-assisted navigation.</div></div>`}
async function renderDashboard(){let d=await api('/api/overview');
 let rows=d.recent.map(a=>`<tr><td><a href="#audit/${a.id}" class="filename">${esc(a.filename)}</a><br/><small>${esc(a.course_code||'Course not detected')}</small></td><td>${pill(compliance(a))}</td><td>${a.passed}</td><td>${a.failed}</td><td><button class="btn small" data-route="audit/${a.id}">Open ${icon('right')}</button></td></tr>`);
 $('content').innerHTML=sectionIntro('Dashboard','A clear view of your institutional syllabus compliance.',aButton(icon('plus')+' New audit','go-check','','primary')+(isAdmin()?aButton('Add institution','inst-add') : ''))+
 `<div class="grid metrics">${stat('Total syllabi',d.audits,'files','Documents submitted')}${stat('Successful checks',d.counts.passed,'check','Passed requirements')}${stat('Items to review',d.counts.warning+d.counts.review,'alert','Warnings and uncertain matches')}${stat('Confirmed failures',d.counts.failed,'shield','Requirements requiring action')}</div>`+
 `<div class="section-bar"><h2>Operational status</h2>${aButton('View sources','go-sources')}</div><div class="grid two"><div class="panel panel-pad stack"><div class="flex justify-between"><strong>Institutional configuration</strong>${pill(d.institutions?'ready':'needs_review')}</div><p class="muted">${d.institutions} institution(s), ${d.templates} template(s) available.</p><p class="tiny muted">${d.source_alerts} source changes awaiting approval.</p></div><div class="panel panel-pad stack"><div class="flex justify-between"><strong>Local AI inference</strong>${pill(d.ai.available?'ready':'review')}</div><p class="muted">${esc(d.ai.description)}</p><p class="tiny muted">No remote model services or AI API credentials.</p></div></div>`+
 `<div class="section-bar"><h2>Recent audits</h2>${aButton('View all','go-audits')}</div><div class="panel">${table(['Document','Status','Passed','Failed',''],rows)}</div>`;
}
function bindDropzone(){const zone=$('dropzone'),choose=$('file-choose'),fileInput=$('file-upload');if(!zone)return;
 choose.addEventListener('click',e=>{e.stopPropagation();fileInput.click()});zone.addEventListener('click',()=>fileInput.click());
 zone.addEventListener('dragover',e=>{e.preventDefault();zone.classList.add('hover')});
 zone.addEventListener('dragleave',()=>zone.classList.remove('hover'));
 zone.addEventListener('drop',e=>{e.preventDefault();zone.classList.remove('hover');S.files=Array.from(e.dataTransfer.files);filesDisplay()});
 fileInput.addEventListener('change',()=>{S.files=Array.from(fileInput.files);filesDisplay()});
}
function filesDisplay(){const el=$('chosen-files');if(!el)return;
 el.innerHTML=S.files.length?`<strong>${S.files.length} selected file(s)</strong><div class="file-list">${S.files.map(f=>`<span class="file-pill">${icon('files')} ${esc(f.name)} · ${(f.size/1024).toFixed(0)} KB</span>`).join('')}</div>`:'No files selected';}
async function renderCheck(){
 const institutions=S.institutions||[],inst=needInstitution();if(!inst){$('content').innerHTML=noInst();return}
 const ts=await api('/api/templates?institution_id='+inst); const jobs=await api('/api/jobs');
 $('content').innerHTML=sectionIntro('Check Syllabi','Upload one syllabus or an entire folder and inspect compliance findings.')+aiBanner(S.user.ai)+
 `<div class="panel panel-pad"><form id="upload-form" class="stack"><div class="form-row">${selectField('institution_id','Institution',institutions.map(i=>[i.id,i.name]),inst)}${selectField('template_id','Master template',[['0','Institution rules only'],...ts.filter(x=>x.active).map(t=>[t.id,`${t.name} (v${t.version})`])])}</div>${input('academic_year','Academic year',institutions.find(i=>i.id===inst)?.academic_year||'','text','e.g. 2026-2027; this selects the appropriate catalog reference')}
 <div class="dropzone" id="dropzone" tabindex="0" role="button" aria-label="Select document files"><span class="big-icon">${icon('upload')}</span><h3>Drop your course syllabi here</h3><p>DOCX, PDF, and UTF-8 TXT · Up to 25 MB per file · 100 documents per batch</p><button type="button" id="file-choose" class="btn primary">Browse files</button><input type="file" id="file-upload" multiple accept=".pdf,.docx,.txt" hidden></div><div class="flex justify-between" style="align-items:flex-start"><div id="chosen-files" class="muted tiny">No files selected</div><button class="btn primary" type="submit">${icon('scan')} Run syllabus checks</button></div></form></div>`+
 `<div class="section-bar"><h2>Recent batches</h2></div><div class="panel">${table(['Batch','Institution','Progress','Status',''],jobs.slice(0,25).map(j=>`<tr><td>#${j.id}<br/><small>${prettyDate(j.created_at)}</small></td><td>${esc(j.institution_name)}</td><td>${j.finished} / ${j.total}<div class="progress" style="margin-top:6px"><span style="width:${j.total?j.finished/j.total*100:0}%"></span></div></td><td>${pill(j.status)}</td><td>${aButton('Details','job-view',`data-id="${j.id}"`)}</td></tr>`))}</div>`;
 bindDropzone();
}
function canManageAudit(a){return Boolean(a&&S.user&&(S.user.role==='admin'||S.user.id===a.created_by))}
function reportActions(a){return (a.status==='complete'?aButton('Inspect','open-audit',`data-id="${a.id}"`):'')+
 (canManageAudit(a)&&['complete','error','interrupted'].includes(a.status)?aButton('Rerun checks','rerun-audit',`data-id="${a.id}"`):'')+
 (canManageAudit(a)&&!['queued','running'].includes(a.status)?aButton('Delete','delete-audit',`data-id="${a.id}"`):'')}
async function renderAudits(){let d=await api('/api/audits'+(S.inst?'?institution_id='+S.inst:''));S.dataset=d;
 const rows=d.map(a=>`<tr><td><a href="#audit/${a.id}" class="filename">${esc(a.filename)}</a><br/><small>${esc(a.course_code||'Unidentified')}${a.rerun_of_id?' · Rerun of #'+a.rerun_of_id:''}</small></td><td>${esc(a.academic_year||'-')}</td><td>${pill(compliance(a))}</td><td><span class="pill passed">${a.passed} passed</span> <span class="pill failed">${a.failed} failed</span> <span class="pill review">${a.review} review</span></td><td>${prettyDate(a.created_at)}</td><td><div class="actions">${reportActions(a)}</div></td></tr>`);
 $('content').innerHTML=sectionIntro('Audit Results','Browse completed and in-progress syllabus checks.',aButton(icon('download')+' Export CSV','download-csv')+aButton(icon('plus')+' New audit','go-check','','primary'))+`<div class="panel">${table(['Document','Academic year','Status','Findings','Submitted',''],rows)}</div>`;
}
async function renderAuditDetail(id){let data=await api('/api/audits/'+id);S.detail=data;
 const a=data.audit,findings=data.findings;if(!S.selectedFinding || !findings.some(f=>f.id===S.selectedFinding))S.selectedFinding=findings[0]?.id||null;
 const chosen=findings.find(f=>f.id===S.selectedFinding);
 const issueButtons=findings.map(f=>`<button class="issue-button ${f.id===S.selectedFinding?'selected':''}" data-act="show-finding" data-id="${f.id}"><span class="flex justify-between"><strong>${esc(f.title)}</strong>${pill(f.status)}</span><span class="meta">${esc(f.category)} · ${esc(f.location||'Not located')}</span></button>`).join('');
 let blocks=[];try{blocks=JSON.parse(a.extraction_json||'[]')}catch{}
 const docHTML=blocks.length?blocks.slice(0,2500).map((b,i)=>`<div class="docblock" id="doc-${i}" data-location="${attr(b.location)}"><small>${esc(b.location)}</small>${esc(b.text)}</div>`).join(''):empty('Text preview is not available');
 const focus=chosen?.location||'';
 $('content').innerHTML=sectionIntro('Review Syllabus',`${a.filename} · ${a.course_code||'Unknown course'} · ${a.academic_year||'Unspecified academic year'}${a.rerun_of_id?' · Rerun of audit #'+a.rerun_of_id:''}`,aButton('Back to results','go-audits')+aButton(icon('download')+' PDF report','report-pdf',`data-id="${a.id}"`)+aButton('DOCX report','report-docx',`data-id="${a.id}"`)+(canManageAudit(a)&&['complete','error','interrupted'].includes(a.status)?aButton('Rerun checks','rerun-audit',`data-id="${a.id}"`):'')+(canManageAudit(a)&&!['queued','running'].includes(a.status)?aButton('Delete report','delete-audit',`data-id="${a.id}"`,'danger'): ''))+
 `<div class="grid metrics" style="margin-bottom:18px">${stat('Passed',a.passed,'check','Verified requirements')}${stat('Warnings',a.warnings,'alert','Potential discrepancies')}${stat('Failures',a.failed,'shield','Confirmed differences')}${stat('Needs review',a.review,'eye','Uncertain or unverified')}</div>`+
 `<div class="actions" style="margin-bottom:17px">${a.filetype==='.pdf'?aButton('Open original PDF','open-original',`data-id="${a.id}"`):aButton('Download original','open-original',`data-id="${a.id}"`)} ${a.filetype==='.docx'?aButton('Download approved corrections','corrected',`data-id="${a.id}"`):''} ${a.job_id?aButton('Batch ZIP','batch-zip',`data-id="${a.job_id}"`):''} ${a.course_code?aButton('Compare previous audit','compare-audit',`data-id="${a.id}"`):''}</div>`+
 `<div class="audit-detail"><div class="panel audit-issues"><div class="panel-head"><h2>Validation findings</h2><span class="pill">${findings.length}</span></div><div class="issue-nav">${issueButtons||empty('No findings')}</div></div><div class="panel"><div class="panel-head"><h2>Document extraction</h2><span class="tag">Original locations preserved</span></div><div class="docviewer" id="docviewer">${docHTML}</div></div><div class="panel inspection" id="inspector">${inspector(chosen)}</div></div>`;
 if(focus)focusLocation(focus);
}
function inspector(f){if(!f)return empty('Select a finding to inspect');
 return `<div class="flex justify-between" style="align-items:flex-start"><h3>${esc(f.title)}</h3>${pill(f.status)}</div><p class="muted tiny" style="margin:8px 0 17px">${esc(f.category)} · ${esc(f.severity)} · ${esc(f.location||'No location')}</p><div class="callout">${esc(f.explanation||'No explanation')}</div><div class="line"></div><div class="quote-label">Expected / approved wording</div><div class="quote">${esc(f.expected||'(No reference text configured)')}</div><div class="line"></div><div class="quote-label">Text found in syllabus</div><div class="quote">${esc(f.observed||'(No matching text found)')}</div>${f.source_url?`<div class="line"></div><div class="tiny wrap"><b>Official source:</b> <a target="_blank" rel="noopener noreferrer" href="${attr(f.source_url)}">${esc(f.source_url)}</a></div>`:''}<div class="line"></div><small>Location confidence: ${(Number(f.confidence)*100).toFixed(0)}%</small><div class="actions" style="margin-top:17px">${f.status==='passed'?'<span class="pill passed">Requirement passed</span>':aButton(f.accepted?'Correction accepted ✓':'Accept correction','accept-finding',`data-id="${f.id}" data-value="${f.accepted?0:1}"`,f.accepted?'small':'primary small')+aButton(f.dismissed?'Reopen finding':'Dismiss finding','dismiss-finding',`data-id="${f.id}" data-value="${f.dismissed?0:1}"`)}</div><p class="tiny muted" style="margin-top:13px">Approval is recorded; it does not rewrite the original document. DOCX corrections are only applied when an unambiguous text replacement is possible.</p>`;
}
function focusLocation(location){if(!location)return;const blocks=[...document.querySelectorAll('.docblock')];for(const b of blocks)b.classList.remove('focus');let node=blocks.find(x=>x.dataset.location===location)||blocks.find(x=>x.dataset.location?.startsWith(location.split(',')[0]));if(node){node.classList.add('focus');node.scrollIntoView({block:'center',behavior:'smooth'})}}
async function renderTemplates(){let inst=needInstitution();if(!inst){$('content').innerHTML=noInst();return}let rows=await api('/api/templates?institution_id='+inst);S.dataset=rows;
 $('content').innerHTML=sectionIntro('Syllabus Templates','Manage institutional master syllabi and required document sections.',isAdmin()?aButton(icon('plus')+' Upload template','template-add','','primary'):'')+
 `<div class="status-banner" style="margin-bottom:18px">${icon('book')} Upload a master template, then mark the extracted headings that every syllabus must contain. Policy wording is managed separately.</div><div class="panel">${table(['Template','Academic year','Version','Headings','Status',''],rows.map(t=>`<tr><td><strong>${esc(t.name)}</strong><br/><small>${esc(t.notes||'No notes')}</small></td><td>${esc(t.academic_year||'Any')}</td><td>v${t.version}</td><td>${JSON.parse(t.sections_json||'[]').length}</td><td>${pill(t.active?'ready':'interrupted')}</td><td>${aButton('Manage','template-edit',`data-id="${t.id}"`)} ${isAdmin()?aButton('Delete','template-delete',`data-id="${t.id}"`,'danger'):''}</td></tr>`))}</div>`;
}
function templateAdd(){modal(modalHead('Upload master syllabus template')+`<form id="template-create" class="stack">${input('name','Template name','','text','',true)}${input('academic_year','Academic year',S.institutions.find(x=>x.id===needInstitution())?.academic_year||'')}${textarea('notes','Notes')}${input('file','DOCX or PDF file','','file','Headings will be extracted; all can be manually marked required',true)}${formFooter('Upload template')}</form>`)}
function templateEdit(id){const t=S.dataset.find(x=>x.id===id);if(!t)return;
 const sections=JSON.parse(t.sections_json||'[]');
 modal(modalHead('Template: '+t.name)+`<form id="template-update" data-id="${t.id}" class="stack">${input('name','Template name',t.name,'text','',true)}${input('academic_year','Academic year',t.academic_year)}${textarea('notes','Notes',t.notes)}<div><strong>Required sections and reference wording</strong><p class="muted tiny" style="margin:5px 0 12px">Disable optional sections. Choose whether the heading alone or its template wording must match.</p><div class="checklist modal-scroll" id="template-section-list">${sections.map((s,i)=>`<div class="checkbox-row"><input type="checkbox" data-index="${i}" ${s.required?'checked':''}><div style="flex:1;min-width:0"><strong>${esc(s.heading)}</strong><span class="tiny muted">${esc((s.sample||'').slice(0,170))}</span><div style="margin-top:8px"><select aria-label="Comparison for ${esc(s.heading)}" data-section-mode="${i}"><option value="heading" ${(s.mode||'heading')==='heading'?'selected':''}>Heading only</option><option value="exact" ${s.mode==='exact'?'selected':''}>Exact reference wording</option><option value="semantic" ${s.mode==='semantic'?'selected':''}>Similar wording</option><option value="present" ${s.mode==='present'?'selected':''}>Content presence</option></select></div></div></div>`).join('')||'<p class="muted">No headings detected; add them manually below.</p>'}</div></div>${input('new_heading','Add a required heading','','text','Optional; type the heading name')}<label class="checkbox-row"><input type="checkbox" name="active" ${t.active?'checked':''}> Template active</label>${formFooter('Save template')}</form>`);
}
const modeOptions=[['exact','Exact approved wording'],['semantic','Semantically equivalent wording'],['present','Section presence'],['heading','Heading recognition']];
const severityOptions=[['critical','Critical'],['warning','Warning'],['info','Informational']];
async function renderPolicies(){let inst=needInstitution();if(!inst){$('content').innerHTML=noInst();return}let req=await api('/api/requirements?institution_id='+inst);S.dataset=req;
 $('content').innerHTML=sectionIntro('Required Policies & Rules','Configure official language, acceptable variants, severity and validation behavior.',isAdmin()?aButton(icon('plus')+' Add requirement','policy-add','','primary'):'')+
 `<div class="panel">${table(['Requirement','Category','Matching rule','Severity','Version',''],req.map(r=>`<tr><td><strong>${esc(r.name)}</strong>${r.source_url?`<br/><small>${esc(r.source_url.slice(0,65))}</small>`:''}</td><td>${esc(r.category)}</td><td>${esc(r.mode)}</td><td>${pill(r.severity==='critical'?'failed':r.severity==='warning'?'warning':'review')}</td><td>v${r.version}</td><td>${aButton('Edit','policy-edit',`data-id="${r.id}"`)} ${isAdmin()?aButton('Delete','policy-delete',`data-id="${r.id}"`,'danger'):''}</td></tr>`))}</div>`;
}
function policyForm(existing){const r=existing||{};
 return modalHead(existing?'Edit requirement':'New requirement')+`<form id="${existing?'policy-update':'policy-create'}" ${existing?`data-id="${r.id}"`:''} class="stack">${input('name','Requirement name',r.name||'','text','e.g. Academic integrity statement',true)}<div class="form-row">${selectField('category','Category',[['policy','School policy'],['syllabus','Syllabus field'],['template','Template section']],r.category||'policy')}${selectField('mode','Matching rule',modeOptions,r.mode||'exact')}</div><div class="form-row">${selectField('severity','Severity',severityOptions,r.severity||'critical')}${input('department','Department limitation (optional)',r.department||'','text','Course prefix, e.g. CSC')}</div>${textarea('expected_text','Required official text',r.expected_text||'','Leave empty for presence-only rules')}${textarea('variants','Other approved versions',(()=>{try{return JSON.parse(r.variants_json||'[]').join('\n')}catch{return ''}})(),'One approved variant per line')}${input('keywords','Matching headings / keywords',r.keywords||'','text','Comma-separated section titles and synonyms')}${input('source_url','Official policy source URL',r.source_url||'','url','Must belong to an institution-approved domain')}
 <div class="form-row">${input('effective_from','Effective from',r.effective_from||'','text','YYYY-MM-DD; optional')}${input('effective_to','Effective until',r.effective_to||'','text','YYYY-MM-DD; optional')}</div>${checkField('active','Requirement active',existing?r.active:true)}${formFooter(existing?'Save requirement':'Create requirement')}</form>`;
}
function acalogSubjectUrl(raw, subject='') {
 const url=new URL(raw); const cat=url.searchParams.get('catoid')||url.searchParams.get('cur_cat_oid');
 const nav=url.searchParams.get('navoid');
 if(url.protocol!=='https:' || !/\/content\.php$/i.test(url.pathname) || !cat || !nav)throw Error('Enter an official Acalog Course Descriptions URL with a catalog ID and navoid.');
 const code=String(subject||'').trim().toUpperCase();
 if(code && !/^[A-Z][A-Z0-9 &/-]{1,11}$/.test(code))throw Error('Enter a valid subject code, such as CIS, CSC, or MATH.');
 if(!code)return url.href;
 const params=new URLSearchParams();
 for(const [k,v] of [['filter[27]',code],['filter[29]',''],['filter[course_type]','-1'],['filter[keyword]',''],['filter[32]','1'],['filter[cpage]','1'],['cur_cat_oid',cat],['expand',''],['navoid',nav],['search_database','Filter'],['filter[exact_match]','1']])params.set(k,v);
 url.search=params.toString();url.hash='acalog_template_course_filter';return url.href;
}
function catalogSubjectUrl(raw, subject='') {
 const url=new URL(raw);
 if(url.protocol==='https:' && /\/Student\/Courses(?:\/Search)?\/?$/i.test(url.pathname)) {
  const code=String(subject||'').trim().toUpperCase();
  if(code && !/^[A-Z]{2,6}$/.test(code))throw Error('Enter a subject code such as CIS or CSC.');
  if(code){url.pathname=url.pathname.replace(/\/Search\/?$/i,'').replace(/\/$/,'')+'/Search';url.searchParams.set('subjects',code)}
  url.hash='';return url.href;
 }
 return acalogSubjectUrl(raw,subject);
}
function isMyOCC(raw){try{return /\/Student\/Courses(?:\/Search)?\/?$/i.test(new URL(raw).pathname)}catch{return false}}
const MYOCC_URL='https://colss-prod.ec.sunyocc.edu/Student/Courses';
function isOCCProfile(cfg){try{const host=new URL(cfg.catalog_url||'').hostname.toLowerCase();return host==='sunyocc.edu'||host.endsWith('.sunyocc.edu')||String(cfg.short_name||'').trim().toUpperCase()==='OCC'}catch{return String(cfg.short_name||'').trim().toUpperCase()==='OCC'}}
function acalogFallbackUrl(cfg){return isMyOCC(cfg.catalog_url||'')?(isOCCProfile(cfg)?'https://catalog.sunyocc.edu/content.php?catoid=15&navoid=755':''):cfg.catalog_url||''}
async function renderCatalog(){let inst=needInstitution();if(!inst){$('content').innerHTML=noInst();return}let [rows,imports]=await Promise.all([api('/api/courses?institution_id='+inst),api('/api/catalog-imports?institution_id='+inst)]);S.dataset=rows;const cfg=S.institutions.find(i=>i.id===inst);
 const subjects=[...new Set(rows.map(c=>String(c.code||'').split('-')[0].toUpperCase()).filter(Boolean))].sort();
 const subject=subjects.includes(S.catalogSubject)?S.catalogSubject:'';
 const query=S.catalogSearch.trim().toUpperCase();
 const filtered=rows.filter(c=>(!subject||c.code.toUpperCase().startsWith(subject+'-'))&&(!query||[c.code,c.title,c.description].some(v=>String(v||'').toUpperCase().includes(query))));
 $('content').innerHTML=sectionIntro('Course Catalog','Maintain approved course metadata by institution and catalog year.',isAdmin()?aButton(icon('plus')+' Add course','course-add','','primary')+aButton(icon('search')+' Discover course','course-discover')+aButton(icon('globe')+' Bulk Import Catalog','catalog-import-start','','primary')+aButton(icon('download')+' Browser Capture Import','catalog-browser-start'):'')+
 `<div class="status-banner" style="margin-bottom:18px">${icon('globe')} <div><strong>Official catalog:</strong> ${cfg.catalog_url?`<a target="_blank" rel="noopener" href="${attr(cfg.catalog_url)}">${esc(cfg.catalog_url)}</a>`:'Not configured. Open Settings to add an official catalog URL.'}<br/><small>Reference content remains unverified until it is confirmed against the official source.</small></div></div>`+
 `<div class="section-bar"><h2>Catalog imports</h2></div><div class="panel">${table(['Scan','Year','Found','Status',''],imports.map(j=>`<tr><td>#${j.id} · ${prettyDate(j.created_at)}</td><td>${esc(j.academic_year)}</td><td>${j.courses_found} / ${j.pages_scanned} pages</td><td>${pill(j.status)}</td><td>${aButton('View results','catalog-import-view',`data-id="${j.id}"`)}</td></tr>`))}</div>`+
 `<div class="section-bar"><h2>Course records</h2><div class="actions"><span class="muted tiny">${filtered.length} shown of ${rows.length} saved</span>${isAdmin()&&rows.length?aButton('Delete all course records','course-delete-all',`data-count="${rows.length}"`,'danger'):''}</div></div>`+
 `<form id="catalog-record-filter" class="catalog-filters"><div class="field"><label for="catalog-subject-filter">Subject code</label><select id="catalog-subject-filter" name="subject"><option value="">All subjects</option>${subjects.map(code=>`<option value="${attr(code)}" ${code===subject?'selected':''}>${esc(code)}</option>`).join('')}</select></div>${input('query','Find courses',S.catalogSearch,'search','Search course code, title, or description')}<button class="btn small" type="submit">Filter courses</button>${(subject||query)?aButton('Clear filters','catalog-record-clear'):''}</form>`+
 `<div class="panel">${table(['Course' ,'Title','Academic year','Source status','Version',''],filtered.map(c=>`<tr><td><strong>${esc(c.code)}</strong><br/><small>${esc(c.credits||'Credits not specified')} credits</small></td><td>${esc(c.title)}</td><td>${esc(c.academic_year||'Any')}</td><td>${c.last_verified_at?pill('verified'):pill('needs_review')}</td><td>v${c.version}</td><td>${aButton('Edit','course-edit',`data-id="${c.id}"`)} ${isAdmin()?aButton('Delete','course-delete',`data-id="${c.id}"`,'danger'):''} ${c.source_url?aButton('Verify source','source-verify',`data-id="${c.id}" data-type="course"`):''}</td></tr>`))}</div>`;
} 
function catalogImportForm(){
 const cfg=S.institutions.find(i=>i.id===needInstitution())||{};
 // MyOCC is the default for OCC. Other institutions retain their configured
 // catalog until they explicitly select another provider.
 const myocc=isMyOCC(cfg.catalog_url||'')||isOCCProfile(cfg);
 const defaultSeed=myocc?MYOCC_URL:acalogFallbackUrl(cfg);
 return modalHead('Bulk import course catalog')+
 `<form id="catalog-import-start" class="stack">
 ${selectField('provider','Catalog source',[["myocc","MyOCC Self-Service (default for OCC)"],["acalog","Academic Catalog / Acalog (fallback)"]],myocc?'myocc':'acalog')}
 ${input('seed_url','Course catalog URL',defaultSeed,'url','MyOCC is the default for OCC. Select Acalog to use the academic catalog as a fallback.',true)}
 ${input('academic_year','Catalog academic year',cfg.academic_year||'','text','The selected year is stored on imported records. MyOCC itself does not guarantee historical year-specific data.',true)}
 ${input('subject_code','Subject codes (optional)','','text','MyOCC: CIS,CSC,MATH (comma-separated). Acalog fallback: one code. Leave blank for discovery.')}
 ${selectField('max_pages','Maximum result pages',[[50,'50 (quick check)'],[250,'250'],[1000,'1,000 (recommended)'],[3500,'3,500 (large import)']],250)}
 <div class="callout">MyOCC uses a local Chromium/Edge browser to scan its dynamic search results. Choose <strong>Academic Catalog / Acalog (fallback)</strong> to activate the existing Acalog importer. Results from either source are staged for approval; MyOCC data is not automatically verified as catalog-year authoritative.</div>
 ${formFooter('Scan courses')}</form>`;
}
function catalogBrowserCaptureForm(){
 const cfg=S.institutions.find(i=>i.id===needInstitution())||{};
 return modalHead('Import a catalog captured in your browser')+
 `<div class="stack"><div class="callout"><strong>Use when automatic catalog scans fail.</strong> Open the official course listing in Chrome or Edge. The browser capture script reads public catalog pages from that tab and downloads a JSON file. Nothing is uploaded until you select that file here.</div>
 <div class="catalog-subject-picker">${input('subject_code','Subject code (optional)','','text','Enter CIS, CSC, MATH, etc. Blank uses the entered catalog URL.').replace('id="f-subject_code"','id="catalog-capture-subject"')}${aButton('Open filtered course list','catalog-browser-open-subject','','small')+aButton('Use MyOCC Self-Service','catalog-browser-use-myocc','','small')}</div>
 <div class="callout">MyOCC Self-Service is a separate provider. For MyOCC, choose a subject (e.g. CIS) and use the MyOCC script. Captures may only include currently loaded results and are never automatically verified.</div><div class="stack tiny"><p><strong>1.</strong> Open <a target="_blank" rel="noopener noreferrer" href="${attr(cfg.catalog_url||'https://catalog.sunyocc.edu/content.php?catoid=15&navoid=755')}">the official Course Descriptions page</a>.</p>
 <p><strong>2.</strong> After opening the filtered catalog, click <b>Copy capture script</b> below. In the catalog tab, open Developer Tools (F12), switch to <b>Console</b>, paste the script, and press Enter. Chrome/Edge may require you to enable console pasting.</p>
 <p><strong>3.</strong> When the JSON download finishes, return here to upload it for review. Keep the browser tab open until the download completes. If the site blocks some pages, the results will be marked partial.</p></div>
 <div class="actions">${aButton('Copy capture script','catalog-browser-copy','','primary')}<a class="btn small" href="/assets/catalog_capture.js" download="catalog_capture.js">Acalog script</a><a class="btn small" href="/assets/ellucian_capture.js" download="ellucian_capture.js">MyOCC script</a></div>
 <form id="catalog-browser-upload" class="stack">
 ${input('seed_url','Official catalog URL',cfg.catalog_url||'https://catalog.sunyocc.edu/content.php?catoid=15&navoid=755','url','Can be the original catalog URL or the filtered URL you captured.',true)}
 ${input('academic_year','Catalog academic year',cfg.academic_year||'2026-2027','text','Full year, e.g. 2026-2027',true)}
 ${input('file','Browser capture JSON or saved HTML','','file','Use the downloaded JSON (recommended) or HTML saved from the catalog page.',true)}
 <div class="callout">Courses remain unverified until separately checked against their official source. You will see an import preview before accepting any changes.</div>
 ${formFooter('Preview captured courses')}</form></div>`;
}
async function showCatalogImport(id,offset=0,q=''){
 const report=await api(`/api/catalog-imports/${id}`);
 let rows={total:0,items:[],offset,limit:100};
 if(['ready','applied'].includes(report.status))rows=await api(`/api/catalog-imports/${id}/items?offset=${offset}&limit=100&q=${encodeURIComponent(q)}`);
 const counts=report.counts||{},done=['ready','applied','failed','interrupted'].includes(report.status);
 let html=modalHead('Catalog import #'+id)+`<div class="stack">
 <p><strong>${esc(report.academic_year)}</strong> · ${pill(report.status)} · ${report.pages_scanned} pages checked · <strong>${report.courses_found}</strong> unique course codes found</p>
 <p class="tiny muted wrap">Source: <a href="${attr(report.seed_url)}" target="_blank" rel="noopener noreferrer">${esc(report.seed_url)}</a></p>
 ${report.error?`<div class="callout">${esc(report.error)}<p style="margin-top:8px">If the catalog is visible in your browser, use Browser Capture Import from the Course Catalog page.</p></div>`:''}
 ${report.truncated?`<div class="callout">The scan reached its page or course limit. These results are not the complete catalog. Consider scanning a smaller department listing or increasing the page limit.</div>`:''}
 ${report.errors?.length?`<details><summary>${report.errors.length} access/retrieval issue(s)</summary><div class="quote tiny">${report.errors.map(esc).join('<hr>')}</div></details>`:''}
 ${!done?`<p class="muted">The scan is running in the background. This window will refresh automatically; you can close it and reopen from the Course Catalog page.</p>`:''}`;
 if(['ready','applied'].includes(report.status)){
  html+=`<div class="grid two"><div class="panel panel-pad"><strong>${counts.new||0}</strong><br><small>New complete records</small></div><div class="panel panel-pad"><strong>${counts.changed||0}</strong><br><small>Existing records with differences</small></div><div class="panel panel-pad"><strong>${counts.unchanged||0}</strong><br><small>Existing matches</small></div><div class="panel panel-pad"><strong>${counts.incomplete||0}</strong><br><small>Incomplete records, not imported</small></div></div>
 <div class="callout">Importing courses creates unverified reference records. The normal official-source verification remains required before a catalog description can receive a confirmed pass.</div>
 <form id="catalog-import-search" class="flex" data-id="${id}">${input('q','Filter by course or title',q,'text','CIS, CSC, Math...')}<button type="submit" class="btn small">Search results</button></form>
 <div class="panel">${table(['Course','Title','Description','Result'],rows.items.map(c=>`<tr><td><strong>${esc(c.code)}</strong></td><td>${esc(c.title)}<br><small>${esc(c.credits||'No credits')} credits</small></td><td class="tiny">${esc(c.description?c.description.slice(0,140)+(c.description.length>140?'…':''):'Not extracted')}</td><td>${pill(c.status)}</td></tr>`))}</div>
 <div class="flex justify-between"><span class="tiny muted">${rows.total?rows.offset+1:0}-${Math.min(rows.offset+rows.items.length,rows.total)} of ${rows.total} courses</span><div>${offset>0?aButton('Previous','catalog-import-page',`data-id="${id}" data-offset="${Math.max(0,offset-100)}" data-q="${attr(q)}"`):''}${offset+100<rows.total?aButton('Next','catalog-import-page',`data-id="${id}" data-offset="${offset+100}" data-q="${attr(q)}"`):''}</div></div>
 ${isAdmin()?`<div class="form-footer">${aButton('Import new courses','catalog-import-apply',`data-id="${id}" data-update="false"`,'primary')}${aButton('Import and update existing','catalog-import-apply',`data-id="${id}" data-update="true"`)}</div>`:''}`;
 }
 html+='</div>';
 if($('modal').open)$('modalContent').innerHTML=html;else modal(html);
 clearInterval(S.poll);S.poll=null;
 if(!done)S.poll=setInterval(async()=>{if(!$('modal').open){clearInterval(S.poll);S.poll=null;return}try{await showCatalogImport(id,offset,q)}catch(err){notify(err.message,'error');clearInterval(S.poll);S.poll=null}},2100);
}

function courseForm(existing){let c=existing||{};
 return modalHead(existing?'Edit catalog course':'Add catalog course')+`<form class="stack" id="${existing?'course-update':'course-create'}" ${existing?`data-id="${c.id}"`:''}>${input('code','Course code',c.code||'','text','e.g. CIS-125',true)}${input('title','Official course title',c.title||'')}${textarea('description','Official course description',c.description||'','Use approved exact wording for catalog verification')}
 <div class="form-row">${input('credits','Credits',c.credits||'')}${input('academic_year','Catalog academic year',c.academic_year||S.institutions.find(i=>i.id===needInstitution())?.academic_year||'')}</div>${textarea('prerequisites','Prerequisites',c.prerequisites||'')}${input('source_url','Direct official course URL',c.source_url||'','url','This is required for live verification')}${formFooter(existing?'Save course':'Add course')}</form>`;
}
async function renderSources(){const inst=needInstitution();if(!inst){$('content').innerHTML=noInst();return}const data=await api('/api/source-checks?institution_id='+inst);S.dataset=data;
 $('content').innerHTML=sectionIntro('Source Monitor','Review changes from authorized institutional catalog and policy webpages.',isAdmin()?aButton(icon('refresh')+' Refresh all','refresh-sources','','primary'):'')+
 `<div class="panel panel-pad" style="margin-bottom:18px"><div class="split-header"><strong>Change approval is always manual</strong>${pill('review')}</div><p class="muted" style="margin-top:7px">A changed source creates a proposal, not an automatic rule update. Confirm effective wording before approving. Failed network checks are never considered verified.</p></div>`+
 `<div class="panel">${table(['Source','Target','Checked','Status',''],data.map(s=>`<tr><td><span class="mono tiny wrap">${esc(s.url.slice(0,100))}</span></td><td>${esc(s.target_type)} #${s.target_id}</td><td>${prettyDate(s.checked_at)}</td><td>${pill(s.approved_at?'verified':s.status)}</td><td>${aButton('Inspect','source-inspect',`data-id="${s.id}"`)}</td></tr>`))}</div>`;
}
function sourceInspect(id){let s=S.dataset.find(x=>x.id===id);if(!s)return;
 modal(modalHead('Official source check #'+s.id)+`<div class="stack"><div class="flex justify-between">${pill(s.status)} <small>${prettyDate(s.checked_at)}</small></div><p class="tiny wrap"><a target="_blank" rel="noopener noreferrer" href="${attr(s.url)}">${esc(s.url)}</a></p>${s.error?`<div class="callout">${esc(s.error)}</div>`:''}<div><div class="quote-label">Previously approved reference</div><div class="quote">${esc(s.old_text||'(none)')}</div></div><div><div class="quote-label">Newly retrieved candidate (verify manually)</div><div class="quote">${esc(s.new_text||'(none)')}</div></div>${['changed','needs_review'].includes(s.status)&&!s.approved_at&&isAdmin()?`<form id="source-approve" data-id="${s.id}">${textarea('approved_text','Confirmed exact text',s.new_text||'','Only approve the authoritative passage, not unrelated page content',true)}${formFooter('Approve new version')}</form>`:''}</div>`);
}
async function renderHistory(){const jobs=await api('/api/jobs');const audits=await api('/api/audits');
 $('content').innerHTML=sectionIntro('History & Reports','Track validation batches, source revisions and prior audits.',aButton('Export all summaries','download-csv'))+
 `<div class="section-bar"><h2>Audit batches</h2></div><div class="panel">${table(['Batch','Date','Institution','Progress','Status','Export'],jobs.map(j=>`<tr><td>#${j.id}</td><td>${prettyDate(j.created_at)}</td><td>${esc(j.institution_name)}</td><td>${j.finished}/${j.total}</td><td>${pill(j.status)}</td><td>${aButton('View','job-view',`data-id="${j.id}"`)} ${aButton('ZIP','batch-zip',`data-id="${j.id}"`)}</td></tr>`))}</div>`+
 `<div class="section-bar"><h2>Recent audit history</h2></div><div class="panel">${table(['Course','Document','Date','Status',''],audits.slice(0,70).map(a=>`<tr><td>${esc(a.course_code||'-')}</td><td>${esc(a.filename)}${a.rerun_of_id?`<br/><small>Rerun of audit #${a.rerun_of_id}</small>`:''}</td><td>${prettyDate(a.completed_at||a.created_at)}</td><td>${pill(compliance(a))}</td><td>${reportActions(a)}</td></tr>`))}</div>`;
}
async function renderSettings(){let runtime=await api('/api/runtime');const inst=S.institutions||[];
 let users=isAdmin()?await api('/api/users'):[],activity=isAdmin()?await api('/api/activity'):[];
 $('content').innerHTML=sectionIntro('Settings','Manage institution profiles, account security, and offline AI status.',isAdmin()?aButton(icon('plus')+' Add institution','inst-add','','primary'):'')+
 `<div class="grid two"><div class="panel panel-pad stack"><div class="split-header"><h2>Embedded AI runtime</h2>${pill(runtime.ai.available?'ready':'review')}</div><p class="muted">${esc(runtime.ai.description)}</p><div class="quote tiny mono">Model: ${esc(runtime.ai.model)}<br/>External AI requests: Disabled<br/>AI API keys: None<br/>Source update interval: ${runtime.monitor_interval_hours} hours</div><p class="tiny muted">This software does not connect to Ollama or paid AI providers.</p></div><div class="panel panel-pad stack"><h2>My account</h2><div class="flex">${icon('lock')} <strong>${esc(S.user.username)}</strong>${pill(S.user.role)}</div><form id="password-change" class="stack">${input('old_password','Current password','','password','',true)}${input('new_password','New password','','password','12 characters or more',true)}<div><button type="submit" class="btn primary">Update password</button></div></form></div></div>`+
 `<div class="section-bar"><h2>Institution profiles</h2></div><div class="panel">${table(['Institution','Catalog address','Academic year',''],inst.map(i=>`<tr><td><strong>${esc(i.name)}</strong><br/><small>${esc(i.short_name)}</small></td><td class="wrap tiny">${esc(i.catalog_url||'(Not configured)')}</td><td>${esc(i.academic_year||'-')}</td><td>${isAdmin()?aButton('Edit','inst-edit',`data-id="${i.id}"`):''}</td></tr>`))}</div>`+
 (isAdmin()?`<div class="section-bar"><h2>Accounts</h2>${aButton('Add account','user-add')}</div><div class="panel">${table(['Username','Role','Created'],users.map(u=>`<tr><td>${esc(u.username)}</td><td>${pill(u.role)}</td><td>${prettyDate(u.created_at)}</td></tr>`))}</div><div class="section-bar"><h2>Recent activity</h2></div><div class="panel">${table(['Action','User','Detail','Time'],activity.slice(0,25).map(a=>`<tr><td>${esc(a.verb)}</td><td>${esc(a.username||'System')}</td><td>${esc(a.detail||a.target)}</td><td>${prettyDate(a.created_at)}</td></tr>`))}</div>`:'');
}
function instForm(existing){let i=existing||{};
 return modalHead(existing?'Edit institution':'Add institution')+`<form class="stack" id="${existing?'inst-update':'inst-create'}" ${existing?`data-id="${i.id}"`:''}>${input('name','Institution name',i.name||'','text','',true)}${input('short_name','Short name',i.short_name||'')}${input('academic_year','Default academic year',i.academic_year||'','text','e.g. 2026-2027')}${input('catalog_url','Official catalog homepage',i.catalog_url||'','url','HTTPS URL, used as a discovery starting point')}${input('allowed_hosts','Other approved official domains',i.allowed_hosts||'','text','Paste a hostname or full HTTPS URL. The application saves only the domain; separate entries with commas.')}${input('catalog_url_pattern','Optional catalog URL pattern',i.catalog_url_pattern||'','text','Reserved for institution-specific source patterns')}${formFooter(existing?'Save institution':'Add institution')}</form>`;
}
function userAdd(){modal(modalHead('Create account')+`<form id="user-create" class="stack">${input('username','Username','','text','',true)}${input('password','Temporary password','','password','At least 12 characters',true)}${selectField('role','Permissions',[['reviewer','Reviewer'],['admin','Administrator']],'reviewer')}${formFooter('Create account')}</form>`)}
async function loadPage(){clearInterval(S.poll);S.poll=null;S.route=decodeURIComponent(location.hash.replace(/^#\/?/,'')||'dashboard');if(!S.user)return;
 shell();try{let [section,id]=S.route.split('/');
  if(section==='dashboard')await renderDashboard();else if(section==='check')await renderCheck();else if(section==='audits')await renderAudits();else if(section==='audit')await renderAuditDetail(Number(id));else if(section==='templates')await renderTemplates();else if(section==='policies')await renderPolicies();else if(section==='catalog')await renderCatalog();else if(section==='sources')await renderSources();else if(section==='history')await renderHistory();else if(section==='settings')await renderSettings();else await renderDashboard();
 }catch(e){$('content').innerHTML=`<div class="panel panel-pad"><h2>Unable to load view</h2><p class="muted" style="margin:14px 0">${esc(e.message)}</p>${aButton('Retry','reload','','primary')}</div>`;notify(e.message,'error')}
}
async function refreshInstitutions(){S.institutions=await api('/api/institutions');if(!S.inst&&S.institutions.length)S.inst=S.institutions[0].id;}
function goto(route){location.hash=route; if(location.hash.replace('#','')===S.route)loadPage()}
async function init(){try{let boot=await api('/api/bootstrap');if(boot.needs_setup){loginUI(true);return}
 try{S.user=await api('/api/me')}catch{loginUI();return}
 await refreshInstitutions();await loadPage();
 }catch(e){$('app').innerHTML=`<div class="auth-screen"><div class="auth-card"><h2>Server connection unavailable</h2><p>${esc(e.message)}</p><button class="btn" data-act="restart">Try again</button></div></div>`}}
// Delegated command handler keeps controls responsive across full re-renders.
document.addEventListener('click',async e=>{
 const target=e.target.closest('[data-route],[data-act]');if(!target)return;
 if(target.dataset.route){e.preventDefault();goto(target.dataset.route);return}
 const act=target.dataset.act,id=Number(target.dataset.id);if(!act)return;e.preventDefault();
 try{
  if(act==='modal-close'){closeModal();return}
  if(act==='logout'){await api('/api/logout',{method:'POST'});S.user=null;loginUI();return}
  if(act==='open-new-audit'){closeModal();return goto('audit/'+id)}
  if(act==='go-check')return goto('check');if(act==='go-sources')return goto('sources');if(act==='go-audits'){if($('modal')?.open)closeModal();return goto('audits')}
  if(act==='inst-add')return modal(instForm());if(act==='inst-edit')return modal(instForm(S.institutions.find(i=>i.id===id)));
  if(act==='template-add')return templateAdd();if(act==='template-edit')return templateEdit(id);
  if(act==='template-delete'){
    if(!isAdmin())throw Error('Administrator permission required');
    const item=S.dataset.find(r=>r.id===id);if(!item)throw Error('Template not found');
    return modal(modalHead('Delete syllabus template?')+`<p>Delete <strong>${esc(item.name)}</strong>?</p><div class="callout" style="margin-top:14px">The template file will be removed. Completed audit findings remain saved. Any policies linked only to this template will be disabled so they do not become institution-wide rules.</div><div class="form-footer">${aButton('Cancel','modal-close')}${aButton('Delete template','confirm-template-delete',`data-id="${id}"`,'danger')}</div>`);
  }
  if(act==='confirm-template-delete'){
    const result=await api(`/api/templates/${id}`,{method:'DELETE'});closeModal();notify(`Template deleted${result.disabled_linked_policies?', '+result.disabled_linked_policies+' linked rule(s) disabled':''}`);return loadPage();
  }
  if(act==='policy-add')return modal(policyForm());if(act==='policy-edit')return modal(policyForm(S.dataset.find(r=>r.id===id)));
  if(act==='policy-delete'){
    if(!isAdmin())throw Error('Administrator permission required');
    const item=S.dataset.find(r=>r.id===id);if(!item)throw Error('Requirement not found');
    return modal(modalHead('Delete required policy?')+`<p>Delete <strong>${esc(item.name)}</strong>?</p><div class="callout" style="margin-top:14px">Future checks will no longer enforce this requirement. Findings from completed audit reports will stay available.</div><div class="form-footer">${aButton('Cancel','modal-close')}${aButton('Delete policy','confirm-policy-delete',`data-id="${id}"`,'danger')}</div>`);
  }
  if(act==='confirm-policy-delete'){
    await api(`/api/requirements/${id}`,{method:'DELETE'});closeModal();notify('Required policy deleted');return loadPage();
  }
  if(act==='catalog-import-start')return modal(catalogImportForm());
  if(act==='catalog-browser-start')return modal(catalogBrowserCaptureForm());
  if(act==='catalog-browser-use-myocc'){document.querySelector('#catalog-browser-upload input[name=seed_url]').value='https://colss-prod.ec.sunyocc.edu/Student/Courses';notify('MyOCC selected. Choose a subject and open the filtered course list.');return}
  if(act==='catalog-browser-open-subject'){const cfg=S.institutions.find(i=>i.id===needInstitution())||{};const original=document.querySelector('#catalog-browser-upload input[name=seed_url]')?.value||cfg.catalog_url;const subject=document.querySelector('#catalog-capture-subject')?.value||'';const url=catalogSubjectUrl(original,subject);document.querySelector('#catalog-browser-upload input[name=seed_url]').value=url;window.open(url,'_blank','noopener');notify(subject?'Opened '+subject.toUpperCase()+' course catalog. Run the capture script on that page.':'Opened full course catalog.');return}
  if(act==='catalog-record-clear'){S.catalogSubject='';S.catalogSearch='';return renderCatalog()}
  if(act==='catalog-browser-copy'){const source=document.querySelector('#catalog-browser-upload input[name=seed_url]')?.value||'';const path=isMyOCC(source)?'/assets/ellucian_capture.js':'/assets/catalog_capture.js';const response=await fetch(path,{cache:'no-store'});if(!response.ok)throw new Error('Could not load the updated catalog capture script');const script=await response.text();await navigator.clipboard.writeText(script);notify('Updated capture script copied. Paste it into the official catalog tab Console.');return}
  if(act==='catalog-import-view')return showCatalogImport(id);
  if(act==='catalog-import-page')return showCatalogImport(id,Number(target.dataset.offset)||0,target.dataset.q||'');
  if(act==='catalog-import-apply'){
    const update=target.dataset.update==='true';
    if(!confirm(update?'Apply all discovered changes to existing course records? Existing records will be versioned and marked unverified.':'Import all new courses with complete descriptions? Existing courses will remain unchanged.'))return;
    const result=await api(`/api/catalog-imports/${id}/apply`,{method:'POST',body:{update_existing:update}});
    notify(`Imported ${result.created} new course(s), updated ${result.updated}, skipped ${result.skipped}.`);closeModal();return loadPage();
  }
  if(act==='course-add')return modal(courseForm());if(act==='course-edit')return modal(courseForm(S.dataset.find(r=>r.id===id)));
  if(act==='course-delete'){
    if(!isAdmin())throw Error('Administrator permission required');
    const item=S.dataset.find(r=>r.id===id);if(!item)throw Error('Course record not found');
    return modal(modalHead('Delete course record?')+`<p>Delete <strong>${esc(item.code)} · ${esc(item.title)}</strong> (${esc(item.academic_year||'Any year')})?</p><div class="callout" style="margin-top:14px">The course reference will be removed. Existing audit reports remain unchanged, but future or rerun audits cannot compare to this course until it is imported again.</div><div class="form-footer">${aButton('Cancel','modal-close')}${aButton('Delete course','confirm-course-delete',`data-id="${id}"`,'danger')}</div>`);
  }
  if(act==='confirm-course-delete'){
    await api(`/api/courses/${id}`,{method:'DELETE'});closeModal();notify('Course record deleted');return loadPage();
  }
  if(act==='course-delete-all'){
    if(!isAdmin())throw Error('Administrator permission required');
    const count=Number(target.dataset.count);
    const name=S.institutions.find(i=>i.id===needInstitution())?.name||'selected institution';
    return modal(modalHead('Delete all course records?')+`<p>You're about to delete <strong>${count} course record(s)</strong> belonging to <strong>${esc(name)}</strong>.</p><div class="callout" style="margin-top:14px">This removes ALL saved course catalog references for this institution, including records outside the current subject filter. Other institutions, policies, templates and previous audit reports remain intact. This cannot be undone.</div><div class="form-footer">${aButton('Cancel','modal-close')}${aButton('Continue to final confirmation','course-delete-all-final',`data-count="${count}"`,'danger')}</div>`);
  }
  if(act==='course-delete-all-final'){
    const count=Number(target.dataset.count);
    return modal(modalHead('Final confirmation: delete all courses')+`<p>This is your second confirmation for deleting <strong>${count} course record(s)</strong>. Type <strong>DELETE ALL</strong> exactly to enable the final delete.</p><form id="course-delete-all-form" data-count="${count}" class="stack" style="margin-top:15px">${input('confirmation','Confirmation phrase','','text','Type DELETE ALL (uppercase)',true)}<div class="form-footer">${aButton('Cancel','modal-close')}<button class="btn danger" type="submit">Permanently delete all ${count} records</button></div></form>`);
  }
  if(act==='user-add')return userAdd();if(act==='source-inspect')return sourceInspect(id);
  if(act==='open-audit')return goto('audit/'+id);
  if(act==='rerun-audit'){
    const result=await api(`/api/audits/${id}/rerun`,{method:'POST'});
    notify(`New audit #${result.audit_id} queued from saved report #${id}`);
    return watchJob(result.job_id);
  }
  if(act==='delete-audit'){
    let a=S.detail?.audit?.id===id?S.detail.audit:S.dataset?.find(x=>x.id===id);
    if(!a)a=(await api(`/api/audits/${id}`)).audit;
    return modal(modalHead('Delete audit report?')+`<p><strong>${esc(a.filename)}</strong> · Audit #${id}</p><div class="callout">This permanently deletes this report, its findings and its saved syllabus copy. Other audits, including reruns, will remain available. This cannot be undone.</div><div class="form-footer">${aButton('Cancel','modal-close')}${aButton('Delete report permanently','confirm-delete-audit',`data-id="${id}"`,'danger')}</div>`);
  }
  if(act==='confirm-delete-audit'){
    const result=await api(`/api/audits/${id}`,{method:'DELETE'});
    closeModal();S.detail=null;S.selectedFinding=null;
    notify(result.stored_file_removed?'Report and stored syllabus deleted':'Report deleted; saved syllabus file could not be removed. Check server storage.',result.stored_file_removed?'success':'error');
    return goto('history');
  }
  if(act==='show-finding'){S.selectedFinding=id;const f=S.detail.findings.find(x=>x.id===id);document.querySelectorAll('.issue-button').forEach(x=>x.classList.toggle('selected',Number(x.dataset.id)===id));$('inspector').innerHTML=inspector(f);focusLocation(f?.location);return}
  if(act==='accept-finding'||act==='dismiss-finding'){
   const key=act==='accept-finding'?'accepted':'dismissed';await api('/api/findings/'+id,{method:'PUT',body:{[key]:Number(target.dataset.value)===1,...(key==='accepted'?{dismissed:false}:{accepted:false})}});
   S.detail.findings= S.detail.findings.map(f=>f.id===id?{...f,[key]:Number(target.dataset.value),[key==='accepted'?'dismissed':'accepted']:0}:f);
   $('inspector').innerHTML=inspector(S.detail.findings.find(x=>x.id===id));notify('Finding review updated');return}
  if(act==='source-verify'){
   notify('Checking official source. This depends on the college website.');const r=await api('/api/sources/check',{method:'POST',body:{institution_id:needInstitution(),target_type:target.dataset.type,target_id:id}});notify('Source status: '+r.status);return loadPage()}
  if(act==='refresh-sources'){
   notify('Checking approved institutional source URLs');const r=await api('/api/sources/refresh',{method:'POST',body:{institution_id:needInstitution()}});notify('Checked '+r.checks.length+' source(s)');return loadPage()}
  if(act==='course-discover')return modal(modalHead('Discover official course')+`<form id="course-search" class="stack">${input('code','Course code','','text','e.g. CIS-125',true)}${formFooter('Search approved catalog')}</form><div id="discovery-result"></div>`);
  if(act==='course-link'){
    let course=S.dataset.find(c=>c.code===target.dataset.code);if(!course){notify('Add this course record first, then set its official source URL','error');return}
    await api('/api/courses/'+course.id,{method:'PUT',body:{source_url:target.dataset.url}});closeModal();notify('Course URL saved; verify its official content');return loadPage()}
  if(act==='download-csv')return download('/api/audits/export.csv','syllabus-audits.csv');
  if(act==='report-pdf')return download(`/api/audits/${id}/report.pdf`,`audit-${id}.pdf`);
  if(act==='report-docx')return download(`/api/audits/${id}/report.docx`,`audit-${id}.docx`);
  if(act==='batch-zip')return download(`/api/jobs/${id}/export.zip`,`audit-batch-${id}.zip`);
  if(act==='corrected')return download(`/api/audits/${id}/corrected.docx`,`corrected-${id}.docx`);
  if(act==='open-original'){const a=S.detail.audit; if(a.filetype==='.pdf'){window.open(`/api/audits/${id}/document`,'_blank','noopener')}else await download(`/api/audits/${id}/document`,a.filename);return}
  if(act==='compare-audit'){const r=await api(`/api/audits/${id}/compare`);return modal(modalHead('Compared with previous audit')+`<p class="muted">${r.previous_audit_id?'Compared against audit #'+r.previous_audit_id:'No earlier audit of this course is available.'}</p><div class="stack" style="margin-top:15px">${r.changes.map(c=>`<div class="checkbox-row"><strong>${esc(c.title)}</strong><span class="muted">${esc(c.previous)} → ${esc(c.current)}</span></div>`).join('')||'<p>No classification changes detected.</p>'}</div>`)}
  if(act==='job-view'){let j=await api('/api/jobs/'+id);return modal(modalHead('Batch #'+id)+`<p class="muted">${j.job.finished} of ${j.job.total} completed · ${esc(j.job.status)}</p><div class="line"></div>${table(['File','Status','Results',''],j.audits.map(a=>`<tr><td>${esc(a.filename)}</td><td>${pill(compliance(a))}</td><td>${a.passed} passed / ${a.failed} failed</td><td>${a.status==='complete'?`<a href="#audit/${a.id}">Review</a>`:''}</td></tr>`))}<div class="form-footer">${aButton('Download batch ZIP','batch-zip',`data-id="${id}"`)}${['interrupted','complete_with_errors'].includes(j.job.status)?aButton('Retry interrupted files','job-retry',`data-id="${id}"`):''}</div>`)}
  if(act==='job-retry'){await api(`/api/jobs/${id}/retry`,{method:'POST'});closeModal();notify('Retry queued');return loadPage()}
  if(act==='reload')return loadPage();if(act==='restart')return location.reload();
 }catch(err){notify(err.message,'error')}
});
async function watchJob(jobID){
 modal(modalHead('Rerunning syllabus checks')+`<div id="rerun-progress" class="stack"><p class="muted">Checking saved syllabus against current requirements...</p></div>`);
 async function refresh(){
  try{
   let j=await api(`/api/jobs/${jobID}`),a=j.audits[0],finished=['complete','complete_with_errors','interrupted'].includes(j.job.status);
   let box=$('rerun-progress');if(!box){clearInterval(S.poll);S.poll=null;return}
   box.innerHTML=`<p>${pill(j.job.status)} · ${j.job.finished} of ${j.job.total} processed</p><div class="progress"><span style="width:${j.job.total?Math.round(j.job.finished/j.job.total*100):0}%"></span></div>`+
   (finished?`<div class="form-footer">${a?aButton('Open new audit','open-new-audit',`data-id="${a.id}"`,'primary'):''}${aButton('All audit results','go-audits')}</div>`:'');
   if(finished){clearInterval(S.poll);S.poll=null}
  }catch(err){clearInterval(S.poll);S.poll=null;notify(err.message,'error')}
 }
 clearInterval(S.poll);S.poll=setInterval(refresh,900);await refresh();
}
async function download(url,filename){const response=await fetch(url,{credentials:'same-origin'});if(!response.ok){let msg='Download failed';try{msg=(await response.json()).detail||msg}catch{}throw Error(msg)}
 const blob=await response.blob(),a=document.createElement('a'),uri=URL.createObjectURL(blob);a.href=uri;a.download=filename;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(uri),2000)}

// Form submissions for all administrative and review workflows.
document.addEventListener('submit',async e=>{
 const form=e.target;if(!(form instanceof HTMLFormElement))return;e.preventDefault();const type=form.id;
 const data=formDataObj(form),id=Number(form.dataset.id);const btn=form.querySelector('[type=submit]');if(btn)btn.disabled=true;
 try{
  if(type==='setup-form'){await api('/api/setup',{method:'POST',body:data});loginUI();notify('Administrator created. Sign in to continue.');return}
  if(type==='login-form'){S.user=await api('/api/login',{method:'POST',body:data});await refreshInstitutions();await loadPage();return}
  if(type==='upload-form'){
   if(!S.files.length)throw Error('Select at least one syllabus');if(S.files.length>100)throw Error('Limit is 100 files per batch');
   const payload=new FormData();payload.set('institution_id',data.institution_id);payload.set('template_id',data.template_id);payload.set('academic_year',data.academic_year||'');
   for(const f of S.files)payload.append('files',f,f.name);
   let result=await api('/api/audits/upload',{method:'POST',body:payload});S.files=[];notify(`Batch #${result.job_id} queued successfully`);
   // Preserve the job view as a live, visible modal until all its uploads finish.
   let jobID=result.job_id;
   modal(modalHead('Audit batch processing')+`<div id="job-progress" class="stack"><p class="muted">Starting...</p></div>`);
   async function updateProgress(){try{let j=await api('/api/jobs/'+jobID),p=j.job.total?Math.floor(j.job.finished/j.job.total*100):0;
      let box=$('job-progress');if(!box){clearInterval(S.poll);return}
      box.innerHTML=`<p>${j.job.finished} / ${j.job.total} processed · ${pill(j.job.status)}</p><div class="progress"><span style="width:${p}%"></span></div><div class="stack">${j.audits.map(a=>`<div class="flex justify-between"><span>${esc(a.filename)}</span>${pill(a.status)}</div>`).join('')}</div>${['complete','complete_with_errors'].includes(j.job.status)?`<div class="form-footer">${aButton('View audits','go-audits','','primary')}${aButton('Batch ZIP','batch-zip',`data-id="${jobID}"`)}</div>`:''}`;
      if(['complete','complete_with_errors'].includes(j.job.status)){clearInterval(S.poll);S.poll=null}
   }catch(err){notify(err.message,'error')}}
   clearInterval(S.poll);S.poll=setInterval(updateProgress,950);await updateProgress();return;
  }
  if(type==='inst-create'||type==='inst-update'){
   const method=type==='inst-create'?'POST':'PUT',url=type==='inst-create'?'/api/institutions':'/api/institutions/'+id;
   await api(url,{method,body:data});closeModal();await refreshInstitutions();notify('Institution saved');return loadPage()}
  if(type==='template-create'){
   const f=form.querySelector('input[name=file]').files[0];if(!f)throw Error('Select template DOCX or PDF');
   const fd=new FormData();fd.set('institution_id',needInstitution());for(const [k,v] of Object.entries(data))if(k!=='file')fd.set(k,v);fd.set('file',f);
   await api('/api/templates/upload',{method:'POST',body:fd});closeModal();notify('Template uploaded and sections extracted');return loadPage()}
  if(type==='template-update'){
   const t=S.dataset.find(t=>t.id===id),sections=JSON.parse(t.sections_json||'[]');
   form.querySelectorAll('#template-section-list input[data-index]').forEach(c=>sections[Number(c.dataset.index)].required=c.checked);
   form.querySelectorAll('#template-section-list select[data-section-mode]').forEach(c=>sections[Number(c.dataset.sectionMode)].mode=c.value);
   if(data.new_heading?.trim())sections.push({heading:data.new_heading.trim(),required:true,mode:'heading',expected_text:'',location:'Added manually',sample:''});
   await api('/api/templates/'+id,{method:'PUT',body:{name:data.name,academic_year:data.academic_year,notes:data.notes,active:data.active,sections_json:sections}});
   closeModal();notify('Template updated');return loadPage()}
  if(type==='policy-create'||type==='policy-update'){
   const payload={...data,variants_json:(data.variants||'').split('\n').map(x=>x.trim()).filter(Boolean)};delete payload.variants;
   if(type==='policy-create')payload.institution_id=needInstitution();
   await api(type==='policy-create'?'/api/requirements':'/api/requirements/'+id,{method:type==='policy-create'?'POST':'PUT',body:payload});closeModal();notify('Requirement saved');return loadPage()}
  if(type==='catalog-import-start'){
    const myocc=data.provider==='myocc';
    const codes=String(data.subject_code||'').split(/[,;]/).map(x=>x.trim().toUpperCase()).filter(Boolean);
    if(!myocc&&codes.length>1)throw Error('Select one subject for an Acalog scan, or choose MyOCC for multiple subjects.');
    if(myocc&&!isMyOCC(data.seed_url))throw Error('Select a MyOCC /Student/Courses URL for this provider.');
    if(!myocc&&isMyOCC(data.seed_url))throw Error('Select MyOCC in Catalog source to scan Self-Service.');
    const url=myocc?data.seed_url:catalogSubjectUrl(data.seed_url,codes[0]||'');
    const result=await api('/api/catalog-imports',{method:'POST',body:{institution_id:needInstitution(),seed_url:url,subject_codes:myocc?codes.join(','):'',academic_year:data.academic_year,max_pages:Number(data.max_pages)}});
    notify('Catalog scan started');return showCatalogImport(result.id);
  }
  if(type==='catalog-browser-upload'){
    const file=form.querySelector('input[name=file]')?.files?.[0];
    if(!file)throw Error('Select the downloaded catalog JSON file or saved HTML');
    const fd=new FormData();fd.set('institution_id',needInstitution());
    fd.set('academic_year',data.academic_year);fd.set('seed_url',data.seed_url);fd.set('file',file);
    const result=await api('/api/catalog-imports/capture',{method:'POST',body:fd});
    notify(`Captured ${result.courses_found} course records for review.`);
    return showCatalogImport(result.id);
  }
  if(type==='catalog-import-search')return showCatalogImport(id,0,data.q||'');
  if(type==='catalog-record-filter'){S.catalogSubject=(data.subject||'').toUpperCase();S.catalogSearch=data.query||'';return renderCatalog()}
  if(type==='course-delete-all-form'){
    if(!isAdmin())throw Error('Administrator permission required');
    if(data.confirmation!=='DELETE ALL')throw Error('Type DELETE ALL exactly to confirm.');
    const count=Number(form.dataset.count);
    const result=await api('/api/courses/all',{method:'DELETE',body:{institution_id:needInstitution(),expected_count:count,confirmation:data.confirmation}});
    closeModal();S.catalogSubject='';S.catalogSearch='';notify(`${result.deleted} course record(s) permanently deleted`);return loadPage();
  }
  if(type==='course-create'||type==='course-update'){
   let payload={...data};if(type==='course-create')payload.institution_id=needInstitution();
   await api(type==='course-create'?'/api/courses':'/api/courses/'+id,{method:type==='course-create'?'POST':'PUT',body:payload});closeModal();notify('Course reference saved');return loadPage()}
  if(type==='source-approve'){
   await api('/api/sources/'+id+'/approve',{method:'POST',body:{approved_text:data.approved_text}});closeModal();notify('New official reference version approved');return loadPage()}
  if(type==='course-search'){
   const result=await api('/api/sources/discover',{method:'POST',body:{institution_id:needInstitution(),code:data.code}});
   $('discovery-result').innerHTML=`<div class="line"></div><p class="muted tiny">Checked ${result.checked_pages} linked official page(s). Results must be manually verified.</p><div class="stack" style="margin-top:12px">${result.candidates.map(c=>`<div class="panel panel-pad"><div class="tiny wrap"><a href="${attr(c.url)}" target="_blank" rel="noopener noreferrer">${esc(c.url)}</a></div><p class="muted tiny" style="margin:11px 0">${esc(c.text.slice(0,350))}</p>${aButton('Link to existing course','course-link',`data-code="${attr(data.code.toUpperCase())}" data-url="${attr(c.url)}"`)}</div>`).join('')||'<p class="muted">No matching official pages found. Add a direct course URL manually.</p>'}</div>`;return}
  if(type==='user-create'){await api('/api/users',{method:'POST',body:data});closeModal();notify('Account created');return loadPage()}
  if(type==='password-change'){await api('/api/users/password',{method:'POST',body:data});form.reset();notify('Password updated');return}
 }catch(err){notify(err.message,'error')}
 finally{if(btn)btn.disabled=false}
});
document.addEventListener('change',async e=>{
 if(e.target?.id==='f-provider' && e.target.closest('#catalog-import-start')){
   const cfg=S.institutions.find(i=>i.id===needInstitution())||{};
   const seed=document.querySelector('#catalog-import-start input[name=seed_url]');
   seed.value=e.target.value==='myocc'?MYOCC_URL:acalogFallbackUrl(cfg);
 }
 if(e.target?.id==='institution-switch'){S.inst=Number(e.target.value);S.catalogSubject='';S.catalogSearch='';await loadPage()}
 if(e.target?.id==='catalog-subject-filter'){S.catalogSubject=e.target.value;S.catalogSearch=document.querySelector('#catalog-record-filter input[name=query]')?.value||'';await renderCatalog()}
 if(e.target?.name==='institution_id'&&S.route==='check'){S.inst=Number(e.target.value);await loadPage()}
});
window.addEventListener('hashchange',()=>{if(S.user){closeModal();loadPage()}});
init();
