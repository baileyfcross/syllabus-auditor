/* Syllabus Auditor: capture currently rendered MyOCC / Ellucian Self-Service catalog results.
   Run on an official public /Student/Courses/Search?subjects=CIS page.
   No remote services or credentials. The JSON stays in the user's browser until uploaded. */
(async () => {
  'use strict';
  const origin = new URL(location.href);
  if (!/^\/Student\/Courses\/Search\/?$/i.test(origin.pathname) ||
      !/^https:$/.test(origin.protocol) ||
      !origin.searchParams.get('subjects')) {
    alert('Open MyOCC Course Search for one subject, such as /Student/Courses/Search?subjects=CIS, before running this script.');
    return;
  }
  const subject = origin.searchParams.get('subjects').trim().toUpperCase();
  if (!/^[A-Z]{2,6}$/.test(subject)) { alert('Select exactly one course subject first.'); return; }
  const clean = s => String(s || '').replace(/\u00a0/g, ' ').replace(/[\t ]+/g, ' ').trim();
  const heading = new RegExp('^(' + subject + ')[ -](\\d{2,4}[A-Z]?)\\s+(.+?)(?:\\s*\\((\\d+(?:\\.\\d+)?)\\s+Credits?\\))?$', 'i');
  const matchHeading = s => {
    const m = clean(s).replace(/\s+/g, ' ').match(heading);
    if (!m || m[3].length < 3 || m[3].length > 170) return null;
    return {code:`${subject}-${m[2].toUpperCase()}`,title:clean(m[3]),credits:m[4] || ''};
  };
  const items = new Map(), diagnostics = {headings_seen:0, examples:[], rendered_pages:1};
  const stop = /^(Requisites?:|Locations?:|Offered:|No sections match|Non-Term Section:|Table for sections|Instructors|Meeting Information|Dates|Seats Available|Course Description|Additional Information|Page\s+\d+)/i;
  const save = record => {
    if (!record || record.code.split('-')[0]!==subject) return;
    const previous = items.get(record.code);
    if (!previous || record.description.length > previous.description.length) items.set(record.code,record);
  };
  const textLines = value => String(value || '').split(/\n+/).map(clean).filter(Boolean);
  const processLines = (lines) => {
    const starts=[];
    for (let i=0; i<lines.length; i++) {
      const h=matchHeading(lines[i]); if (h) {
        starts.push([i,h]); diagnostics.headings_seen++;
        if (diagnostics.examples.length < 8) diagnostics.examples.push(lines[i]);
      }
    }
    for(let j=0;j<starts.length;j++) {
      const [at,h]=starts[j];const limit=j+1<starts.length?starts[j+1][0]:lines.length;
      const body=[];let prerequisites='';
      for(let k=at+1;k<Math.min(limit,at+80);k++) {
        const line=lines[k];
        if(/^No description available\.?$/i.test(line))break;
        if(stop.test(line)) { if(/^Requisites?:/i.test(line))prerequisites=clean(line.replace(/^Requisites?:\s*/i,''));break; }
        if (/^Search for Courses|^Filter Results|^Advanced Search Selection|^Filters Applied|^Results View/i.test(line))break;
        body.push(line);
        if (body.join(' ').length>4800)break;
      }
      const description=clean(body.join(' ')).slice(0,5000);
      save({...h,description:description.length>=24?description:'',prerequisites,
        source_url:origin.href});
    }
  };
  // Use visible innerText instead of textContent: live search pages often ship
  // hidden detail templates containing fictitious empty course headings.
  processLines(textLines(document.body.innerText));
  // Some Self-Service templates keep the course title and body in a single
  // card and split lines differently than the full document's innerText.
  for(const titleEl of document.querySelectorAll('h2,h3,h4,h5,.course-title,[class*="courseTitle"]')) {
    const h=matchHeading(titleEl.innerText); if(!h)continue;
    const wrapper=titleEl.closest('article,li,[class*="course-result"],[class*="courseResult"],section') || titleEl.parentElement;
    if(!wrapper)continue;
    const lines=textLines(wrapper.innerText), at=lines.findIndex(x=>matchHeading(x)?.code===h.code);
    if(at<0)continue;
    processLines(lines.slice(at));
  }
  const courses=[...items.values()].sort((a,b)=>a.code.localeCompare(b.code));
  const withDescription=courses.filter(c=>c.description.length>=24).length;
  const errors=['MyOCC is a live course-search interface. This export covers only results currently rendered in the browser. Additional pages, subjects, or hidden results may not be included.'];
  if(!courses.length)errors.push('No visible course headings recognized. Select a subject, wait for results to load, and select Catalog Listing.');
  if(withDescription<courses.length)errors.push(`${courses.length-withDescription} course(s) lack visible descriptions.`);
  const result={format:'syllabus-auditor-browser-capture-v1',source_url:origin.href,
    subject_filter:subject,captured_at:new Date().toISOString(),pages_checked:1,
    complete:false,errors,diagnostics,courses};
  const blob=new Blob([JSON.stringify(result,null,2)],{type:'application/json'});
  const href=URL.createObjectURL(blob), a=document.createElement('a');
  a.href=href;a.download=`OCC_SelfService_${subject}_Browser_Capture.json`;
  document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(href),60000);
  console.info('Syllabus Auditor MyOCC capture:', {courses:courses.length, descriptions:withDescription,diagnostics,errors});
})();
