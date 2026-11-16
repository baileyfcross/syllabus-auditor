# Design system patch installation

Syllabus Auditor - Tailwind + centralized design system + MIT License

INSTALL:
  1. Back up your project and stop Syllabus Auditor.
  2. Extract the ZIP into the ROOT of syllabus-auditor, merging folders.
  3. Allow replacement of app/static/index.html and app/static/app.js.
     The existing app/static/app.css and app/static/theme.js are NOT replaced.
  4. In the project root, run:
         npm install
         npm run build:css
     (Node 20+ required on developer/build machine only.)
  5. Start the app normally and check Light, Dark and System themes.
  6. Commit the compiled app/static/tailwind.generated.css and npm-generated
     package-lock.json for reproducible desktop and Docker distributions.

WHAT WAS ADDED:
  LICENSE                              MIT copyright (c) 2026 Bailey Cross
  package.json                         Tailwind CSS v4 development-only CLI
  styles/tailwind.css                  Tailwind source (prefixed, no Preflight)
  app/static/design-system.css        Shared tokens and standardized components
  app/static/tailwind.generated.css    Initial placeholder, replaced by npm build
  docs/DESIGN_SYSTEM.md                Token reference, components and workflow
  tests/test_design_system_assets.py   Static regression tests
  .gitignore / .dockerignore           Exclude node_modules and build artifacts

WHAT WAS UPDATED:
  app/static/index.html               Loads compiled Tailwind + design system
  app/static/app.js                   Shared button/form/modal helpers use classes

NOTE: The provided ZIP does not include downloaded Node dependencies or a
compiled Tailwind bundle. npm build:css is needed before release. The semantic
component CSS works without that step. No backend/data/model files are touched.

LICENSE: MIT applies to your original code and documentation. Dependency/model
licenses are separate. Review prior third-party contributions if applicable.
