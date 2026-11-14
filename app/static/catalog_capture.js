/*
 * Syllabus Auditor browser-side catalog capture for Acalog/Modern Campus sites.
 * Run this with the public Course Descriptions page open (F12 -> Console).
 * All requests stay on this catalog's origin; no data is transmitted to any
 * outside site. A JSON file is downloaded for explicit review in the app.
 * Do not run this against a catalog you are not authorized to access.
 */
(async () => {
  'use strict';
  if (window.__syllabusCatalogCaptureRunning) {
    alert('A catalog capture is already running in this tab.');
    return;
  }
  window.__syllabusCatalogCaptureRunning = true;
  const seed = new URL(location.href);
  // Acalog course filters often add a fragment, which must not cause a duplicate fetch.
  seed.hash = '';
  const catoid = seed.searchParams.get('catoid') || seed.searchParams.get('cur_cat_oid');
  const selectedSubject = cleanSubject(seed.searchParams.get('filter[27]'));
  const navoid = seed.searchParams.get('navoid');
  if (!/^\/content\.php$/i.test(seed.pathname) || !catoid || !navoid) {
    alert('Open the official Acalog Course Descriptions page before running the capture.');
    window.__syllabusCatalogCaptureRunning = false;
    return;
  }
  function cleanSubject(s){return String(s||'').trim().toUpperCase();}
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const clean = (s) => String(s || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
  const coursePattern = /^\s*([A-Z]{2,6})\s*[- ]?\s*(\d{2,4}[A-Z]?)\s*(?:[-–—:]\s*|\s+)(.{4,180}?)\s*$/i;
  const pages = new Map(), courses = new Map(), details = new Map(), errors = [];
  const diagnostics = { headingCandidates: 0, textFallbackMatches: 0, samples: [] };
  const remember = (text) => {
    const value = clean(text).slice(0, 150);
    if (value && diagnostics.samples.length < 12 && !diagnostics.samples.includes(value)) diagnostics.samples.push(value);
  };
  const maxPages = 1500, maxDetails = 6000;
  let complete = true;
  let requested = 0;
  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;z-index:2147483647;bottom:16px;right:16px;background:#1b2940;color:white;padding:14px 18px;border-radius:12px;font:13px system-ui;box-shadow:0 7px 30px #0005;max-width:340px';
  overlay.textContent = 'Syllabus Auditor: Starting catalog capture...';
  document.body.appendChild(overlay);
  const update = (stage) => {
    overlay.textContent = `Syllabus Auditor: ${stage} · ${pages.size} listing pages · ${courses.size} courses · ${details.size} course detail links`;
  };
  const inScope = (candidate, courseDetail = false) => {
    try {
      const u = new URL(candidate, seed.href);
      if (u.origin !== seed.origin || u.protocol !== 'https:') return null;
      if ((u.searchParams.get('catoid') || u.searchParams.get('cur_cat_oid')) !== catoid) return null;
      if (!courseDetail && selectedSubject && cleanSubject(u.searchParams.get('filter[27]'))!==selectedSubject) return null;
      if (!courseDetail && (u.pathname !== seed.pathname || u.searchParams.get('navoid') !== navoid)) return null;
      if (courseDetail && !/preview_course(_nopop)?\.php$/i.test(u.pathname)) return null;
      return u;
    } catch { return null; }
  };
  const getCourseHeading = (s) => {
    const value = clean(s);
    const m = value.match(coursePattern);
    if (!m || /^(?:course descriptions?|course search|credits?|credit hours?|catalog|add to|expand|collapse|print|page\s+\d)/i.test(m[3])) return null;
    const title = clean(m[3]).replace(/\s*\(\s*\d+(?:\.\d+)?\s*credits?\s*\)\s*$/i, '').slice(0, 180);
    if (title.length < 4) return null;
    return { code: `${m[1].toUpperCase()}-${m[2].toUpperCase()}`, title };
  };
  const save = (item) => {
    if (!item.code || !item.title || (selectedSubject && item.code.split('-')[0]!==selectedSubject)) return;
    item.description = clean(item.description).slice(0, 5000);
    item.credits = clean(item.credits).slice(0, 30);
    item.prerequisites = clean(item.prerequisites).slice(0, 800);
    const prior = courses.get(item.code);
    if (!prior || item.description.length > prior.description.length) courses.set(item.code, item);
  };
  const parseCredits = (s) => (clean(s).match(/(?:\bcredits?(?:\s+hours?)?\s*:?\s*(\d+(?:\.\d+)?)\b|\b(\d+(?:\.\d+)?)\s*(?:credit\s+hours?|credits?(?:\s+hours?)?)\b)/i) || []).slice(1).find(Boolean) || '';
  const elementText = (el) => {
    if (!el) return '';
    const walker = el.ownerDocument.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    const fragments = [];
    let node;
    while ((node = walker.nextNode())) { const part=clean(node.nodeValue); if (part) fragments.push(part); }
    return clean(fragments.join(' '));
  };
  const parsePrereqs = (s) => (clean(s).match(/(?:pre-?requisites?\s*:\s*)(.{0,500})/i) || [,''])[1];
  const detailFromLink = (a) => {
    const raw = [a.getAttribute('href'), a.getAttribute('onclick'), a.getAttribute('data-url')].join(' ');
    const match = raw.match(/(?:preview_course(?:_nopop)?\.php\?[^\s"'<>);]+)|(?:\bcoid=(\d+)\b)/i);
    if (!match) return null;
    let path = match[0];
    if (/^coid=/i.test(path)) path = `preview_course_nopop.php?catoid=${encodeURIComponent(catoid)}&${path}`;
    path = path.replace(/&amp;/g, '&').replace(/["']+$/,'');
    let candidate;
    try { candidate = new URL(path, seed.href); } catch { return null; }
    if (candidate.origin === seed.origin && !candidate.searchParams.has('catoid'))
      candidate.searchParams.set('catoid',catoid);
    const u = inScope(candidate.href, true);
    return u ? u.href : null;
  };
  // Catalog layouts vary: some Acalog templates put the course header in a link,
  // others put it in bold text, a table cell, or a separate expanded block.
  const courseTextLines = (doc) => {
    // A DOMParser document has no reliable innerText. Keep block boundaries
    // as newlines before asking the browser to strip the HTML tags.
    const html = (doc.body?.innerHTML || '')
      .replace(/<br\s*\/?>/gi, '\n')
      .replace(/<\/(?:p|div|li|tr|td|h[1-6]|strong|b|a|section|article)>/gi, '\n');
    const holder = doc.createElement('div');
    holder.innerHTML = html;
    return (holder.textContent || '').split(/\n+/).map(clean).filter(Boolean);
  };
  const courseBody = (fullText, headingText) => {
    const pos = fullText.toLowerCase().indexOf(headingText.toLowerCase());
    const body = pos >= 0 ? fullText.slice(pos + headingText.length) : fullText;
    return clean(body).slice(0, 5000);
  };
  const usableDescription = (value) => {
    const description = clean(value).replace(/^(?:Course Description|Description)\s*:\s*/i, '')
      .replace(/^\d+(?:\.\d+)?\s*(?:credit\s+hours?|credits?(?:\s+hours?)?)\s*/i, '')
      .replace(/\s+Prerequisites?\s*:\s*[^.]+$/i, '').trim();
    if (description.length < 24) return '';
    if (/^(?:select a prefix|search courses|course descriptions|add to favorites|print this page)/i.test(description)) return '';
    return description.slice(0, 5000);
  };
  const parseListing = (doc, sourceURL) => {
    const headingSelector = 'a, h2, h3, h4, h5, strong, b, .courseblocktitle, .course-title, .acalog-course-header, .course_header, .course-header';
    // Record all plausible headings, including non-clickable course headers.
    const headingElements = [...doc.querySelectorAll(headingSelector)];
    const counted = new Set();
    for (const el of headingElements) {
      const label = elementText(el);
      const heading = getCourseHeading(label);
      if (!heading) {
        if (/\b[A-Z]{2,6}\s*[- ]?\s*\d{2,4}[A-Z]?\b/i.test(label) && label.length < 200) remember(label);
        continue;
      }
      if (!counted.has(heading.code)) { diagnostics.headingCandidates++; counted.add(heading.code); }
      const a = el.closest('a') || (el.matches('a') ? el : null);
      const detailURL = a ? detailFromLink(a) : null;
      save({ ...heading, description:'', credits:'', prerequisites:'', source_url: detailURL || sourceURL });
      if (detailURL) details.set(detailURL, heading);
      // Search nearby wrappers instead of requiring a specific course CSS class.
      let wrapper = el;
      for (let depth = 0; wrapper && depth < 5; depth++, wrapper = wrapper.parentElement) {
        const raw = elementText(wrapper);
        if (raw.length < label.length + 24 || raw.length > 7500) continue;
        const otherCodes = new Set((raw.match(/\b[A-Z]{2,6}\s*[- ]?\s*\d{2,4}[A-Z]?\b/g) || [])
          .map(code => code.replace(/[\s-]/g, '').toUpperCase()));
        if (otherCodes.size > 1) continue;
        const descEl = wrapper.querySelector('.courseblockdesc, .course-description, .course-desc, .acalog-course-description, [itemprop="description"]');
        const desc = usableDescription(elementText(descEl) || courseBody(raw, label));
        if (desc) {
          save({ ...heading, description: desc, credits: parseCredits(raw),
            prerequisites: parsePrereqs(raw), source_url: detailURL || sourceURL });
          break;
        }
      }
    }
    // Expanded Acalog entries can use a wrapper with nested header + body.
    for (const block of doc.querySelectorAll('.courseblock, .acalog-course, .acalog-course-container, .course_block, .course-container, [id^="course_"], [class*="courseblock"]')) {
      const raw = elementText(block);
      if (raw.length < 30 || raw.length > 9000) continue;
      const titleEl = block.querySelector('.courseblocktitle, .acalog-course-header, .course-title, .course_header, h2, h3, h4, strong, a');
      const heading = getCourseHeading(elementText(titleEl));
      if (!heading) continue;
      const descEl = block.querySelector('.courseblockdesc, .course-description, .course-desc, .acalog-course-description, [itemprop="description"]');
      const desc = usableDescription(elementText(descEl) || courseBody(raw, elementText(titleEl)));
      if (!desc) continue;
      save({ ...heading, description:desc, credits:parseCredits(raw),
        prerequisites:parsePrereqs(raw), source_url:sourceURL });
    }
    // Last resort: extract expanded course prose from block-separated page text.
    // This also handles courses whose codes and titles use single spaces.
    const lines = courseTextLines(doc);
    for (let index = 0; index < lines.length; index++) {
      const heading = getCourseHeading(lines[index]);
      if (!heading) continue;
      const body = [];
      for (let j = index + 1; j < lines.length && j < index + 35; j++) {
        if (getCourseHeading(lines[j])) break;
        if (/^(?:Catalog Navigation|Course Descriptions|Course Search|Print this Page|Add to Favorites|Return to Top|Page \d+ of \d+)$/i.test(lines[j])) continue;
        if (lines[j].length < 3) continue;
        body.push(lines[j]);
        if (body.join(' ').length > 4500) break;
      }
      const full = body.join(' ');
      const desc = usableDescription(full);
      if (desc && (!courses.get(heading.code)?.description || desc.length > courses.get(heading.code).description.length)) {
        save({ ...heading, description:desc, credits:parseCredits(full), prerequisites:parsePrereqs(full), source_url:sourceURL });
        diagnostics.textFallbackMatches++;
      }
    }
    if (!courses.size && pages.size <= 1) {
      // User-visible diagnostics help distinguish an actual empty catalog
      // from a changed HTML template or missing expanded content.
      console.warn('Syllabus Auditor: no course records recognized on page', sourceURL,
        'Sample course-like labels:', diagnostics.samples);
    }
  };
  const parseDetail = (doc, sourceURL, knownHeading) => {
    const headingCandidates = [
      ...doc.querySelectorAll('.courseblocktitle, .course-title, h1, h2, h3, strong, b')
    ];
    let heading = null;
    for (const candidate of headingCandidates) {
      heading = getCourseHeading(candidate.textContent);
      if (heading) break;
    }
    if (!heading) {
      const title = clean(doc.title || '');
      heading = getCourseHeading(title);
    }
    if (!heading) heading=knownHeading;
    if (!heading) return;
    let description = '';
    for (const selector of ['.courseblockdesc', '.course-description', '.course-desc', '[itemprop="description"]']) {
      const match = doc.querySelector(selector);
      if (match && clean(match.textContent).length >= 24) {
        description = clean(match.textContent);
        break;
      }
    }
    if (!description) {
      const headingEl = headingCandidates.find(el => getCourseHeading(el.textContent)?.code === heading.code);
      let sibling = headingEl?.nextElementSibling;
      for (let i = 0; sibling && i < 6; i++, sibling=sibling.nextElementSibling) {
        const s = clean(sibling.textContent);
        if (s.length >= 36 && !/^\d+(?:\.\d+)?\s+credits?/i.test(s) && !getCourseHeading(s)) {
          description = s; break;
        }
      }
    }
    const metadata = clean(doc.body?.textContent || '');
    save({ ...heading, description: description.slice(0,5000), credits:parseCredits(metadata),
      prerequisites:parsePrereqs(metadata), source_url: sourceURL });
  };
  const load = async (href) => {
    await sleep(120);
    requested++;
    const response = await fetch(href, {credentials:'same-origin',redirect:'follow',headers:{Accept:'text/html'}});
    if (!response.ok) throw new Error(`HTTP ${response.status} ${new URL(href).pathname}`);
    if (!inScope(response.url, href.includes('preview_course'))) throw new Error('Redirected outside the selected catalog');
    const html = await response.text();
    if (/captcha|verify you are human|access denied|checking your browser/i.test(html.slice(0,3000))) {
      throw new Error('Catalog returned an access-check page');
    }
    return new DOMParser().parseFromString(html,'text/html');
  };
  const listingQueue = [seed.href];
  const pushListing = (href) => {
    const u=inScope(href);
    if (u && !pages.has(u.href) && !listingQueue.includes(u.href)) listingQueue.push(u.href);
  };
  const extractPrefixes = (doc) => {
    const selects = [...doc.querySelectorAll('select')];
    const select = selects.find(s => s.name === 'filter[27]' || /prefix/i.test(s.id || ''));
    if (!select) return [];
    return [...new Set([...select.options].map(o=>o.value.trim()).filter(v => /^[A-Za-z][A-Za-z0-9 &/-]{1,11}$/.test(v)))];
  };
  const listingURL = (prefix, pageNumber) => {
    const u = new URL(seed.href);
    if(!u.searchParams.has('catoid') && !u.searchParams.has('cur_cat_oid'))u.searchParams.set('cur_cat_oid',catoid);
    u.searchParams.set('filter[27]', prefix);
    u.searchParams.set('filter[29]','');
    u.searchParams.set('filter[course_type]','-1');
    u.searchParams.set('filter[keyword]','');
    u.searchParams.set('filter[32]','1');
    u.searchParams.set('filter[cpage]',String(pageNumber));
    u.searchParams.set('search_database','Filter');
    u.searchParams.set('filter[exact_match]','1');
    u.hash='';
    return u.href;
  };
  try {
    const prefixValues=selectedSubject ? [selectedSubject] : extractPrefixes(document);
    if (prefixValues.length) {
      for (const prefix of prefixValues) pushListing(listingURL(prefix,1));
      update(`Found ${prefixValues.length} prefixes`);
    } else {
      complete=false;
      errors.push('Could not find the catalog prefix selector. Captured linked pages only; completeness is unknown.');
    }
    // The already-open page is available even when Python HTTP retrieval is blocked.
    parseListing(document,seed.href);
    while (listingQueue.length && pages.size < maxPages) {
      const url=listingQueue.shift();
      if (pages.has(url)) continue;
      let doc;
      try {doc=(url===seed.href)?document:await load(url)}
      catch(e) {complete=false; errors.push(`${url}: ${e.message}`);continue}
      pages.set(url,true);
      parseListing(doc,url);
      // Acalog paginates each prefix with a filter[cpage] select or links.
      const current=new URL(url);
      if (current.searchParams.has('filter[27]') && (!current.searchParams.has('filter[cpage]') || current.searchParams.get('filter[cpage]')==='1')) {
        const numbers = [...doc.querySelectorAll('select[name="filter[cpage]"] option')]
          .map(x=>Number(x.value)).filter(n=>Number.isInteger(n)&&n>1&&n<=150);
        const pageText=clean(doc.body?.textContent||'').match(/Page\s+1\s+of\s+(\d{1,3})/i);
        if (pageText && !numbers.length) for (let n=2;n<=Math.min(Number(pageText[1]),150);n++) numbers.push(n);
        for (const num of new Set(numbers)) pushListing(listingURL(current.searchParams.get('filter[27]'),num));
      }
      for (const a of doc.querySelectorAll('a[href]')) {
        const u=inScope(a.href);
        if (u && (u.searchParams.has('filter[cpage]') || u.searchParams.has('filter[27]'))) pushListing(u.href);
      }
      if (pages.size % 5 === 0) update('Scanning course listings');
      if (courses.size>=maxDetails) {complete=false;errors.push('Reached 6,000 course limit');break}
    }
    if (listingQueue.length) { complete=false;errors.push(`Stopped after ${maxPages} catalog pages`); }
    update('Retrieving course descriptions');
    const detailURLs=[...details.entries()].filter(([,h])=>!(courses.get(h.code)?.description||'')).map(([url])=>url).slice(0,maxDetails);
    if (details.size>maxDetails) {complete=false;errors.push('Reached 6,000 course detail limit')}
    for (let i=0;i<detailURLs.length;i++) {
      const url=detailURLs[i];
      try {const doc=await load(url);parseListing(doc,url);parseDetail(doc,url,details.get(url))}
      catch(e) {complete=false;errors.push(`${url}: ${e.message}`)}
      if(i%12===0) update(`Checking descriptions ${i+1}/${detailURLs.length}`);
    }
  } catch(e) {
    complete=false;errors.push(e.stack||e.message);
  } finally {
    const items=[...courses.values()].sort((a,b)=>a.code.localeCompare(b.code));
    const haveDesc=items.filter(c=>c.description.length>=24).length;
    if(!items.length||haveDesc<items.length) complete=false;
    if (!items.length) errors.push(`No course headings recognized. ${diagnostics.headingCandidates} matching headers seen; candidate examples: ${diagnostics.samples.join(' | ') || 'none'}. Try expanding a course on the current page first.`);
    const output={format:'syllabus-auditor-browser-capture-v1',source_url:seed.href,subject_filter:selectedSubject||null,
       captured_at:new Date().toISOString(),pages_checked:pages.size,
       complete,errors:errors.slice(0,30),diagnostics,courses:items};
    const blob=new Blob([JSON.stringify(output,null,2)],{type:'application/json'});
    const link=document.createElement('a');link.href=URL.createObjectURL(blob);
    link.download=`OCC_Catalog_${catoid}${selectedSubject?'_'+selectedSubject.replace(/[^A-Z0-9]/g,'_'):''}_Browser_Capture.json`;
    document.body.appendChild(link);link.click();link.remove();
    setTimeout(()=>URL.revokeObjectURL(link.href),60000);
    update(`Downloaded ${items.length} courses (${haveDesc} with descriptions)`);
    console.info('Syllabus Auditor catalog capture:',{pages:pages.size,courses:items.length,descriptions:haveDesc,complete,diagnostics,errors:errors.slice(0,10)});
    setTimeout(()=>overlay.remove(),15000);
    window.__syllabusCatalogCaptureRunning=false;
  }
})();
