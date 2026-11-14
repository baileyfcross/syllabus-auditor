'use strict';
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const script=fs.readFileSync('app/static/app.js','utf8');
function slice(start,end){const a=script.indexOf(start);const b=script.indexOf(end,a+start.length);if(a<0||b<0)throw new Error('UI helper not found');return script.slice(a,b)}
const context={
 URL, S:{institutions:[]}, needInstitution:()=>1,
 modalHead:(x)=>x+'\n',
 selectField:(name,label,options,selected)=>`<select data-name="${name}" data-selected="${selected}">${options.map(o=>o[1]).join('|')}</select>`,
 input:(name,label,value)=>`<input name="${name}" value="${value}">`,
 formFooter:()=>'',
};
vm.createContext(context);
const helpers=slice('function isMyOCC(raw)', 'function catalogImportForm(){');
const ui=slice('function catalogImportForm(){','function catalogBrowserCaptureForm(){');
vm.runInContext(helpers+ui,context);
context.S.institutions=[{id:1,short_name:'OCC',catalog_url:'https://catalog.sunyocc.edu/content.php?catoid=15&navoid=755',academic_year:'2026-27'}];
let markup=vm.runInContext('catalogImportForm()',context);
assert.match(markup,/data-selected="myocc"/);
assert.match(markup,/value="https:\/\/colss-prod\.ec\.sunyocc\.edu\/Student\/Courses"/);
assert.match(markup,/Academic Catalog \/ Acalog \(fallback\)/);
assert.equal(vm.runInContext('acalogFallbackUrl(S.institutions[0])',context),'https://catalog.sunyocc.edu/content.php?catoid=15&navoid=755');
context.S.institutions=[{id:1,short_name:'XYZ',catalog_url:'https://catalog.example.edu/courses',academic_year:'2026-27'}];
markup=vm.runInContext('catalogImportForm()',context);
assert.match(markup,/data-selected="acalog"/);
assert.match(markup,/value="https:\/\/catalog\.example\.edu\/courses"/);
assert.match(script,/seed\.value=e\.target\.value==='myocc'\?MYOCC_URL:acalogFallbackUrl\(cfg\);/);
console.log('Bulk import source selector: OCC MyOCC default, Acalog fallback, other institutions preserved.');
