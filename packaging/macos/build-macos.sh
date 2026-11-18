#!/usr/bin/env bash
# Build macOS SyllabusAuditor.app plus a drag-to-Applications .dmg.
# Run on an actual Mac, once on Apple Silicon and again on Intel for both architectures.
set -Eeuo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="$(cd -- "$HERE/../.." && pwd)"
APP_VERSION="1.0.0"
PYTHON_BIN="python3"
SKIP_AI=0
SKIP_OCR=0
BUNDLE_CHROMIUM=0
SKIP_DMG=0
DRY_RUN=0
SIGN_IDENTITY=""

usage() {
  cat <<'EOF'
Usage: ./packaging/macos/build-macos.sh [options]

Options:
  --python PATH_OR_COMMAND   Python interpreter used to create the build venv
                             (3.12 recommended, e.g. python3.12)
  --version VERSION          Output version, default 1.0.0
  --skip-ai                  Omit Qwen3 and llama-cpp runtime (reduced-feature build)
  --skip-ocr                 Omit embedded Tesseract (reduced-feature build)
  --bundle-chromium          Bundle Playwright Chromium for catalog scans (larger)
  --no-dmg                   Produce the .app only
  --sign-identity NAME       Developer ID Application signing identity (optional)
  --dry-run                  Show build plan without installing or modifying anything
  -h, --help                 Show help

A full build bundles the 1.28 GB Qwen3 model and an OCR executable with English
language data. Never publish reduced builds as complete offline AI/OCR releases.
This builder requires macOS; PyInstaller cannot cross-build from Windows.
EOF
}

die() { echo "ERROR: $*" >&2; exit 1; }

while (($#)); do
  case "$1" in
    --python|--version|--sign-identity)
      (($# >= 2)) || die "Missing value for $1"
      case "$1" in
        --python) PYTHON_BIN="$2";;
        --version) APP_VERSION="$2";;
        --sign-identity) SIGN_IDENTITY="$2";;
      esac
      shift 2;;
    --skip-ai) SKIP_AI=1; shift;;
    --skip-ocr) SKIP_OCR=1; shift;;
    --bundle-chromium) BUNDLE_CHROMIUM=1; shift;;
    --no-dmg) SKIP_DMG=1; shift;;
    --dry-run) DRY_RUN=1; shift;;
    -h|--help) usage; exit 0;;
    *) die "Unrecognized option: $1";;
  esac
done

