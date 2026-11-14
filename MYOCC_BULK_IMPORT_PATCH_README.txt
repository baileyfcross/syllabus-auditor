SYLLABUS AUDITOR - MYOCC BULK IMPORT INTEGRATION
================================================

This patch extends the EXISTING Course Catalog > Bulk Import Catalog workflow.
It does not replace the separate Browser Capture Import option, and it does not
use Ollama or a paid AI API. The browser-driven scan uses a local headless
Chromium-compatible browser to load MyOCC public course search results.

INSTALL ON WINDOWS (VS CODE / COMMAND PROMPT)
---------------------------------------------
1. Stop the running app with Ctrl+C.
2. Make a copy of your syllabus-auditor/data directory (backup).
3. Extract the ZIP contents directly into syllabus-auditor, preserving paths
   and replacing the indicated files. Do not replace your data, models or .venv.
4. Open the project folder in VS Code and run:

       ".\Start Syllabus Auditor.bat"

   The launcher installs the additional Playwright Python dependency listed
   in requirements.txt. It prefers an already-installed Microsoft Edge on
   Windows. You can install a separate browser when necessary:

       python -m playwright install chromium

5. In your browser refresh Syllabus Auditor with Ctrl+F5.

CONFIGURE SOURCES
-----------------
1. Settings > Institution > Edit institution.
2. Keep the academic catalog URL (e.g., catalog.sunyocc.edu) as the primary
   source for official syllabus-compliance verification.
3. Add this domain to Other approved official domains:

       colss-prod.ec.sunyocc.edu

IMPORT FROM MYOCC
-----------------
1. Course Catalog > Bulk Import Catalog.
2. Catalog source: MyOCC Self-Service (browser-driven).
3. Course catalog URL:

       https://colss-prod.ec.sunyocc.edu/Student/Courses

4. Enter an academic year (for example 2026-2027). Note: MyOCC may show
   current offerings rather than a historical year's official catalog.
5. Subject codes: CIS (one), CIS,CSC,MATH (multiple) or blank to attempt
   discovery of all available subjects from the public MyOCC interface.
6. Set a page limit and click Scan courses.
7. Review results, errors, and any incomplete/partial indicators.
8. Click Import new courses to preserve existing records or Import and
   update existing to version existing records and invalidate prior verification.

THE IMPORTANT LIMITATIONS
-------------------------
- MyOCC is a dynamically rendered search interface. Some results, page
  controls, hidden descriptions, and subject lists may not be accessible
  to automated browser navigation. If the site prevents discovery, the scan
  fails explicitly or reports partial coverage. It does not claim every
  course was found.
- MyOCC may not supply an academic-year-specific authoritative course catalog.
  Newly imported descriptions remain unverified until independently checked.
- The integration requires a supported browser for the local mode and a
  Playwright-installed Chromium during container build. Dockerfile installs
  the browser in the image during build (no runtime download required).
- No separate login, school credentials, third-party AI services, or bypass
  of access restrictions is implemented. Only public course results are read.

TEST COVERAGE
-------------
- 24 automated Python tests passed, including multi-subject MyOCC scanning,
  staging, source status, schema migration code paths, and safe subject input.
- Node JavaScript extractor test passed using sample rendered MyOCC course data.
- JavaScript syntax and Python compilation passed.
- LIVE MyOCC end-to-end result extraction and pagination remain UNVERIFIED.

Patch files: app/catalog_bulk.py, app/myocc_bulk.py, app/main.py,
app/database.py, app/static/app.js, requirements.txt, Dockerfile,
docker-compose.yml, tests/test_system.py, tests/test_myocc_extractor.js,
README.md, and this instruction file.
