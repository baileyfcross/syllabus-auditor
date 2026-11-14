# Build a distributable Syllabus Auditor.exe and optional Inno Setup installer.
# Run from any folder on a Windows x64 machine, not from Linux/macOS.
param(
  [ValidateSet('3.14','3.13','3.12')][string]$PythonVersion = '3.14',
  [switch]$SkipInstaller,
  [switch]$SkipAI,
  [switch]$SkipOCR,
  [switch]$SkipBrowser, # backward-compatible switch
  [switch]$BundleChromium, # optional; use installed Edge by default
  [string]$TesseractDir = ''
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$project = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location -LiteralPath $project
$buildVenv = Join-Path $project '.build-venv'
$python = Join-Path $buildVenv 'Scripts\python.exe'
function Run-Native([string]$Exe, [string[]]$Arguments) {
  # Windows PowerShell 5.1 can treat native stderr as a terminating error.
  # Judge process success by its exit code instead.
  $priorPreference = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try {
    & $Exe @Arguments
    $code = $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $priorPreference
  }
  if ($code -ne 0) { throw "Command failed ($code): $Exe $($Arguments -join ' ')" }
}
function Ensure-File([string]$Path, [string]$Message) {
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw $Message }
}
Write-Host 'Syllabus Auditor Windows packager' -ForegroundColor Cyan
if (-not (Test-Path -LiteralPath $python)) {
  Write-Host "Creating isolated build environment with Python $PythonVersion..."
  Run-Native 'py' @("-$PythonVersion",'-m','venv',$buildVenv)
}
$actualVersion = (& $python -c 'import sys;print(sys.version_info.major, sys.version_info.minor, sep=chr(46))').Trim()
if ($actualVersion -ne $PythonVersion) { throw "Build environment uses Python $actualVersion, but $PythonVersion was requested. Remove only .build-venv and retry." }
Run-Native $python @('-m','pip','install','--upgrade','pip')
Run-Native $python @('-m','pip','install','-r','requirements.txt','pyinstaller>=6.18,<7','pywebview>=6,<8')

$extraArgs = @()
if (-not $SkipAI) {
  $model = Join-Path $project 'models\Qwen3-1.7B-Q4_K_M.gguf'
  if (-not (Test-Path -LiteralPath $model)) {
    Write-Host 'Retrieving the model for this build (one-time build dependency)...'
    Run-Native $python @('tools\prepare_model.py')
  }
  Run-Native $python @('-c','from tools.prepare_model import verify, DEST; import sys; sys.exit(0 if verify(DEST) else 2)')
  Write-Host 'Installing embedded CPU inference runtime; may need a prebuilt wheel.'
  # Prefer wheels instead of attempting an expensive native CMake build.
  Run-Native $python @('-m','pip','install','--only-binary=:all:','--extra-index-url','https://abetlen.github.io/llama-cpp-python/whl/cpu','llama-cpp-python>=0.3.5,<1')
  Run-Native $python @('-c','import llama_cpp')
  $extraArgs += @('--collect-all','llama_cpp','--add-data',"${model};models")
} else {
  Write-Warning 'Building without embedded AI. This is NOT the complete self-contained AI product.'
}

if (-not $SkipOCR) {
  if (-not $TesseractDir) {
    $candidate = Join-Path $env:ProgramFiles 'Tesseract-OCR'
    if (Test-Path -LiteralPath (Join-Path $candidate 'tesseract.exe')) { $TesseractDir = $candidate }
  }
  if (-not $TesseractDir) { throw 'Tesseract not found. Install it on the BUILD machine and use -TesseractDir "C:\Program Files\Tesseract-OCR"; or explicitly specify -SkipOCR for a reduced-feature build.' }
  Ensure-File (Join-Path $TesseractDir 'tesseract.exe') 'Missing Tesseract executable.'
  Ensure-File (Join-Path $TesseractDir 'tessdata\eng.traineddata') 'Missing English OCR model in Tesseract tessdata.'
  $extraArgs += @('--add-data',"${TesseractDir};tesseract")
} else {
  Write-Warning 'Building without bundled Tesseract OCR; scanned PDF recognition may be unavailable.'
}

if ($BundleChromium -and -not $SkipBrowser) {
  # Optional fully bundled browser engine, for systems without installed Edge.
  $browserCache = Join-Path $project 'packaging\windows\.playwright-browsers'
  $env:PLAYWRIGHT_BROWSERS_PATH = $browserCache
  Write-Host 'Bundling Chromium for catalog automation (larger installer)...'
  Run-Native $python @('-m','playwright','install','chromium')
  $extraArgs += @('--add-data',"${browserCache};ms-playwright")
} else {
  Write-Host 'Using recipient Windows Edge/Chrome for MyOCC scans; no extra Chromium bundled.'
}

$launcher = Join-Path $project 'packaging\windows\desktop_launcher.py'
$icon = Join-Path $project 'packaging\windows\syllabus-auditor.ico'
Ensure-File $launcher 'Missing desktop launcher.'
Ensure-File $icon 'Missing program icon.'
$pyinstallerArgs = @(
    '-m','PyInstaller','--noconfirm','--clean','--onedir','--windowed',
    '--name','SyllabusAuditor','--distpath','dist','--workpath','build\pyinstaller',
    '--specpath','build\pyinstaller',
    '--icon',$icon,
    '--paths',$project,
    '--collect-all','playwright',
    '--collect-all','webview',
    '--collect-submodules','app',
    '--hidden-import','app',
    '--hidden-import','app.main',
    '--add-data',"$(Join-Path $project 'app\static');app/static"
) + $extraArgs + @($launcher)
Run-Native $python $pyinstallerArgs
$exe = Join-Path $project 'dist\SyllabusAuditor\SyllabusAuditor.exe'
Ensure-File $exe 'EXE did not appear in dist\SyllabusAuditor.'
Write-Host "Executable built: $exe" -ForegroundColor Green
Write-Host 'Smoke test on Windows: launch the native desktop window, verify PDF/report downloads, OCR, MyOCC, AI, and window-close cleanup.'
if (-not $SkipInstaller) {
  $programFilesX86 = [Environment]::GetEnvironmentVariable('ProgramFiles(x86)')
  $isccCandidates = @(
    (Join-Path $programFilesX86 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe'),
    (Join-Path $programFilesX86 'Inno Setup 7\ISCC.exe'),
    (Join-Path $env:ProgramFiles 'Inno Setup 7\ISCC.exe'),
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 7\ISCC.exe"
  )
  $compiler = $isccCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
  if (-not $compiler) { throw 'Inno Setup compiler (ISCC.exe) not found. Install Inno Setup 6 or 7, or rerun with -SkipInstaller.' }
  Run-Native $compiler @((Join-Path $project 'packaging\windows\installer.iss'))
  Write-Host ('Installer built under ' + (Join-Path $project 'dist\installer')) -ForegroundColor Green
}
Write-Host 'Finished. Existing project data\ folder was never added to the installer.'
