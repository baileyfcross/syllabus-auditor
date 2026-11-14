# Syllabus Auditor - Native-window Windows desktop edition

This patch changes the **installed** Windows application to open its own native Windows application window instead of opening a tab in Edge/Chrome. It uses the system's Microsoft Edge WebView2 runtime (not Electron or a bundled browser window) and runs the existing FastAPI validation engine in a private background thread **within the same program process**. All document/audit, MyOCC, Qwen3, template, approval, and report code remains unchanged. Docker/web hosting continues to work separately.

## Apply to your existing VS Code project

1. Stop the current app. Back up the whole project or at least the `data` folder.
2. Copy this patch's contents into your `syllabus-auditor` root, allowing matching **packaging** files to be replaced. This patch does not contain the existing database, original `app` files, or the model weights.
3. Make sure Edge WebView2 Runtime is installed on the target Windows machine (typically present on Windows 11). For this desktop build, native Windows 64-bit is expected.
4. **Preview the native window using your existing project data:** double-click `Start Syllabus Auditor Desktop.bat`, or run `".\Start Syllabus Auditor Desktop.bat"` from VS Code Command Prompt. The first run may install the `pywebview` Python dependency in `.venv`. This launches a native window, but the terminal is visible during development.
5. **Compile the production application:** run `".\Build Windows Installer.bat"` with Python 3.14. It uses an isolated `.build-venv`, installs pywebview and dependencies, and packages a `--windowed` (no console) `SyllabusAuditor.exe` and the Inno Setup installer.
6. Find the executable under `dist\SyllabusAuditor\SyllabusAuditor.exe`, and the installer under `dist\installer\SyllabusAuditor_Setup_1.0.0.exe`.

**Important:** `Build Windows Installer.bat` still needs the Tesseract installation on your build computer to include scanned PDF OCR; the previous error you reported is unrelated to opening in a browser. To build without OCR while diagnosing the window, run `".\Build Windows Installer.bat" -SkipOCR` (reduced-feature build). A full installer requires Tesseract and its `tessdata\eng.traineddata`.

### Size and service simplifications

- Desktop window: reuses the OS WebView2 runtime; no Electron and no standalone browser for normal UI.
- Normal build: uses installed Microsoft Edge (or Chrome) for the **MyOCC automation feature** instead of bundling another Chromium browser. You can opt into fully bundling Chromium using `".\Build Windows Installer.bat" -BundleChromium` (larger installer).
- Qwen3 remains bundled for the AI features unless you explicitly build with `-SkipAI`; the GGUF file is the largest item.
- The Windows installer stores database, uploaded syllabi, templates, reports, and settings in `%LOCALAPPDATA%\SyllabusAuditor\data`, unaffected by subsequent installer updates. The developer preview batch script deliberately uses your existing project `data` directory for testing.
- No Ollama or paid model API connections are added.

### First launch

The native shell reads the one-time setup token from its own local data directory and pre-fills the setup-token field. Existing users sign in normally. If setup prefill does not occur, open `%LOCALAPPDATA%\SyllabusAuditor\data\bootstrap-token.txt` and paste the token manually.

### Other details

- Closing the main desktop window stops its local server. The server binds only to `127.0.0.1` on a free temporary port and cannot be reached from other computers.
- Official catalog website links that explicitly request a new tab may open your ordinary browser. This is intentional; the *Syllabus Auditor desktop UI* stays inside its application window.
- Report downloads use the webview's native Save dialog. In the desktop shell `ALLOW_DOWNLOADS` is enabled.
- A second desktop instance is prevented on Windows to avoid multiple background source monitors touching the same database.
- Exceptions while starting the installed window are shown in a Windows message box and logged to `%LOCALAPPDATA%\SyllabusAuditor\logs\desktop.log`.
- This is a native **window**, not a PySide6 native-widgets rewrite. The existing HTML/CSS/JS UI remains the same, which is why the desktop package can stay small and the website can use the same code.

### Windows release validation still needed

The source tests can run on Linux, but a real WebView2 window and Inno Setup executable must be built and tested **on Windows**. Before distribution, verify login, file uploads, PDF/DOCX exports, MyOCC scans, OCR and local model availability in the installed EXE. PyInstaller packages target the OS on which they are built.
