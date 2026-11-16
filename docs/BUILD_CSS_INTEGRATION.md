# Syllabus Auditor: Automatic Tailwind compilation

Apply this patch into the **repository root** after installing the Tailwind Design System / MIT License patch. The `package.json` included here adds `npm run build` as an alias for `npm run build:css`.

## Windows desktop installer

Run `".\Build Windows Installer.bat"` in your VS Code Command Prompt. It calls the existing `packaging/windows/build-windows.ps1`, which now installs npm development dependencies, executes `npm run build`, and verifies `app/static/tailwind.generated.css` **before** running PyInstaller and Inno Setup. On the Windows build computer, install Node.js LTS. The installed application doesn't need Node.js.

## macOS desktop build

Run `./packaging/macos/build-macos.sh --python python3.12` on macOS. It now installs npm development dependencies, compiles the CSS, verifies output, and then runs the existing PyInstaller/DMG builder. You need the macOS Desktop Build Kit from the earlier patch (desktop launcher, icon creator, and preview script) if it has not yet been installed. A `--dry-run` does not run npm or create output.

## Docker deployment

`docker compose build` uses a separate Node builder stage to compile Tailwind CSS and copies the compiled file into the Python runtime image. Node.js is not present in the final running container.

## Build behavior

- Tailwind source and `package.json` both present: compile every build, stop on errors.
- Neither present (legacy source checkout): skip and keep using the original `app.css`.
- One present but the other missing: stop with an actionable message (Windows and macOS).
- If `package-lock.json` exists, builds use `npm ci`; otherwise, they use `npm install`.
- Commit `package-lock.json` for reproducible future builds. Ignore `node_modules/`, but keep `app/static/tailwind.generated.css` in the source repository if you want source-mode preview without a build step.
- The Dockerfile **requires** the complete Tailwind design-system files. Do not apply the Dockerfile alone to a legacy checkout.

## Verification

To verify locally before packaging: `npm run build` followed by `npm run build:css` (both produce the same CSS). Check the app in light and dark modes. Build your Windows/macOS installer and confirm it includes `tailwind.generated.css`.

## Scope

This patch updates the packaging scripts, `package.json`, Dockerfile, and documentation only. It doesn't alter your backend, AI model, syllabus database, existing CSS, or login flow. It doesn't contain the Qwen3 model or runtime binaries.
