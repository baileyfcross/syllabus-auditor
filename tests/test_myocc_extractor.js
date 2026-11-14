const fs = require('fs'), path = require('path');
const py = fs.readFileSync(path.join(__dirname,'../app/myocc_bulk.py'),'utf8');
const content = py.split("EXTRACT_PAGE_JS = r'''")[1].split("'''\n\nDISCOVER_SUBJECTS_JS")[0];
const vm=require('vm');
const ctx={document:{body:{innerText:`Filter Results\nCIS-100 Information and Computer Literacy (3 Credits)\nThis course provides an overview of digital technologies, ethical issues, and information literacy for students.\nRequisites:\nNone\nCIS 130 - Web Development (3 Credits)\nCourse Description\nStudents learn accessible HTML, CSS, and JavaScript for developing responsive websites.\nLocations:\nCIS-145\nSoftware Engineering\nCourse Description\nThe course discusses software design, testing, and development lifecycle concepts.\n`},querySelectorAll:()=>[]}, location:{href:'https://colss-prod.ec.sunyocc.edu/Student/Courses/Search?subjects=CIS'}};
const fn=vm.runInNewContext('('+content+')',ctx);
const out=fn('CIS');
console.log(JSON.stringify(out.courses,null,2));
if(out.courses.length!==3 || !out.courses.find(r=>r.code==='CIS-100')?.description || !out.courses.find(r=>r.code==='CIS-145')?.description || out.courses.find(r=>r.code==='CIS-130')?.description.includes('Locations:'))process.exit(1);