[[ "$APP_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.]+)?$ ]] || die "Invalid version: $APP_VERSION"

if [[ "$(uname -s)" == "Darwin" ]]; then
  ARCH="$(uname -m)"
else
  ARCH="host-architecture"
fi
if ((DRY_RUN)); then
  cat <<EOF
Syllabus Auditor macOS packaging plan
  Project: $PROJECT
  Python: $PYTHON_BIN
  Native architecture: $ARCH
  Version: $APP_VERSION
  Qwen3 bundled: $((1-SKIP_AI))
  Tesseract bundled: $((1-SKIP_OCR))
  Chromium bundled: $BUNDLE_CHROMIUM
  DMG requested: $((1-SKIP_DMG))
  Signing: ${SIGN_IDENTITY:-ad hoc / local testing only}
  Output: dist/macos/<arch>/SyllabusAuditor.app
          dist/releases/SyllabusAuditor-$APP_VERSION-macOS-<arch>.dmg
No files were changed.
EOF
  exit 0
fi
[[ "$(uname -s)" == "Darwin" ]] || die "macOS build requires a Mac (Darwin), not Windows/Linux"
cd "$PROJECT"
[[ "$ARCH" == "arm64" || "$ARCH" == "x86_64" ]] || die "Unsupported Mac architecture: $ARCH"
# Build Tailwind for the shared HTML/JS frontend before it is frozen into .app.
# npm/Node are build-time tools and are NOT distributed to app users.
build_frontend_css() {
  local css_source="$PROJECT/styles/tailwind.css"
  local manifest="$PROJECT/package.json"
  if [[ ! -f "$css_source" && ! -f "$manifest" ]]; then
    echo 'Tailwind source not installed; using existing plain CSS.'
    return
  fi
  [[ -f "$css_source" && -f "$manifest" ]] || die 'Tailwind setup is incomplete: apply the design-system patch (package.json + styles/tailwind.css) first.'
  command -v npm >/dev/null 2>&1 || die 'Node.js/npm is required on the BUILD Mac. Install Node.js LTS; app users do not need it.'
  echo 'Installing Tailwind build dependencies...'
  if [[ -f "$PROJECT/package-lock.json" ]]; then
    npm ci --no-audit --no-fund
  else
    npm install --no-audit --no-fund
  fi
  echo 'Compiling Tailwind CSS (npm run build)...'
  npm run build
  [[ -s "$PROJECT/app/static/tailwind.generated.css" ]] || die 'Tailwind CSS output is missing or empty.'
  [[ $(wc -c < "$PROJECT/app/static/tailwind.generated.css") -ge 100 ]] || die 'Tailwind generated CSS is unexpectedly small.'
  echo 'Tailwind CSS compiled successfully.'
}
build_frontend_css

for item in xcode-select hdiutil ditto codesign otool; do
  command -v "$item" >/dev/null || die "$item is missing; install Xcode Command Line Tools: xcode-select --install"
done
xcode-select -p >/dev/null 2>&1 || die "Install Xcode Command Line Tools: xcode-select --install"
command -v "$PYTHON_BIN" >/dev/null || die "Python not found: $PYTHON_BIN. Install with brew install python@3.12"

read -r PY_VER PY_ARCH < <("$PYTHON_BIN" -c 'import sys,platform;print(f"{sys.version_info.major}.{sys.version_info.minor} {platform.machine()}")')
[[ "$PY_VER" =~ ^3\.(11|12|13|14)$ ]] || die "Unsupported Python version $PY_VER; Python 3.12 recommended"
[[ "$PY_ARCH" == "$ARCH" ]] || die "Python architecture $PY_ARCH differs from native Mac $ARCH; use a matching interpreter"

BUILD_DIR="$PROJECT/build/macos/$ARCH"
VENV="$BUILD_DIR/.venv"
PY="$VENV/bin/python"
DIST="$PROJECT/dist/macos/$ARCH"
RELEASES="$PROJECT/dist/releases"
MODEL="$PROJECT/models/Qwen3-1.7B-Q4_K_M.gguf"
mkdir -p "$BUILD_DIR" "$RELEASES"
if [[ ! -x "$PY" ]]; then
  "$PYTHON_BIN" -m venv "$VENV"
fi
"$PY" -m pip install --upgrade pip
"$PY" -m pip install -r "$PROJECT/requirements.txt" \
  'pyinstaller>=6.18,<7' 'pywebview>=6,<8' \
  pyobjc-core pyobjc-framework-Cocoa pyobjc-framework-Quartz \
  pyobjc-framework-WebKit pyobjc-framework-Security

PYI=("$PY" -m PyInstaller --noconfirm --clean --onedir --windowed
  --name SyllabusAuditor
  --distpath "$DIST"
  --workpath "$BUILD_DIR/pyinstaller"
  --specpath "$BUILD_DIR/pyinstaller"
  --paths "$PROJECT"
  --target-arch "$ARCH"
  --osx-bundle-identifier info.baileyfcross.syllabusauditor
  --collect-all webview
  --collect-all playwright
  --collect-data docx  # Required XML templates, including default-header.xml
  --collect-submodules app
  --hidden-import app
  --hidden-import app.main
  --hidden-import objc
  --hidden-import Cocoa
  --hidden-import WebKit
  --hidden-import Quartz
  --add-data "$PROJECT/app/static:app/static")

if ((SKIP_AI == 0)); then
  [[ -f "$MODEL" ]] || "$PY" "$PROJECT/tools/prepare_model.py"
  "$PY" -c 'import sys;from tools.prepare_model import verify,DEST;sys.exit(0 if verify(DEST) else 1)' \
    || die "Model SHA-256 verification failed: $MODEL"
  # On Apple Silicon, building llama.cpp with Metal is supported; the current
  # Syllabus Auditor application selects CPU by default (n_gpu_layers=0).
  if [[ "$ARCH" == "arm64" ]]; then
    export CMAKE_ARGS="${CMAKE_ARGS:--DGGML_METAL=on}"
  fi
  "$PY" -m pip install 'llama-cpp-python>=0.3.5,<1' \
    || die "Could not build llama-cpp-python. Install cmake: brew install cmake; then retry"
  "$PY" -c 'from llama_cpp import Llama' \
    || die "llama-cpp-python does not import successfully in the build environment"
  PYI+=(--collect-all llama_cpp --add-data "$MODEL:models")
else
  echo "WARNING: Packaging without local AI or model. This is a reduced-feature build."
fi

if ((SKIP_OCR == 0)); then
  command -v tesseract >/dev/null || die "Tesseract is missing. Run: brew install tesseract"
  TESS_BIN="$(command -v tesseract)"
  if command -v brew >/dev/null; then
    TESS_PREFIX="$(brew --prefix tesseract 2>/dev/null || true)"
  else
    TESS_PREFIX=""
  fi
  TESSDATA=""
  for dir in "${TESS_PREFIX:+$TESS_PREFIX/share/tessdata}" \
             /opt/homebrew/share/tessdata /usr/local/share/tessdata; do
    [[ -n "$dir" && -f "$dir/eng.traineddata" ]] && { TESSDATA="$dir"; break; }
  done
  [[ -n "$TESSDATA" ]] || die "English OCR data missing; verify brew install tesseract and eng.traineddata"
  TESS_TMP="$BUILD_DIR/tessdata"
  mkdir -p "$TESS_TMP"
  cp "$TESSDATA/eng.traineddata" "$TESS_TMP/"
  [[ ! -f "$TESSDATA/osd.traineddata" ]] || cp "$TESSDATA/osd.traineddata" "$TESS_TMP/"
  PYI+=(--add-binary "$TESS_BIN:tesseract" --add-data "$TESS_TMP:tesseract/tessdata")
else
  echo "WARNING: Packaging without bundled OCR. Scanned PDFs may not be readable."
fi

if ((BUNDLE_CHROMIUM)); then
  # Chromium bundled when building, never downloaded by the installed app.
  BROWSERS="$BUILD_DIR/ms-playwright"
  PLAYWRIGHT_BROWSERS_PATH="$BROWSERS" "$PY" -m playwright install chromium
  [[ -d "$BROWSERS" ]] || die "Playwright browser installation did not create $BROWSERS"
  PYI+=(--add-data "$BROWSERS:ms-playwright")
else
  echo 'MyOCC catalog automation will use an installed Chrome/Edge if available.'
fi

ICON="$BUILD_DIR/syllabus-auditor.icns"
if [[ -f "$PROJECT/packaging/windows/syllabus-auditor.ico" ]]; then
  "$PY" "$HERE/create_icon.py" "$PROJECT/packaging/windows/syllabus-auditor.ico" "$ICON"
  PYI+=(--icon "$ICON")
fi
if [[ -n "$SIGN_IDENTITY" ]]; then
  PYI+=(--codesign-identity "$SIGN_IDENTITY")
fi
PYI+=("$HERE/desktop_launcher.py")
"${PYI[@]}"

APP="$DIST/SyllabusAuditor.app"
[[ -d "$APP" ]] || die "PyInstaller did not produce $APP"
[[ -x "$APP/Contents/MacOS/SyllabusAuditor" ]] || die "App launcher is missing"
[[ -f "$APP/Contents/Info.plist" ]] || die "App Info.plist is missing"

# python-docx creates header/footer parts when needed, using bundled XML files.
# On macOS PyInstaller stores package data under Contents/Resources and links
# them into Contents/Frameworks. Verify the path python-docx reads at runtime.
for resource in default-header.xml default-footer.xml default-settings.xml default-styles.xml; do
  [[ -f "$APP/Contents/Frameworks/docx/templates/$resource" ]] || \
    die "Missing bundled python-docx resource: $resource. Check --collect-data docx."
done
echo 'Verified bundled python-docx XML resources.'

if ((SKIP_AI == 0)); then
  find "$APP/Contents" -name 'Qwen3-1.7B-Q4_K_M.gguf' -type f -print -quit | grep -q . \
    || die "Qwen3 model not found inside .app"
fi
if ((SKIP_OCR == 0)); then
  OCR_BIN="$(find "$APP/Contents" -type f -name tesseract -print -quit)"
  [[ -n "$OCR_BIN" ]] || die "Tesseract executable missing from .app"
  find "$APP/Contents" -name eng.traineddata -type f -print -quit | grep -q . \
    || die "English OCR language data missing from .app"
  # If linked against host Homebrew paths, the bundle is NOT independent.
  if otool -L "$OCR_BIN" | grep -Eq '/(opt/homebrew|usr/local/(Cellar|opt))(/|$)'; then
    die "Bundled Tesseract still references Homebrew libraries outside .app. Do not distribute this build."
  fi
fi
codesign --verify --deep --strict "$APP" \
  || die "App code-signature validation failed; check PyInstaller signing output"

if ((SKIP_DMG)); then
  echo "Built macOS app: $APP"
  exit 0
fi

STAGING="$BUILD_DIR/dmg-staging"
rm -rf "$STAGING"
mkdir -p "$STAGING"
ditto "$APP" "$STAGING/SyllabusAuditor.app"
ln -s /Applications "$STAGING/Applications"
DMG="$RELEASES/SyllabusAuditor-$APP_VERSION-macOS-$ARCH.dmg"
rm -f "$DMG"
hdiutil create -quiet -volname "Syllabus Auditor $APP_VERSION" \
  -srcfolder "$STAGING" -format UDZO -ov "$DMG"
[[ -s "$DMG" ]] || die "DMG creation failed"
echo
printf 'macOS APP: %s\n' "$APP"
printf 'macOS DMG: %s\n' "$DMG"
echo 'Important: Validate on a clean Mac before publishing. Public distribution requires Developer ID signing and Apple notarization.'
