param(
    [switch]$SkipModelWarmup
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$entryPoint = Join-Path $projectRoot "__main__.py"

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    throw "Python 3.10 or newer is required. Install Python and reopen PowerShell."
}

$pythonVersion = & $pythonCommand.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0) {
    throw "Could not read the installed Python version."
}
$versionParts = $pythonVersion.Split(".")
if ([int]$versionParts[0] -lt 3 -or ([int]$versionParts[0] -eq 3 -and [int]$versionParts[1] -lt 10)) {
    throw "Python 3.10 or newer is required; found Python $pythonVersion."
}

if (-not (Test-Path $venvPython)) {
    & $pythonCommand.Source -m venv (Join-Path $projectRoot ".venv")
    if ($LASTEXITCODE -ne 0) {
        throw "Creating the project virtual environment failed."
    }
}

& $venvPython -m pip install --disable-pip-version-check -r (Join-Path $projectRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Installing Agentic Memory dependencies failed."
}

if (-not $SkipModelWarmup) {
    Push-Location $projectRoot
    try {
        & $venvPython -c "from config import EMBEDDING_DIM, EMBEDDING_MODEL; from embeddings import get_embedding; vector = get_embedding('local Agentic Memory setup check'); assert vector.shape == (EMBEDDING_DIM,), f'Expected {EMBEDDING_DIM} dimensions, got {vector.shape}'; print(f'Model ready: {EMBEDDING_MODEL} ({vector.shape[0]} dimensions)')"
        if ($LASTEXITCODE -ne 0) {
            throw "Hugging Face model download/load failed. Check network access and retry, or warm the model before enabling offline mode."
        }
    }
    finally {
        Pop-Location
    }
}

Write-Host ""
Write-Host "Local environment is ready. The model is cached by Hugging Face in its shared user cache (HF_HOME/HF_HUB_CACHE if configured)."
Write-Host "Register the MCP with Copilot CLI:"
Write-Host ('  copilot mcp add agentic-memory --tools "*" -- "{0}" "{1}"' -f $venvPython, $entryPoint)
Write-Host ""
Write-Host "After model warmup, optional offline registration:"
Write-Host ('  copilot mcp add agentic-memory --tools "*" --env AGENTIC_MEMORY_HF_HUB_OFFLINE=1 -- "{0}" "{1}"' -f $venvPython, $entryPoint)
