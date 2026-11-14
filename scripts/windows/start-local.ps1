# Windows launcher for Syllabus Auditor.
# Compatible with Windows PowerShell 5.1 and newer PowerShell versions.
# Run via "Start Syllabus Auditor.bat" from CMD/VS Code.
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location -LiteralPath $ProjectRoot
$ErrorActionPreference = 'Stop'

$python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    Write-Host 'Creating the Syllabus Auditor Python environment...'
    & py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Unable to create the Python virtual environment.' }
}
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Python was not found in .venv\Scripts\python.exe.'
}

# In Windows PowerShell 5.1, a native process writing to stderr with
# ErrorActionPreference=Stop can trigger NativeCommandError (even for an
# expected missing-module check). Native-program exit codes are checked
# explicitly below instead of treating all stderr as a PowerShell failure.
$ErrorActionPreference = 'Continue'
Write-Host 'Checking required application dependencies...'
& $python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host 'The required dependencies could not be installed.' -ForegroundColor Red
    exit 1
}

$model = Join-Path $ProjectRoot 'models\Qwen3-1.7B-Q4_K_M.gguf'
if (Test-Path -LiteralPath $model) {
    # The checker catches missing packages and DLL failures without a traceback.
    $runtimeCheck = Join-Path $ProjectRoot 'tools\check_ai_runtime.py'
    & $python $runtimeCheck
    $installed = ($LASTEXITCODE -eq 0)
    if (-not $installed -and $env:SA_SKIP_AI_INSTALL -ne '1') {
        Write-Host 'Installing local AI runtime (llama-cpp-python)...'
        Write-Host 'On Python 3.14, this may require a compatible wheel or Windows build tools.'
        & $python -m pip install --prefer-binary --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu 'llama-cpp-python>=0.3.5,<1'
        if ($LASTEXITCODE -ne 0) {
            Write-Warning 'Could not install the embedded AI runtime. The regular syllabus checker can still run.'
        }
    }
    # A package may be present while a native DLL is still missing.
    # Do not block the web app if the runtime is unavailable.
    & $python $runtimeCheck
    if ($LASTEXITCODE -eq 0) {
        Write-Host 'Embedded AI runtime: available.' -ForegroundColor Green
    } else {
        Write-Warning 'Embedded AI runtime: unavailable. The standard validator remains available.'
    }
} else {
    Write-Warning 'AI model file is missing. Standard syllabus checks are still available.'
}

Write-Host 'Starting Syllabus Auditor at http://127.0.0.1:8765/' -ForegroundColor Cyan
& $python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
exit $LASTEXITCODE
