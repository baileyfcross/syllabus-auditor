# Build a Windows `.exe` and installer for Syllabus Auditor

This kit is meant to be **copied into your current syllabus-auditor folder**. Run the build on **Windows x64**; PyInstaller does not cross-compile from Linux or macOS into Windows executables.

## Build prerequisites

- Python 3.14 or 3.12 installed on the **build computer**. The resulting installer includes the Python runtime and your users do not need Python.
- Internet access on the **build computer** for downloading Python build packages, the optional model, and Chromium. The installed app does not call paid AI services or Ollama.
- [Inno Setup](https://jrsoftware.org/isdl.php) 6 or 7 for the final installer. Use the official signed installer.
- Tesseract OCR already installed locally (usually `C:\Program Files\Tesseract-OCR`) with English trained data so it can be bundled.
- For the complete embedded AI product: `llama-cpp-python` **must** install correctly in the isolated build environment. If no prebuilt package is available for Python 3.14, run the builder with `-PythonVersion 3.12`, which can coexist with 3.14.

## Run from your VS Code PowerShell terminal

Open the **syllabus-auditor root folder** in VS Code. In PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\windows\build-windows.ps1 -PythonVersion 3.14
```

If you are using **Command Prompt** (prompt ends in `>` rather than `PS>`), the same line still works; it launches PowerShell for the build.

If `llama-cpp-python` cannot find a binary wheel for Python 3.14, install Python 3.12 alongside Python 3.14, **delete only** `.build-venv`, then run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\windows\build-windows.ps1 -PythonVersion 3.12
```

The builder creates an isolated `.build-venv` and does not change `.venv` or your existing `data` folder. Build-time model retrieval uses the project's pinned `tools/prepare_model.py` download and SHA-256 validation.

**Alternative partial build (no embedded AI):** add `-SkipAI`. To omit bundled OCR, add `-SkipOCR`. To require installed Edge/Chrome instead of bundled Chromium, add `-SkipBrowser`. These flags produce **reduced-feature** bundles and should not be labeled as full all-in-one releases.

## Output files

- `dist\SyllabusAuditor\SyllabusAuditor.exe` + its `_internal` folder: portable one-folder application. **Distribute the whole folder**, not the EXE alone.
- `dist\installer\SyllabusAuditor_Setup_1.0.0.exe`: self-contained Windows installer; double click to install and add Start Menu shortcuts.

The installer installs per-user in `%LOCALAPPDATA%\Programs\Syllabus Auditor`; the application stores documents and SQLite data separately in `%LOCALAPPDATA%\SyllabusAuditor\data`. Uninstalling or upgrading should not delete the user data. On first launch, an administrator setup token is printed in the application's console window. Keep the console open while using the web UI at `http://127.0.0.1:8765`.

**Existing data migration:** your development copy uses `syllabus-auditor\data`; the newly installed application starts with a different data folder. If you want to preserve your current institutions, templates, reports and documents, **close both application instances**, back up both folders, then copy the contents of your existing `data` folder into `%LOCALAPPDATA%\SyllabusAuditor\data` before the first installed launch. Do not overwrite a populated destination without reviewing it first.

## Verification before distribution

1. Run the EXE *outside your source checkout* and open its browser page; verify setup/login and check the `/health` response.
2. Verify the AI status is **Ready** (for the full AI build), and run a sample syllabus audit.
3. Verify OCR with a scanned PDF and MyOCC bulk import with bundled Chromium.
4. Close the server using Ctrl+C, then run the installer and repeat the smoke test as an installed user.
5. Confirm that restarting/upgrading preserves saved files under `%LOCALAPPDATA%\SyllabusAuditor\data`.
6. Code-sign the installer/executable for redistribution when possible. Unsigned installers may trigger Windows SmartScreen warnings.

The scripts cannot be fully tested on Linux. Installer and Windows native build must be executed and tested on a Windows computer before distribution.
