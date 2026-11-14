'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const js=fs.readFileSync('app/static/app.js','utf8');
const first=js.indexOf('function canManageAudit(a)');
const last=js.indexOf('async function renderAudits()',first);
const ctx={S:{user:{id:7,role:'reviewer'}},aButton:(label,act,extra)=>`<button data-act="${act}" ${extra}>${label}</button>`};
vm.createContext(ctx);
vm.runInContext(js.slice(first,last),ctx);
const a={id:15,series_id:3,created_by:7,status:'complete',approved_at:''};
let buttons=vm.runInContext('reportActions('+JSON.stringify(a)+')',ctx);
assert.match(buttons,/data-act="open-audit"[^>]+data-series="3"/);
assert.match(buttons,/data-act="rerun-audit"/);
assert.match(buttons,/data-act="delete-syllabus"[^>]+data-series="3"/);
buttons=vm.runInContext('reportActions('+JSON.stringify({...a,created_by:8})+')',ctx);
assert.doesNotMatch(buttons,/data-act="rerun-audit"|data-act="delete-syllabus"/);
const start=js.indexOf('function renderRevisionHistory(');
const end=js.indexOf('async function renderAuditDetail(',start);
const c2={table:(_headers,rows)=>rows.join(''),esc:x=>String(x),prettyDate:x=>x,pill:x=>String(x)};
vm.createContext(c2);vm.runInContext(js.slice(start,end),c2);
const history={series_id:3,current_audit_id:15,revisions:[
 {id:15,revision_number:2,created_at:'2026-11-14',completed_at:'2026-11-14',status:'complete',approved_at:'',passed:4,failed:1,review:2,pending_findings:1},
 {id:3,revision_number:1,created_at:'2026-11-13',completed_at:'2026-11-13',status:'complete',approved_at:'2026-11-13',passed:5,failed:0,review:1,pending_findings:0}
]};
const html=vm.runInContext('renderRevisionHistory('+JSON.stringify(history)+',15)',c2);
assert.match(html,/Check history \(2\)/);
assert.match(html,/#syllabus\/3/);
assert.match(html,/#audit\/3/);
assert.match(html,/Check #1/);
assert.match(html,/Approved copy/);
assert.match(js,/else if\(section==='syllabus'\)/);
assert.match(js,/\/api\/audit-series\/\$\{series\}/);
assert.ok(js.includes("api('/api/audits/'+id+'/history')"));
console.log('PASS stable syllabus series actions and revision history');
