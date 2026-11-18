# macOS build fix: missing create_icon.py

The macOS packager references `packaging/macos/create_icon.py` to convert the
existing Windows icon (`packaging/windows/syllabus-auditor.ico`) into the native
`*.icns` format expected by PyInstaller. The earlier macOS package omitted the
helper, causing `can't open file ... packaging/macos/create_icon.py` after the
AI model and Python packages were installed.

This small patch supplies that helper. It uses the Pillow dependency already
installed by the macOS packaging script and Apple's `iconutil` from the Xcode
Command Line Tools. It builds standard 1x/2x PNG icon sizes in a temporary
iconset, then writes the .icns file in the location requested by the packager.

## Install

Copy `packaging/macos/create_icon.py` into your existing Syllabus Auditor
repository at the same path. Your existing `build-macos.sh` does not need to be
replaced. This patch does not modify your model, database or build flags.

## Build v1.1.0

```bash
./packaging/macos/build-macos.sh --python python3.12 --version 1.1.0
```

Because the build environment and model are already present, they should be
reused, although the script still checks dependencies and may rebuild AI wheels.

Expected outputs on Apple Silicon:

- `dist/macos/arm64/SyllabusAuditor.app`
- `dist/releases/SyllabusAuditor-1.1.0-macOS-arm64.dmg`

This addresses only the missing icon helper seen in your log. The rest of the
native macOS build, including bundled OCR library checks, code signing, and the
final .dmg step, still needs to complete on your Mac.
