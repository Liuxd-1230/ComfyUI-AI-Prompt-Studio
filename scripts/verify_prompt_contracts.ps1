$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repositoryRoot
try {
    Write-Host "[PH9 1/4] Unit, integration, mock Gateway, workflow, and node-loader tests"
    python -m pytest tests/ -q
    if ($LASTEXITCODE -ne 0) { throw "pytest failed with exit code $LASTEXITCODE" }

    Write-Host "[PH9 2/4] Python compilation"
    python -m compileall nodes services renderers validators schemas server prompting domain tests
    if ($LASTEXITCODE -ne 0) { throw "compileall failed with exit code $LASTEXITCODE" }

    Write-Host "[PH9 3/4] JavaScript syntax"
    foreach ($script in Get-ChildItem -LiteralPath web -Filter *.js | Sort-Object Name) {
        node --check $script.FullName
        if ($LASTEXITCODE -ne 0) { throw "node --check failed: $($script.Name)" }
    }

    Write-Host "[PH9 4/4] Diff whitespace"
    git diff --check
    if ($LASTEXITCODE -ne 0) { throw "git diff --check failed with exit code $LASTEXITCODE" }

    Write-Host "PH9 prompt-contract regression passed."
} finally {
    Pop-Location
}
