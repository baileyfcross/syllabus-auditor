# Course identity and title validation

Syllabus Auditor checks the catalog course prefix, number and title as **three
independent fields**. A valid identifier in the syllabus title line (for example,
`CSC-220 Foundations of Computer Science`) is split into `CSC`, `220`, and
`Foundations of Computer Science` for validation.

The title finding stores the text **without** the identifier or title-field
label. This permits an accepted title correction to preserve the course code in
a DOCX paragraph. Near matches remain subject to reviewer approval and exact
title checks respect the reference verification state.

When an identifier cannot be located in a title/header near the beginning, its
parts are marked for review instead of being silently assumed from a course
mention buried in the syllabus. A mismatch in either part fails that finding.

The **Review progress** area groups `Next unreviewed` and `Approve syllabus`.
The original unreviewed navigation cycles through actionable issues and avoids
already accepted or dismissed findings.

## Development CSS

`Start Syllabus Auditor Desktop.bat` invokes `tools/desktop_dev.py`, which
compiles Tailwind when the Tailwind sources are installed, then starts the
existing `packaging/windows/desktop_launcher.py`. Run with `--watch` to also
start `npm run watch:css` until the desktop window exits.

Installed desktop executables should not call Node.js at runtime. Run your
installer packaging script after changing styles so that the compiled CSS is
bundled in `app/static`.
